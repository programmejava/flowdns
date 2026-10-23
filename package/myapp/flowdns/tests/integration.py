#!/usr/bin/env python3
"""Exercise the actual sing-box DNS/route engine against local TLS/SOCKS peers.

Usage: integration.py /path/to/sing-box /tmp/flowdns-tests
No public DNS, Internet access, route changes or firewall changes are used.
"""
import contextlib
import http.server
import ipaddress
import json
import os
import pathlib
import select
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import threading
import time


def receive(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError("short response")
        data += chunk
    return data


def query(name):
    labels = b"".join(bytes([len(x)]) + x.encode() for x in name.split("."))
    return b"FD\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + labels + b"\x00\x00\x01\x00\x01"


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TLSResolver(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with self.server.tls.wrap_socket(self.request, server_side=True) as conn:
                while True:
                    packet = receive(conn, struct.unpack("!H", receive(conn, 2))[0])
                    self.server.queries.append(packet)
                    response = packet[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00" + packet[12:]
                    response += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x7f\x00\x00\x01"
                    conn.sendall(struct.pack("!H", len(response)) + response)
        except (EOFError, OSError):
            pass


class HTTPSResolver(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        packet = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.queries.append(packet)
        response = packet[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00" + packet[12:]
        response += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x7f\x00\x00\x01"
        self.send_response(200)
        self.send_header("Content-Type", "application/dns-message")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


class HTTPSServer(Server):
    request_queue_size = 128

    def process_request_thread(self, request, client_address):
        # Reality probes and concurrent DoH clients share this controlled peer.
        # A stalled handshake must not block accept() for every other client.
        try:
            request.settimeout(5)
            request = self.tls.wrap_socket(request, server_side=True)
        except OSError:
            request.close()
            return
        super().process_request_thread(request, client_address)


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"flowdns-route-ok")


class SOCKS(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            header = receive(self.request, 2)
            receive(self.request, header[1])
            self.request.sendall(b"\x05\x00")
            _, command, _, atyp = receive(self.request, 4)
            if atyp == 1:
                host = socket.inet_ntop(socket.AF_INET, receive(self.request, 4))
            elif atyp == 3:
                host = receive(self.request, receive(self.request, 1)[0]).decode()
            else:
                host = socket.inet_ntop(socket.AF_INET6, receive(self.request, 16))
            port = struct.unpack("!H", receive(self.request, 2))[0]
            assert command == 1
            self.server.connections.append((host, port))
            if getattr(self.server, 'reject', False):
                self.request.sendall(b'\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00')
                return
            # Never allow the test proxy to contact a non-local destination.
            assert host in ("127.0.0.1", "::1")
            with socket.create_connection((host, port), timeout=3) as remote:
                self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                while True:
                    readable, _, _ = select.select([self.request, remote], [], [], 3)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (remote if source is self.request else self.request).sendall(data)
        except (EOFError, OSError):
            pass


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    binary, work = sys.argv[1], pathlib.Path(sys.argv[2])
    transport = sys.argv[3] if len(sys.argv) > 3 else "tls"
    assert transport in ("tls", "https")
    label = "DoT" if transport == "tls" else "DoH"
    cert, key = work / "test-cert.pem", work / "test-key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    with contextlib.ExitStack() as stack:
        servers = []
        resolver = TLSResolver if transport == "tls" else HTTPSResolver
        for handler in (resolver, resolver, SOCKS, Echo):
            server_type = HTTPSServer if handler is HTTPSResolver else Server
            server = stack.enter_context(server_type(("127.0.0.1", 0), handler))
            server.tls, server.queries, server.connections = tls, [], []
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            servers.append(server)
        domestic, overseas, proxy, target = servers
        config = json.loads((work / ("config-9.json" if transport == "tls" else "config-1.json")).read_text())
        for entry, server in zip(config["dns"]["servers"][:2], (domestic, overseas)):
            entry["server"], entry["server_port"] = server.server_address
            entry["tls"] = {"enabled": True, "server_name": "localhost", "certificate_path": str(cert)}
        config["outbounds"][1]["server_port"] = proxy.server_address[1]
        dns_port, routing_port = unused_port(), unused_port()
        config["inbounds"] = [
            {"type": "direct", "tag": "dns-in", "listen": "127.0.0.1", "listen_port": dns_port},
            {"type": "mixed", "tag": "tproxy-in", "listen": "127.0.0.1", "listen_port": routing_port},
        ]
        config["log"]["output"] = str(work / "integration.log")
        config["experimental"]["cache_file"]["path"] = str(work / "integration-cache.db")
        path = work / "integration.json"
        path.write_text(json.dumps(config))
        with open(work / "integration-stderr.log", "w") as log:
            process = subprocess.Popen([binary, "run", "-c", str(path)], stdout=log, stderr=log)
            stack.callback(lambda: process.wait(timeout=5))
            stack.callback(process.terminate)
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", routing_port), timeout=.1):
                        break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError((work / "integration-stderr.log").read_text())
                    time.sleep(.1)
            def dns(name):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(4)
                    sock.sendto(query(name), ("127.0.0.1", dns_port))
                    answer = sock.recv(4096)
                assert answer[:2] == b"FD" and answer[3] & 15 == 0
                return socket.inet_ntoa(answer[-4:])

            def connect(host):
                with socket.create_connection(("127.0.0.1", routing_port), timeout=4) as sock:
                    sock.settimeout(4)
                    sock.sendall(b"\x05\x01\x00")
                    assert receive(sock, 2) == b"\x05\x00"
                    try:
                        address = b"\x01" + socket.inet_aton(host)
                    except OSError:
                        address = b"\x03" + bytes([len(host)]) + host.encode()
                    sock.sendall(b"\x05\x01\x00" + address + struct.pack("!H", target.server_address[1]))
                    reply = receive(sock, 4)
                    assert reply[1] == 0, reply
                    receive(sock, (4 if reply[3] == 1 else 16) + 2)
                    assert receive(sock, len(b"flowdns-route-ok")) == b"flowdns-route-ok"

            assert dns("www.qq.com") == "127.0.0.1"
            assert domestic.queries and not overseas.queries
            print(f"PASS: domestic domain uses certificate-verified direct {label}")
            connect("www.qq.com")
            assert not proxy.connections
            print("PASS: domestic connection bypasses SOCKS")
            fake = dns("unknown.example")
            assert ipaddress.ip_address(fake) in ipaddress.ip_network("198.18.0.0/15")
            connect(fake)
            assert overseas.queries
            assert ("127.0.0.1", overseas.server_address[1]) in proxy.connections
            assert ("127.0.0.1", target.server_address[1]) in proxy.connections
            print(f"PASS: Fake-IP restores domain, resolves through proxied {label}, and proxies the actual connection")
            before = len(proxy.connections)
            connect("www.force-proxy.cn")
            assert len(proxy.connections) > before
            print("PASS: explicit proxy rule overrides domestic list and private resolved IP")
            assert dns("compat.example") == "127.0.0.1"
            print(f"PASS: compatibility exception returns a real IP through overseas {label}")
            proxy.reject = True
            try:
                blocked = False
                try:
                    connect(fake)
                except (OSError, EOFError, AssertionError):
                    blocked = True
                assert blocked, 'proxy failure unexpectedly reached the foreign target'
                before = len(proxy.connections)
                assert dns('www.qq.com') == '127.0.0.1'
                connect('www.qq.com')
                assert len(proxy.connections) == before
                assert process.poll() is None
            finally:
                proxy.reject = False
            connect(fake)
            assert process.poll() is None
            print('PASS: real SOCKS failure leaves domestic DNS/traffic available; foreign traffic recovers without restarting the core')
            if os.getenv('FLOWDNS_TEST_LUA') and os.getenv('FLOWDNS_TEST_MODULES'):
                modules = os.environ['FLOWDNS_TEST_MODULES']
                env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;')
                code = "local s=dofile('package/myapp/flowdns/src/system.lua'); local j=require 'luci.jsonc'; local ok,msg=s.query(tonumber(arg[1]),arg[2],arg[3]=='tcp'); print(j.stringify({ok=ok,message=msg})); os.exit(ok and 0 or 1)"
                driver = work / 'production-probe.lua'; driver.write_text(code)
                for domain in ('www.qq.com', 'unknown.example'):
                    for protocol in ('tcp', 'udp'):
                        result = subprocess.run([os.environ['FLOWDNS_TEST_LUA'], str(driver), str(dns_port), domain, protocol],
                                                capture_output=True, text=True, env=env, timeout=10)
                        assert result.returncode == 0 and json.loads(result.stdout)['ok'], result.stdout + result.stderr
                print('PASS: actual production diagnostic validates both TCP/UDP against the live core for domestic and foreign domains')
            print("All local sing-box integration checks passed")


if __name__ == "__main__":
    main()
