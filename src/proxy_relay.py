"""A local relay that adds proxy credentials Chrome refuses to send itself.

Chrome cannot take a username and password on ``--proxy-server``; it raises a
native auth dialog WebDriver cannot reach. The old workaround was a small
extension answering ``onAuthRequired``, but Chrome 137+ ignores
``--load-extension`` outright, so on a current Chrome that approach silently
loads nothing and every page comes back blank.

So instead of asking Chrome to authenticate, we authenticate for it. This
listens on 127.0.0.1, injects ``Proxy-Authorization`` into the first request of
each connection, and pipes the rest straight through to the real proxy. Chrome
points at the loopback address and never sees a credential, which means it works
the same on any Chrome version, headless or not.

Almost all browser traffic is HTTPS, which is one ``CONNECT`` per connection --
exactly where a per-connection header injection belongs.
"""

from __future__ import annotations

import base64
import socket
import threading

BUFFER = 65536
IDLE_TIMEOUT = 300


class ProxyRelay:
    """Loopback front end for one upstream proxy that needs credentials."""

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.upstream = (host, port)
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._auth_header = f"Proxy-Authorization: Basic {token}\r\n".encode()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.port: int | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> int:
        """Bind an ephemeral loopback port and start serving. Returns the port."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(128)
        self._server = server
        self.port = server.getsockname()[1]

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    # -- plumbing ----------------------------------------------------------
    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except OSError:
                break  # socket closed by stop()
            threading.Thread(
                target=self._handle, args=(client,), daemon=True
            ).start()

    def _handle(self, client: socket.socket) -> None:
        upstream = None
        try:
            client.settimeout(IDLE_TIMEOUT)
            head, rest = self._read_headers(client)
            if not head:
                return

            upstream = socket.create_connection(self.upstream, timeout=30)
            upstream.settimeout(IDLE_TIMEOUT)
            upstream.sendall(self._with_auth(head) + rest)

            self._pipe_both(client, upstream)
        except OSError:
            pass
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

    @staticmethod
    def _read_headers(sock: socket.socket) -> tuple[bytes, bytes]:
        """Read up to the blank line. Returns (headers, leftover body bytes)."""
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(BUFFER)
            if not chunk:
                return b"", b""
            buffer += chunk
            if len(buffer) > 1_000_000:  # runaway client, not a real request
                return b"", b""
        head, _, rest = buffer.partition(b"\r\n\r\n")
        return head + b"\r\n\r\n", rest

    def _with_auth(self, head: bytes) -> bytes:
        """Drop any client-supplied proxy auth and put ours in its place."""
        lines = head.split(b"\r\n")
        kept = [
            line
            for line in lines
            if not line.lower().startswith(b"proxy-authorization:")
        ]
        # kept[0] is the request line; the header goes directly after it.
        return b"\r\n".join([kept[0]]) + b"\r\n" + self._auth_header + b"\r\n".join(
            kept[1:]
        )

    @staticmethod
    def _pipe_both(a: socket.socket, b: socket.socket) -> None:
        done = threading.Event()

        def pump(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(BUFFER)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                done.set()
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        first = threading.Thread(target=pump, args=(a, b), daemon=True)
        second = threading.Thread(target=pump, args=(b, a), daemon=True)
        first.start()
        second.start()
        first.join()
        second.join()
