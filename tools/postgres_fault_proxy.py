"""Test-only, loopback PostgreSQL wire proxy. Never use with real credentials.

TLS/GSS must be disabled by the disposable test client. The proxy recognizes
frontend frames solely to withhold COMMIT responses, not to implement SQL.
"""
import select
import socket
import threading


class FrontendFrames:
    def __init__(self):
        self.buffer = bytearray()
        self.startup = True

    def feed(self, data):
        self.buffer.extend(data)
        committed = False
        while True:
            offset = 0 if self.startup else 1
            if len(self.buffer) < offset + 4:
                break
            length = int.from_bytes(self.buffer[offset:offset + 4], 'big')
            if not 4 <= length <= 16 * 1024 * 1024:
                raise ValueError('invalid test wire frame length')
            total = offset + length
            if len(self.buffer) < total:
                break
            frame = bytes(self.buffer[:total])
            del self.buffer[:total]
            if not self.startup and frame[:1] == b'Q' and frame[5:] == b'COMMIT\x00':
                committed = True
            self.startup = False
        return committed


class CommitProxy:
    """One client connection. Hold all backend bytes after COMMIT is forwarded."""
    def __init__(self, backend_port):
        self.backend_port = backend_port
        self.commit_seen = threading.Event()
        self.armed = threading.Event()
        self.stop = threading.Event()
        self.error = None
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            while not self.stop.is_set():
                try:
                    client, _ = self.listener.accept()
                    break
                except socket.timeout:
                    continue
            else:
                return
            with client, socket.create_connection(('127.0.0.1', self.backend_port), timeout=3) as backend:
                client.settimeout(3)
                frames = FrontendFrames()
                holding = False
                while not self.stop.is_set():
                    readable, _, _ = select.select([client, backend], [], [], 0.05)
                    # Process frontend first, before any newly ready COMMIT reply.
                    for connection in (client, backend):
                        if connection not in readable:
                            continue
                        data = connection.recv(65536)
                        if not data:
                            return
                        if connection is client:
                            commit = frames.feed(data) and self.armed.is_set()
                            holding = holding or commit
                            backend.sendall(data)
                            if commit:
                                self.commit_seen.set()
                        elif not holding:
                            client.sendall(data)
                        # While holding, discard server bytes. The test independently
                        # observes the durable receipt, then cuts this connection.
        except Exception as error:
            if not self.stop.is_set():
                self.error = type(error).__name__
        finally:
            self.listener.close()

    def cut(self):
        self.stop.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError('test proxy failed to stop')

    close = cut
