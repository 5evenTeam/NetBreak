from __future__ import annotations

import socket
import threading

import pytest


@pytest.fixture
def quiet_stdout(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdout", io.StringIO())
    monkeypatch.setattr("sys.stderr", io.StringIO())


@pytest.fixture
def tcp_listener():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(32)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                conn, _address = server.accept()
            except OSError:
                return
            try:
                conn.close()
            except OSError:
                pass

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield server, server.getsockname()[1]
    finally:
        stop.set()
        server.close()


@pytest.fixture
def http_stub():
    payload = (
        b"HTTP/1.1 200 OK\r\n"
        b"Server: nginx/1.25.3\r\n"
        b"Content-Type: text/html\r\n"
        b"Content-Length: 25\r\n"
        b"\r\n"
        b"<html><title>stub</title>"
    )
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                conn, _address = server.accept()
            except OSError:
                return
            try:
                conn.recv(4096)
                conn.sendall(payload)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield server, server.getsockname()[1]
    finally:
        stop.set()
        server.close()
