import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "telnet.py"


def load_client():
    spec = importlib.util.spec_from_file_location("telnet_client_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Socket:
    def __init__(self, response):
        self.response = response
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _size):
        response, self.response = self.response, b""
        return response


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


if __name__ == "__main__":
    unittest.main()
