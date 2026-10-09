import importlib.util
from io import BytesIO
import os
from pathlib import Path
import socket
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "target" / "telnet.py"


def load_client():
    spec = importlib.util.spec_from_file_location("telnet_client_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Socket:
    """Fake shell socket: queued chunks, then EOF or endless timeouts."""

    def __init__(self, chunks, timeout_after=False):
        if isinstance(chunks, (bytes, str)):
            chunks = [chunks]
        self.chunks = [c.encode() if isinstance(c, str) else c for c in chunks]
        self.timeout_after = timeout_after
        self.sent = []

    def settimeout(self, _seconds):
        pass

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _size):
        if self.chunks:
            return self.chunks.pop(0)
        if self.timeout_after:
            raise socket.timeout()
        return b""


def _capture_stdout(fn):
    buffer = BytesIO()
    real_write = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else None

    class _Tee:
        def write(self, text):
            if real_write is not None:
                real_write.write(text.encode("utf-8", "replace"))
            buffer.write(text.encode("utf-8", "replace"))
        def flush(self):
            if real_write is not None:
                real_write.flush()

    old = sys.stdout
    sys.stdout = _Tee()
    try:
        result = fn()
    finally:
        sys.stdout = old
    return result, buffer.getvalue()


class TelnetClientTests(unittest.TestCase):
    def test_authenticate_sends_token_and_accepts_success(self):
        client = load_client()
        sock = _Socket(b"authenticated\n<<<END>>>\n")
        client._authenticate(sock, "secret")
        self.assertEqual(sock.sent, [b"auth secret\n"])

    def test_authenticate_rejects_failure(self):
        client = load_client()
        sock = _Socket(b"authentication required\n<<<END>>>\n")
        with self.assertRaisesRegex(RuntimeError, "authentication failed"):
            client._authenticate(sock, "wrong")

    def test_authenticate_is_a_noop_without_token(self):
        client = load_client()
        sock = _Socket(b"")
        client._authenticate(sock, None)
        self.assertEqual(sock.sent, [])


class StreamingTests(unittest.TestCase):
    """Progress instead of a hang: chunks echo live, the END marker never
    reaches stdout (callers parse it), split markers are held back."""

    def test_streaming_echoes_payload_without_the_marker(self):
        client = load_client()
        sock = _Socket(b"line one\nline two\n<<<END>>>\n")
        payload, echoed = _capture_stdout(
            lambda: client._recv_until_end(sock, stream=True))
        self.assertEqual(payload, b"line one\nline two\n")
        self.assertEqual(echoed, b"line one\nline two\n")

    def test_streaming_holds_back_a_split_marker(self):
        client = load_client()
        sock = _Socket([b"ok\n<<<EN", b"D>>>\n"])
        payload, echoed = _capture_stdout(
            lambda: client._recv_until_end(sock, stream=True))
        self.assertEqual(payload, b"ok\n")
        self.assertEqual(echoed, b"ok\n")  # no partial marker leaked

    def test_buffered_mode_is_unchanged(self):
        client = load_client()
        sock = _Socket(b"payload\n<<<END>>>\n")
        _payload, echoed = _capture_stdout(
            lambda: client._recv_until_end(sock))
        self.assertEqual(_payload, b"payload\n")
        self.assertEqual(echoed, b"")  # buffered: nothing printed


class TimeoutTests(unittest.TestCase):
    """Activity-based timeouts with unambiguous, actionable messages."""

    def test_first_chunk_timeout_names_the_half_boot_guard(self):
        client = load_client()
        sock = _Socket([], timeout_after=True)
        with self.assertRaisesRegex(
                RuntimeError, "waiting for the shell banner.*mid-boot"):
            client._recv_until_end(sock, first_timeout=0.05,
                                   desc="the shell banner")

    def test_idle_timeout_names_the_knob_not_mid_boot(self):
        client = load_client()
        sock = _Socket([b"first line\n"], timeout_after=True)
        with self.assertRaisesRegex(
                RuntimeError, "no more output for .*OTC_CMD_IDLE_TIMEOUT"):
            client._recv_until_end(sock, first_timeout=0.05,
                                   idle_timeout=0.05,
                                   desc="the reply to 'test run'")


if __name__ == "__main__":
    unittest.main()
