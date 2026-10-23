#!/usr/bin/env python3
"""Real client namespace -> LAN DNS redirect/Fake-IP -> TProxy -> local SOCKS.
All TLS/DNS/SOCKS peers are local fixtures. The host network is never modified.
"""
import contextlib
import ipaddress
import json
import os
import pathlib
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from integration import HTTPSServer, HTTPSResolver, Server, SOCKS, Echo

binary, work = str(pathlib.Path(sys.argv[1]).resolve()), pathlib.Path(sys.argv[2]).resolve()
assert os.environ['FLOWDNS_TEST_PARENT_NETNS'] != os.readlink('/proc/self/ns/net')
assert [x['ifname'] for x in json.loads(subprocess.check_output(['ip', '-j', 'link']))] == ['lo']
def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)
run('ip', 'link', 'set', 'lo', 'up')
with contextlib.ExitStack() as stack, tempfile.TemporaryDirectory(prefix='flowdns-lan-') as temp:
    root = pathlib.Path(temp)
    client = subprocess.Popen(['unshare', '--net', 'sleep', '120'])
    stack.callback(client.wait); stack.callback(client.terminate)
    for _ in range(50):
        if os.readlink(f'/proc/{client.pid}/ns/net') != os.readlink('/proc/self/ns/net'): break
        time.sleep(.01)
    def cli(*args):
        return run('nsenter', '-t', str(client.pid), '-n', *args)
    run('ip', 'link', 'add', 'br-lan', 'type', 'veth', 'peer', 'name', 'client0')
    run('ip', 'link', 'set', 'client0', 'netns', str(client.pid))
    for command in [('ip', 'addr', 'add', '10.77.0.1/24', 'dev', 'br-lan'),
                    ('ip', '-6', 'addr', 'add', 'fd77::1/64', 'dev', 'br-lan', 'nodad'),
                    ('ip', 'link', 'set', 'br-lan', 'up')]: run(*command)
    cli('ip', 'link', 'set', 'lo', 'up')
    cli('ip', 'addr', 'add', '10.77.0.2/24', 'dev', 'client0')
    cli('ip', '-6', 'addr', 'add', 'fd77::2/64', 'dev', 'client0', 'nodad')
    cli('ip', 'link', 'set', 'client0', 'up')
    cli('ip', 'route', 'add', 'default', 'via', '10.77.0.1')
    cli('ip', '-6', 'route', 'add', 'default', 'via', 'fd77::1')
    cert, key = root / 'cert.pem', root / 'key.pem'
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
        '-addext', 'subjectAltName=DNS:localhost', '-keyout', str(key), '-out', str(cert))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, key)
    servers = []
    for handler in (HTTPSResolver, HTTPSResolver, SOCKS, Echo):
        server = stack.enter_context((HTTPSServer if handler is HTTPSResolver else Server)(('127.0.0.1', 0), handler))
        server.tls, server.queries, server.connections = tls, [], []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.shutdown); servers.append(server)
    domestic, overseas, proxy, target = servers
    config = json.loads((work / 'config-1.json').read_text())
    for entry, server in zip(config['dns']['servers'][:2], (domestic, overseas)):
        entry['server'], entry['server_port'] = server.server_address
        entry['tls'] = dict(enabled=True, server_name='localhost', certificate_path=str(cert))
    config['outbounds'][1]['server_port'] = proxy.server_address[1]
    config['log']['output'] = str(root / 'core.log')
    config['experimental']['cache_file']['path'] = str(root / 'cache.db')
    path = root / 'config.json'; path.write_text(json.dumps(config))
    with (root / 'launch.log').open('w') as log:
        process = subprocess.Popen([binary, 'run', '-c', str(path)], stdout=log, stderr=log)
        stack.callback(process.wait); stack.callback(process.terminate)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', 16553), .1): break
            except OSError:
                assert process.poll() is None, (root / 'launch.log').read_text()
                time.sleep(.05)
        run('nft', '-f', str(work / 'firewall.nft'))
        for family in ('-4', '-6'):
            run('ip', family, 'route', 'add', 'local', 'default', 'dev', 'lo', 'table', '20260')
            run('ip', family, 'rule', 'add', 'pref', '20260', 'fwmark', '0x40000000/0x40000000', 'lookup', '20260')
        script = root / 'client.py'
        script.write_text('''import ipaddress, socket, struct
+def dns(name, server, tcp=False, aaaa=False):
+    packet = b'FD\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00' + b''.join(bytes([len(x)])+x.encode() for x in name.split('.')) + b'\\x00' + struct.pack('!HH',28 if aaaa else 1,1)
+    family = socket.AF_INET6 if ':' in server else socket.AF_INET
+    with socket.socket(family, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
+        s.settimeout(8)
+        if tcp:
+            s.connect((server,53)); s.sendall(struct.pack('!H',len(packet))+packet)
+            size = struct.unpack('!H',s.recv(2))[0]; answer=b''
+            while len(answer)<size: answer+=s.recv(size-len(answer))
+        else: s.sendto(packet,(server,53)); answer=s.recv(4096)
+    assert answer[:2]==b'FD' and answer[3]&15==0
+    return socket.inet_ntop(socket.AF_INET6 if aaaa else socket.AF_INET,answer[-16:] if aaaa else answer[-4:])
+assert dns('www.qq.com','10.77.0.1')=='127.0.0.1'
+assert dns('www.qq.com','fd77::1',True)=='127.0.0.1'
+fake4=dns('unknown.example','8.8.8.8')
+fake6=dns('unknown-v6.example','fd77::1',aaaa=True)
+assert ipaddress.ip_address(fake4) in ipaddress.ip_network('198.18.0.0/15')
+assert ipaddress.ip_address(fake6) in ipaddress.ip_network('fc00::/18')
+for host in (fake4,fake6):
+    with socket.create_connection((host,TARGET_PORT),timeout=8) as s:
+        s.settimeout(8); assert s.recv(100)==b'flowdns-route-ok'
+print('PASS: LAN IPv4/IPv6 DNS interception, TCP/UDP DNS, external DNS capture, Fake-IP and actual TProxy/SOCKS connections')
+'''.replace('\n+', '\n').replace('TARGET_PORT', str(target.server_address[1])))
        result = subprocess.run(['nsenter', '-t', str(client.pid), '-n', sys.executable, str(script)], capture_output=True, text=True, timeout=35)
        assert result.returncode == 0, result.stdout + result.stderr + (root / 'core.log').read_text()[-5000:]
        assert domestic.queries and overseas.queries and proxy.connections
        print(result.stdout.strip())
