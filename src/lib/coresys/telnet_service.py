"""Remote shell service: one telnet-style command channel for the whole device.

Replaces the legacy HTTP API and the separate debug console with a single TCP
listener on the standard telnet port (23 by default). Stock ``telnet`` and
``nc`` clients work as-is:

    $ telnet 10.9.30.76
    micropy-system shell (otc)
    Type 'help' for commands.
    <<<END>>>
    status
    {"service": "otc", "version": "1.1.22", ...}
    <<<END>>>

Protocol: plain text lines. Each client line is a command; the server
answers with zero or more output lines followed by ``<<<END>>>\n``.
``exit``/``quit`` closes the connection. Passing ``auth_token`` requires each
client to authenticate with ``auth TOKEN`` before any command is accepted.
The persistent Python eval loop is available only when the application
explicitly constructs the service with ``allow_repl=True``; it is disabled by
default. RFC 854 IAC sequences sent by real telnet clients are stripped, so no
option negotiation is required.

Built-in commands: ``status`` (one-line JSON), ``log [N]``, ``heap``,
``reboot``, ``help``, plus optional ``repl``. Applications extend the command
table with ``add()`` (e.g. ``selftest``). One client at a time; handler
exceptions are contained to that request and never reach the control loop.
"""

import gc
import io
import sys
import time

import uasyncio as asyncio
import ujson as json
import machine

import lib.coresys.logger as logger
from lib.coresys.ota_state import load_state

END_MARKER = "<<<END>>>"
DEFAULT_PORT = 23          # standard telnet port
LOG_WINDOW = 16384         # max bytes read when tailing the log


def _strip_telnet(raw):
    """Drop RFC 854 IAC triples so stock telnet clients can talk to us."""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] == 0xFF and i + 2 < n:
            i += 3
            continue
        out.append(raw[i])
        i += 1
    return bytes(out)


class TelnetService:
    """One line-command listener: built-ins plus app-registered commands."""

    def __init__(self, wifi=None, port=DEFAULT_PORT, name="micropy-system",
                 log_path="/log.txt", allow_repl=False, auth_token=None):
        self.wifi = wifi
        self.port = int(port)
        self.name = name
        self.log_path = log_path
        self.allow_repl = bool(allow_repl)
        self.auth_token = str(auth_token) if auth_token else None
        self._commands = {}
        self._busy = False

    # ------------------------------------------------------------- registration
    def add(self, command, handler, description=""):
        """Register an app command: handler(args) -> text (may span lines)."""
        self._commands[str(command).lower()] = (handler, description)

    # ------------------------------------------------------------------ builtins
    def _status(self, _args):
        d = {"service": self.name}
        try:
            d["version"] = open("/version.txt").read().strip()
        except OSError:
            d["version"] = None
        try:
            st = load_state()
            d["slot"] = {"active": st.get("active"),
                         "pending": st.get("pending"),
                         "rejected": st.get("rejected_version")}
        except Exception:
            d["slot"] = None
        d["uptime_s"] = time.ticks_ms() // 1000
        d["heap_free"] = gc.mem_free()
        w = self.wifi
        if w is not None:
            try:
                d["wifi"] = {"state": w.get_state(), "ip": w.get_ip(),
                             "rssi": w.get_signal_strength(),
                             "ssid": w.get_ssid()}
            except Exception:
                d["wifi"] = None
        return json.dumps(d)

    def _log(self, args):
        n = 40
        if args:
            try:
                n = int(args.split()[0])
            except ValueError:
                pass
        n = min(200, max(1, n))
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                window = min(size, LOG_WINDOW)
                f.seek(size - window)
                data = f.read()
        except OSError:
            return "(no log)"
        lines = [l for l in data.decode("utf-8", "replace").split("\n")
                 if l != ""]
        if size > LOG_WINDOW and lines:
            lines = lines[1:]  # first line in the window is truncated
        return "\n".join(lines[-n:]) or "(empty log)"

    def _heap(self, _args):
        gc.collect()
        return "heap_free=%d heap_used=%d" % (gc.mem_free(), gc.mem_alloc())

    def _help(self, _args):
        rows = [
            "status    one-line JSON: version, slot, uptime, heap, wifi",
            "log [N]   last N log lines (default 40, max 200)",
            "heap      heap free/used after a GC pass",
            "reboot    acknowledge, then machine.reset()",
            "help      this list",
        ]
        if self.allow_repl:
            rows.insert(-1,
                        "repl      persistent Python eval loop (exit closes the link)")
        for name in sorted(self._commands):
            _handler, desc = self._commands[name]
            rows.append("%-10s %s" % (name, desc or "app command"))
        return "\n".join(rows)

    # -------------------------------------------------------------------- lifecycle
    async def start(self):
        """Bind the listener and serve until the loop is torn down."""
        try:
            await asyncio.start_server(self._handle, "0.0.0.0", self.port)
        except OSError as e:
            logger.error("Telnet: cannot listen on :%s (%s)" % (self.port, e),
                         log_to_file=True)
            return  # task ends cleanly; the app keeps running
        ip = None
        if self.wifi is not None:
            try:
                ip = self.wifi.get_ip()
            except Exception:
                ip = None
        logger.info("Telnet: listening on %s (shell :%s)"
                    % (ip or "0.0.0.0", self.port), log_to_file=True)
        while True:
            await asyncio.sleep(3600)

    # -------------------------------------------------------------------- handler
    async def _handle(self, reader, writer):
        if self._busy:
            # A second client may only be REJECTED; it must not clear the
            # flag the active client still owns.
            try:
                writer.write(("busy: one client at a time\n"
                              + END_MARKER + "\n").encode())
                await writer.drain()
            finally:
                await self._close(writer)
            return
        self._busy = True
        try:
            authenticated = self.auth_token is None
            auth_notice = ("Authentication required: auth TOKEN\n"
                           if not authenticated else "")
            writer.write(("micropy-system shell (%s)\n" % self.name
                          + auth_notice + "Type 'help' for commands.\n"
                          + END_MARKER + "\n").encode())
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = _strip_telnet(line).decode("utf-8", "replace").strip()
                if not text:
                    continue
                if text in ("exit", "quit"):
                    break
                if not authenticated:
                    command, _, supplied = text.partition(" ")
                    if (command.lower() == "auth"
                            and supplied.strip() == self.auth_token):
                        authenticated = True
                        response = "authenticated"
                    else:
                        response = "authentication required"
                    writer.write((response + "\n" + END_MARKER + "\n").encode())
                    await writer.drain()
                    continue
                if text.lower() == "repl":
                    if self.allow_repl:
                        await self._repl(reader, writer)
                        break  # the repl owns the rest of the connection
                    writer.write(("repl disabled\n" + END_MARKER + "\n").encode())
                    await writer.drain()
                    continue
                await self._dispatch(text, writer)
        except Exception as e:
            logger.error("Telnet handler error: %s" % e, log_to_file=True)
        finally:
            self._busy = False
            await self._close(writer)

    @staticmethod
    async def _close(writer):
        """Release the socket.

        uasyncio builds differ: ``close()`` may be a coroutine (await it)
        while the transport is finalized by ``wait_closed()``; host test
        fakes are plain synchronous calls. Cover both so the socket is
        always released -- otherwise the Pico's small socket pool leaks
        until new connections time out.
        """
        try:
            close = writer.close()
            if close is not None and hasattr(close, "__await__"):
                await close
        except Exception:
            pass
        try:
            wait = writer.wait_closed()
            if wait is not None and hasattr(wait, "__await__"):
                await wait
        except Exception:
            pass

    async def _dispatch(self, line, writer):
        name, _, arg = line.partition(" ")
        name = name.strip().lower()
        arg = arg.strip()

        if name == "reboot":
            writer.write(("rebooting\n" + END_MARKER + "\n").encode())
            await writer.drain()
            logger.error("Telnet: reboot requested", log_to_file=True)
            await asyncio.sleep(0.3)
            machine.reset()
            return  # unreachable

        builtins = {"status": self._status, "log": self._log,
                    "heap": self._heap, "help": self._help}
        handler = builtins.get(name)
        if handler is None and name in self._commands:
            handler = self._commands[name][0]
        if handler is None:
            out = "unknown command: %s (try 'help')" % name
        else:
            try:
                out = handler(arg)
            except Exception as e:
                out = "error: %s" % e
                logger.error("Telnet command '%s' failed: %s" % (name, e),
                             log_to_file=True)
        # App handlers may be coroutines (async I/O that must not block the
        # board); await them when they are.
        if hasattr(out, "__await__"):
            try:
                out = await out
            except Exception as e:
                out = "error: %s" % e
                logger.error("Telnet command '%s' failed: %s" % (name, e),
                             log_to_file=True)
        if out is None:
            out = ""
        writer.write((str(out) + "\n" + END_MARKER + "\n").encode())
        await writer.drain()

    # ----------------------------------------------------------------------- repl
    async def _repl(self, reader, writer):
        ns = {"__name__": "pico-shell"}
        try:
            writer.write(("Python eval loop (persistent namespace).\n"
                          "Type 'exit' to end the connection.\n" +
                          END_MARKER + "\n").encode())
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = _strip_telnet(line).decode("utf-8", "replace").strip()
                if not text:
                    continue
                if text in ("exit", "quit"):
                    break
                try:
                    out, err_text = self._eval_line(text, ns)
                except Exception as e:
                    # Never let the error-reporting path kill the repl loop.
                    out, err_text = "", "error: %s: %s\n" % (type(e).__name__, e)
                writer.write((out + err_text + END_MARKER + "\n").encode())
                await writer.drain()
        except Exception as e:
            logger.error("Telnet repl error: %s" % e, log_to_file=True)

    @staticmethod
    def _eval_line(text, ns):
        output = []

        def console_print(*values, **kwargs):
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            output.append(sep.join(str(value) for value in values) + end)

        ns["print"] = console_print
        err_text = ""
        try:
            try:
                result = eval(text, ns)
            except SyntaxError:
                exec(text, ns)
                result = None
            if result is not None:
                output.append(repr(result) + "\n")
        except Exception as e:
            errbuf = io.StringIO()
            # MicroPython (1.29.0 Pico builds) rejects the file= keyword here;
            # pass the stream positionally. Verified on-device.
            sys.print_exception(e, errbuf)
            err_text = errbuf.getvalue()
        return "".join(output), err_text
