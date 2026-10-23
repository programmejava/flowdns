#!/usr/bin/env python3
"""A stalled TLS peer must not serialize the controlled resolver's accept loop."""
import contextlib
import http.server
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from integration import HTTPSServer

class Reply(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204)
        self.end_headers()
    def log_message(self, *args):
        pass

with tempfile.TemporaryDirectory(prefix='flowdns-tls-fixture-') as folder:
    cert, key = Path(folder) / 'cert.pem', Path(folder) / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost', '-keyout', str(key), '-out', str(cert)],
                   check=True, capture_output=True)
    server = HTTPSServer(('127.0.0.1', 0), Reply)
    server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.tls.load_cert_chain(cert, key)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(socket.create_connection(server.server_address, timeout=1))  # No ClientHello.
            time.sleep(.1)
            started = time.monotonic()
            client = ssl.create_default_context(cafile=str(cert))
            raw = stack.enter_context(socket.create_connection(server.server_address, timeout=2))
            tls = stack.enter_context(client.wrap_socket(raw, server_hostname='localhost'))
            tls.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
            assert b' 204 ' in tls.recv(1024)
            assert time.monotonic() - started < 2
    finally:
        server.shutdown()
        server.server_close()
print('PASS: stalled TLS handshake cannot block concurrent controlled DNS/Reality fixture peers')
