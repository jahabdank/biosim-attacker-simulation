#!/usr/bin/env python3
"""TCP→UNIX relay. Trusted sidecar, not the operator.

Listens on TCP inside the internal docker network and forwards to a
host-broker UNIX socket bind-mounted into this sidecar only.
"""
from __future__ import annotations

import os
import socket
import threading

LISTEN_HOST = os.environ.get("RELAY_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("RELAY_LISTEN_PORT", "9377"))
UNIX_PATH = os.environ.get("RELAY_UNIX", "/run/broker/eclss.sock")


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(client: socket.socket) -> None:
    unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        unix.connect(UNIX_PATH)
        t1 = threading.Thread(target=_pipe, args=(client, unix), daemon=True)
        t2 = threading.Thread(target=_pipe, args=(unix, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except OSError:
        pass
    finally:
        client.close()
        unix.close()


def main() -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(32)
    print(f"unix-tcp-relay {LISTEN_HOST}:{LISTEN_PORT} -> {UNIX_PATH}", flush=True)
    while True:
        client, _ = srv.accept()
        threading.Thread(target=_handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())
