"""Local forwarding proxy server that chains to an upstream geo-proxy."""

from __future__ import annotations

import re
import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from geospoof.proxy_provider import ProxyInfo

BUFFER_SIZE = 65536


class _ProxyHandler(BaseHTTPRequestHandler):
    """Handles HTTP and CONNECT requests, forwarding via upstream proxy."""

    upstream: ProxyInfo  # set on the class before server starts

    def log_message(self, format: str, *args: object) -> None:
        # Suppress default logging
        pass

    def do_CONNECT(self) -> None:
        """Handle HTTPS CONNECT tunneling through upstream proxy."""
        upstream = self.upstream
        up_sock = None
        try:
            # Connect to the upstream proxy
            up_sock = socket.create_connection((upstream.host, upstream.port), timeout=10)
            # Send CONNECT to upstream
            connect_req = f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n\r\n"
            up_sock.sendall(connect_req.encode())

            # Read upstream response
            resp = up_sock.recv(BUFFER_SIZE)
            status_line = resp.split(b"\r\n")[0]
            if not re.match(rb"HTTP/\d\.\d\s+200\b", status_line):
                self.send_error(502, "Upstream proxy refused CONNECT")
                return

            # Tell client the tunnel is established
            self.send_response(200, "Connection Established")
            self.end_headers()

            # Relay data between client and upstream
            self._tunnel(self.connection, up_sock)
        except Exception:
            self.send_error(502, "Bad Gateway")
        finally:
            if up_sock:
                up_sock.close()

    def do_GET(self) -> None:
        self._forward_request()

    def do_POST(self) -> None:
        self._forward_request()

    def do_PUT(self) -> None:
        self._forward_request()

    def do_DELETE(self) -> None:
        self._forward_request()

    def do_HEAD(self) -> None:
        self._forward_request()

    def _forward_request(self) -> None:
        """Forward an HTTP request through the upstream proxy."""
        upstream = self.upstream
        up_sock = None
        try:
            up_sock = socket.create_connection((upstream.host, upstream.port), timeout=10)

            # Reconstruct the full request to send to the upstream proxy
            # Upstream proxy expects the full URL in the request line
            url = self.path
            if not url.startswith("http"):
                url = f"http://{self.headers['Host']}{self.path}"

            request_line = f"{self.command} {url} {self.request_version}\r\n"
            headers = ""
            for key, value in self.headers.items():
                headers += f"{key}: {value}\r\n"
            headers += "\r\n"

            up_sock.sendall((request_line + headers).encode())

            # Forward request body if present
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                up_sock.sendall(body)

            # Let the bidirectional relay handle the full response
            self._tunnel(self.connection, up_sock)
        except Exception:
            self.send_error(502, "Bad Gateway")
        finally:
            if up_sock:
                up_sock.close()

    @staticmethod
    def _tunnel(client: socket.socket, remote: socket.socket, timeout: float = 60) -> None:
        """Relay data between two sockets until one side closes."""
        sockets = [client, remote]
        while True:
            readable, _, errors = select.select(sockets, [], sockets, timeout)
            if errors or not readable:
                break
            for sock in readable:
                data = sock.recv(BUFFER_SIZE)
                if not data:
                    return
                target = remote if sock is client else client
                target.sendall(data)


class _ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class LocalProxyServer:
    """A local proxy server that forwards traffic through an upstream geo-proxy."""

    def __init__(self, upstream: ProxyInfo, port: int = 8888) -> None:
        if upstream.protocol != "http":
            raise ValueError(
                f"LocalProxyServer only chains to HTTP upstreams, "
                f"got {upstream.protocol!r}."
            )
        self.upstream = upstream
        self.port = port
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the proxy server in a background thread."""
        # Create a handler class with the upstream proxy info
        handler = type("Handler", (_ProxyHandler,), {"upstream": self.upstream})

        self._server = _ReusableTCPServer(("0.0.0.0", self.port), handler)

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the proxy server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
