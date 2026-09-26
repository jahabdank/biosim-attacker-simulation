#!/usr/bin/env python3
"""TLS CONNECT relay restricted to explicit model-provider hosts."""
from __future__ import annotations

import ipaddress
import os
import select
import socket
import socketserver
from http.server import BaseHTTPRequestHandler

ALLOWED = frozenset(os.environ.get("ALLOWED_MODEL_HOSTS", "auth.x.ai,api.x.ai,grok.com,accounts.x.ai,cli-chat-proxy.grok.com").split(","))


def public_addresses(host: str) -> list[tuple]:
    records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not records or any(not ipaddress.ip_address(r[4][0]).is_global for r in records):
        raise ValueError("nonpublic destination")
    return records


class Handler(BaseHTTPRequestHandler):
    timeout = 30
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_CONNECT(self) -> None:
        host, sep, port = self.path.rpartition(":")
        host = host.lower()
        if not sep or port != "443" or host not in ALLOWED:
            print("DENIED destination", host[:120], flush=True)
            self.send_error(403, "destination forbidden")
            return
        upstream = None
        try:
            records = public_addresses(host)
            for family, kind, proto, _, address in records:
                candidate = socket.socket(family, kind, proto)
                candidate.settimeout(15)
                try:
                    candidate.connect(address)
                    upstream = candidate
                    break
                except OSError:
                    candidate.close()
            if upstream is None:
                raise OSError("upstream unavailable")
            print("ALLOWED destination", host, flush=True)
            self.send_response(200, "Connection established")
            self.end_headers()
            self.wfile.flush()
            peers = [self.connection, upstream]
            for peer in peers:
                peer.settimeout(60)
            while True:
                readable, _, exceptional = select.select(peers, [], peers, 180)
                if exceptional or not readable:
                    break
                for source in readable:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    target = upstream if source is self.connection else self.connection
                    target.sendall(chunk)
        except (OSError, ValueError):
            if upstream is None:
                self.send_error(502, "upstream unavailable")
        finally:
            if upstream is not None:
                upstream.close()
            self.close_connection = True

    def do_GET(self) -> None:
        self.send_error(405, "CONNECT only")

    do_POST = do_GET
    do_PUT = do_GET


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 8080), Handler) as server:
        server.serve_forever()
