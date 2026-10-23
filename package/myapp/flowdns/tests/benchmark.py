#!/usr/bin/env python3
"""Validate the client benchmark with a local verified HTTPS test object."""
import http.server
import json
import pathlib
import ssl
import subprocess
import sys
import tempfile
import threading

with tempfile.TemporaryDirectory(prefix='flowdns-benchmark-') as temp:
    root = pathlib.Path(temp)
    cert, key = root / 'cert.pem', root / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                    '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = b'x' * 1048576
            self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        def log_message(self, *args):
            pass
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            output = root / 'report.json'
            result = subprocess.run([sys.executable, 'package/myapp/flowdns/tools/flowdns-benchmark.py', '--mode', 'direct',
                                     '--url', f'https://localhost:{server.server_port}/test.bin', '--ca-file', str(cert),
                                     '--runs', '1', '--parallel', '2', '--mib', '1', '--output', str(output)],
                                    capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stdout + result.stderr
            report = json.loads(output.read_text())
            assert report['samples'][0]['total_mbps'] > 0
            assert all(s['bytes'] == 1048576 and s['ttfb_ms'] > 0 for s in report['samples'][0]['streams'])
            print('PASS: benchmark verifies TLS, measures bounded parallel downloads/TTFB, and writes a real report')
        finally:
            server.shutdown()
