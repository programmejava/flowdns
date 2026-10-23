#!/usr/bin/env python3
"""Real DNS/nft-set -> kernel bypass or Xray TProxy -> VLESS -> target.

Router, LAN client and target live in isolated network namespaces. All
resolvers and proxy peers are local; the host network is never changed.
"""
import contextlib
import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from integration import HTTPSServer, Server, SOCKS

engine, xray, work, lua, modules = [str(pathlib.Path(v).resolve()) for v in sys.argv[1:]]
work = pathlib.Path(work)
assert os.environ['FLOWDNS_TEST_PARENT_NETNS'] != os.readlink('/proc/self/ns/net')
assert [v['ifname'] for v in json.loads(subprocess.check_output(['ip', '-j', 'link']))] == ['lo']

def run(*args, check=True, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r

with contextlib.ExitStack() as stack, tempfile.TemporaryDirectory(prefix='flowdns-native-') as temp:
    root = pathlib.Path(temp)
    (root / 'run').mkdir()
    run('ip', 'link', 'set', 'lo', 'up')
    run('sysctl', '-w', 'net.ipv4.ip_forward=1')
    run('sysctl', '-w', 'net.ipv6.conf.all.forwarding=1')
    peers = {}
    for name, interface, subnet, v6 in (('client', 'br-lan', '77', '77'), ('target', 'target0', '88', '88')):
        p = subprocess.Popen(['unshare', '--net', 'sleep', '300'])
        stack.callback(p.wait); stack.callback(p.terminate)
        peers[name] = p
        for _ in range(100):
            if os.readlink(f'/proc/{p.pid}/ns/net') != os.readlink('/proc/self/ns/net'):
                break
            time.sleep(.01)
        run('ip', 'link', 'add', interface, 'type', 'veth', 'peer', 'name', 'peer0')
        run('ip', 'link', 'set', 'peer0', 'netns', str(p.pid))
        run('ip', 'addr', 'add', f'10.{subnet}.0.1/24', 'dev', interface)
        run('ip', '-6', 'addr', 'add', f'fd{v6}::1/64', 'dev', interface, 'nodad')
        run('ip', 'link', 'set', interface, 'up')
        def ns(*args):
            return run('nsenter', '-t', str(p.pid), '-n', *args)
        ns('ip', 'link', 'set', 'lo', 'up')
        ns('ip', 'addr', 'add', f'10.{subnet}.0.2/24', 'dev', 'peer0')
        ns('ip', '-6', 'addr', 'add', f'fd{v6}::2/64', 'dev', 'peer0', 'nodad')
        ns('ip', 'link', 'set', 'peer0', 'up')
        ns('ip', 'route', 'add', 'default', 'via', f'10.{subnet}.0.1')
        ns('ip', '-6', 'route', 'add', 'default', 'via', f'fd{v6}::1')
    target = peers['target']
    for address in ('203.0.113.2/24', '198.51.100.2/24', '198.51.100.3/24',
                    '2001:db8:44::2/48', '2001:db8:55::2/48', '2001:db8:55::3/48'):
        run('nsenter', '-t', str(target.pid), '-n', 'ip', '-6' if ':' in address else '-4',
            'addr', 'add', address, 'dev', 'lo', *(['nodad'] if ':' in address else []))
    for network in ('203.0.113.0/24', '198.51.100.0/24', '2001:db8:44::/48', '2001:db8:55::/48'):
        run('ip', '-6' if ':' in network else '-4', 'route', 'add', network, 'via', 'fd88::2' if ':' in network else '10.88.0.2')
    # IPv6 REDIRECT selects the ingress link-local address. Wait until its
    # automatic DAD completes before sending the first LAN DNS query.
    for _ in range(100):
        addresses = json.loads(run('ip', '-j', '-6', 'addr').stdout)
        if not any('tentative' in a or 'tentative' in a.get('flags', []) for link in addresses for a in link['addr_info']): break
        time.sleep(.05)
    else: raise AssertionError('fixture IPv6 DAD did not complete')
    target_script = root / 'target.py'
    target_script.write_text('''import json,os,pathlib,socket,socketserver,sys,threading,time
r=pathlib.Path(sys.argv[1])
def record(peer,kind):
    with (r/'peers.jsonl').open('a') as f: f.write(json.dumps([kind,peer[0]])+'\\n')
class TCP(socketserver.BaseRequestHandler):
    def handle(self):
        record(self.client_address,'tcp'); self.request.sendall(b'native-ok')
        while True:
            data=self.request.recv(256)
            if not data: break
            self.request.sendall(data)
class UDP(socketserver.BaseRequestHandler):
    def handle(self): record(self.client_address,'udp'); self.request[1].sendto(b'native-ok',self.client_address)
for family,hosts in ((socket.AF_INET,['203.0.113.2','198.51.100.2','198.51.100.3']),
                     (socket.AF_INET6,['2001:db8:44::2','2001:db8:55::2','2001:db8:55::3'])):
    for base,handler,host in [(socketserver.ThreadingTCPServer,TCP,'::' if family==socket.AF_INET6 else '0.0.0.0')]+[(socketserver.ThreadingUDPServer,UDP,host) for host in hosts]:
        class S(base):
            address_family=family; allow_reuse_address=True; daemon_threads=True
            def server_bind(self):
                if self.address_family==socket.AF_INET6: self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                super().server_bind()
        server=S((host,18888),handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        if base is socketserver.ThreadingUDPServer:
            q=S((host,443),handler);threading.Thread(target=q.serve_forever,daemon=True).start()
(r/'target-ready').touch()
time.sleep(300)
''')
    p = subprocess.Popen(['nsenter', '-t', str(target.pid), '-n', sys.executable, str(target_script), temp])
    stack.callback(p.wait); stack.callback(p.terminate)
    for _ in range(100):
        if (root / 'target-ready').exists(): break
        assert p.poll() is None
        time.sleep(.02)

    cert, key = root / 'cert.pem', root / 'key.pem'
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost',
        '-addext', 'subjectAltName=DNS:localhost', '-keyout', str(key), '-out', str(cert))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, key)
    class Resolver(__import__('http.server', fromlist=['BaseHTTPRequestHandler']).BaseHTTPRequestHandler):
        def do_POST(self):
            packet = self.rfile.read(int(self.headers['Content-Length']))
            pos, labels = 12, []
            while packet[pos]:
                n = packet[pos]; labels.append(packet[pos + 1:pos + 1 + n].decode()); pos += n + 1
            end = pos + 5
            qtype = struct.unpack('!H', packet[pos + 1:pos + 3])[0]
            name = '.'.join(labels)
            suffix = '3' if 'manual-direct' in name else '2'
            foreign = 'qq.com' not in name and 'manual-proxy' not in name
            family = socket.AF_INET6 if qtype == 28 else socket.AF_INET
            address = ('2001:db8:55::' if foreign else '2001:db8:44::') + suffix if qtype == 28 else ('198.51.100.' if foreign else '203.0.113.') + suffix
            data = socket.inet_pton(family, address)
            answer = packet[:2] + b'\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00' + packet[12:end]
            answer += b'\xc0\x0c' + struct.pack('!HHIH', qtype, 1, 60, len(data)) + data
            self.send_response(200); self.send_header('Content-Type', 'application/dns-message')
            self.send_header('Content-Length', str(len(answer))); self.end_headers(); self.wfile.write(answer)
        def log_message(self, *args): pass
    servers = []
    for cls, handler in ((HTTPSServer, Resolver), (HTTPSServer, Resolver), (Server, SOCKS)):
        server = stack.enter_context(cls(('127.0.0.1', 0), handler))
        server.tls, server.connections = tls, []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.shutdown); servers.append(server)
    domestic, overseas, socks = servers
    def remap(value):
        if isinstance(value, dict): return {k: remap(v) for k, v in value.items()}
        if isinstance(value, list): return [remap(v) for v in value]
        if isinstance(value, str): return value.replace('/var/run/flowdns', str(root / 'run'))
        return value
    dns = remap(json.loads((work / 'native-dns.json').read_text()))
    for entry, server in zip(dns['dns']['servers'][:2], (domestic, overseas)):
        entry['server'], entry['server_port'] = server.server_address
        entry['tls'] = dict(enabled=True, server_name='localhost', certificate_path=str(cert))
    dns['outbounds'][1]['server_port'] = socks.server_address[1]
    dns['experimental']['cache_file']['path'] = str(root / 'cache.db')
    (root / 'run/config.json').write_text(json.dumps(dns))
    native = remap(json.loads((work / 'native-xray.json').read_text()))
    native_outbound = next(v for v in native['outbounds'] if v['protocol'] == 'vless')
    node = native_outbound['settings']['vnext'][0]
    node['port'] = 33445
    proxy_server = dict(log=dict(loglevel='warning'), inbounds=[dict(listen='127.0.0.1', port=33445, protocol='vless',
        settings=dict(clients=[dict(id=node['users'][0]['id'])], decryption='none'))], outbounds=[dict(protocol='freedom')])
    if os.environ.get('FLOWDNS_TEST_REALITY') == '1':
        keys = subprocess.check_output([xray, 'x25519'], text=True)
        private = re.search(r'Private key:\s*(\S+)', keys).group(1)
        public = re.search(r'(?:Public key|Password):\s*(\S+)', keys).group(1)
        node['users'][0]['flow'] = 'xtls-rprx-vision-udp443'
        native_outbound['streamSettings'] = dict(network='raw', security='reality', realitySettings=dict(
            publicKey=public, shortId='aabb', serverName='localhost', fingerprint='chrome'))
        inbound = proxy_server['inbounds'][0]
        inbound['settings']['clients'][0]['flow'] = 'xtls-rprx-vision'
        inbound['streamSettings'] = dict(network='raw', security='reality', realitySettings=dict(
            dest='127.0.0.1:' + str(overseas.server_address[1]), serverNames=['localhost'], privateKey=private, shortIds=['aabb']))
    (root / 'run/xray.json').write_text(json.dumps(native))
    server_file = root / 'node.json'; server_file.write_text(json.dumps(proxy_server))
    log = stack.enter_context((root / 'node.log').open('w'))
    p = subprocess.Popen([xray, 'run', '-config', str(server_file)], stdout=log, stderr=log)
    stack.callback(p.wait); stack.callback(p.terminate)
    frontend_config = (work / 'native-dnsmasq.conf').read_text().replace('/var/run/flowdns', str(root / 'run'))
    # Empty user/group skips setgroups in the user namespace, while preserving
    # the real foreground TCP fork/IPC behavior. Never use --no-daemon here.
    frontend_config = frontend_config.replace('user=root\n', 'user=\n').replace('group=root\n', 'group=\n')
    (root / 'run/dnsmasq.conf').write_text(frontend_config)
    (root / 'run/active.nft').write_text((work / 'native-firewall.nft').read_text())
    (root / 'run/active.json').write_text((work / 'native-policy.json').read_text())
    (root / 'run/engine-mode').write_text('transparent')
    bindir = root / 'bin'; bindir.mkdir()
    (bindir / 'sing-box').symlink_to(engine); (bindir / 'xray').symlink_to(xray)
    frontend = str(pathlib.Path(os.environ['FLOWDNS_TEST_FRONT']).resolve())
    (bindir / 'flowdns-dns').symlink_to(frontend)
    helper = bindir / 'backend'
    import shlex
    helper.write_text('#!/bin/sh\nexec ' + shlex.quote(lua) + ' ' + shlex.quote(str(pathlib.Path('package/myapp/flowdns/tests/rpc-runtime.lua').resolve())) + ' ' + shlex.quote(str(pathlib.Path('package/myapp/flowdns/root/usr/libexec/flowdns').resolve())) + ' ' + shlex.quote(temp) + ' "$1" native-network-live "${2:-}" "${3:-}"\n')
    helper.chmod(0o755)
    wrapper = root / 'engine.sh'; wrapper.write_text(pathlib.Path('package/myapp/flowdns/root/usr/libexec/flowdns-engine').read_text().replace('/var/run/flowdns', str(root / 'run')).replace('/usr/libexec/flowdns-dns', str(bindir / 'flowdns-dns')).replace('/usr/libexec/flowdns ',str(helper)+' '))
    log = stack.enter_context((root / 'launch.log').open('w'))
    env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'], LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;')
    process = subprocess.Popen(['sh', str(wrapper), str(root / 'run/config.json')], env=env, stdout=log, stderr=log)
    stack.callback(lambda: process.wait(timeout=8)); stack.callback(process.terminate)
    (root / 'run/core.pid').write_text(str(process.pid))
    def backend(action, check=True):
        return run(lua, 'package/myapp/flowdns/tests/rpc-runtime.lua', 'package/myapp/flowdns/root/usr/libexec/flowdns',
                   temp, action, 'native-network-live', check=check, env=env, timeout=8)
    for _ in range(100):
        if backend('ready', False).returncode == 0: break
        assert process.poll() is None, (root / 'launch.log').read_text() + ((root / 'run/dnsmasq.log').read_text() if (root / 'run/dnsmasq.log').exists() else '')
        time.sleep(.05)
    else:
        details = (root / 'launch.log').read_text() + backend('ready', False).stdout
        for name in ('core', 'dns', 'front', 'transparent'):
            p = root / ('run/' + name + '.pid'); details += '\n' + name + ': ' + (p.read_text() if p.exists() else 'missing')
        for name in ('tcp', 'udp', 'tcp6', 'udp6'):
            details += '\n' + name + '\n' + pathlib.Path('/proc/net/' + name).read_text()
        raise AssertionError(details)
    backend('attach')
    client_script = root / 'client.py'
    client_script.write_text('''import json,socket,struct,sys
action,name=sys.argv[1:3]
if action=='dns':
    aaaa='AAAA' in sys.argv[3:]; tcp='TCP' in sys.argv[3:]
    packet=b'FD\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00'+b''.join(bytes([len(x)])+x.encode() for x in name.split('.'))+b'\\x00'+struct.pack('!HH',28 if aaaa else 1,1)
    with socket.socket(socket.AF_INET6 if aaaa else socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
        s.settimeout(6); s.connect(('fd77::1' if aaaa else '10.77.0.1',53))
        if tcp:
            s.sendall(struct.pack('!H',len(packet))+packet)
            length=s.recv(2); assert len(length)==2
            need=struct.unpack('!H',length)[0]; a=b''
            while len(a)<need:
                chunk=s.recv(need-len(a)); assert chunk; a+=chunk
        else: s.send(packet); a=s.recv(4096)
        if tcp: __import__('time').sleep(.05)
    assert a[:2]==b'FD' and a[3]&15==0
    print(socket.inet_ntop(socket.AF_INET6 if aaaa else socket.AF_INET,a[-16:] if aaaa else a[-4:]))
else:
    with socket.socket(socket.AF_INET6 if ':' in name else socket.AF_INET,socket.SOCK_DGRAM if action in ('udp','udp443') else socket.SOCK_STREAM) as s:
        s.settimeout(5); s.connect((name,443 if action=='udp443' else 18888))
        if action in ('udp','udp443'): s.send(b'test')
        assert s.recv(50)==b'native-ok'
    print('ok')
''')
    def client(*args, check=True):
        result = run('nsenter', '-t', str(peers['client'].pid), '-n', sys.executable, str(client_script), *args, check=False, timeout=8)
        if check and result.returncode:
            details = result.stdout + result.stderr + '\nclient action: ' + repr(args)
            for cmd in (('nft', 'list', 'table', 'inet', 'flowdns'), ('ip', '-4', 'rule'), ('ip', '-4', 'route', 'show', 'table', 'all')):
                details += '\n' + run(*cmd).stdout
            for name in ('launch.log', 'node.log', 'peers.jsonl', 'run/xray.log', 'run/dnsmasq.log', 'run/core.log', 'trace.log'):
                path = root / name
                if path.exists(): details += '\n' + name + '\n' + path.read_text()[-24000:]
            raise AssertionError(details)
        return result
    def peer():
        return json.loads((root / 'peers.jsonl').read_text().splitlines()[-1])[1]
    def learned(name, address):
        family = '6' if ':' in address else '4'
        run('nft', 'get', 'element', 'inet', 'flowdns', name + family, '{ ' + address + ' }')
    for aaaa in (False, True):
        args = ('AAAA',) if aaaa else ()
        direct = client('dns', 'www.qq.com', *args).stdout.strip()
        foreign = client('dns', 'outside.example', *args).stdout.strip()
        assert direct == ('2001:db8:44::2' if aaaa else '203.0.113.2'), direct
        assert foreign == ('2001:db8:55::2' if aaaa else '198.51.100.2'), foreign
        learned('domestic', direct); learned('foreign', foreign)
        for protocol in ('tcp', 'udp'):
            client(protocol, direct); assert peer() == ('fd77::2' if aaaa else '10.77.0.2'), peer()
            client(protocol, foreign); assert peer() == ('fd88::1' if aaaa else '10.88.0.1'), peer()
        print('PASS: real LAN IPv%d DNS learns nft sets; domestic TCP/UDP bypasses userspace, foreign TCP/UDP uses Xray/VLESS' % (6 if aaaa else 4))
    assert all(port == overseas.server_address[1] for _, port in socks.connections), socks.connections
    socks.reject = True
    client('tcp', '198.51.100.2'); client('udp', '198.51.100.2')
    socks.reject = False
    print('PASS: video/data connections do not traverse the SOCKS DNS exit')
    force = client('dns', 'manual-proxy.cn').stdout.strip(); learned('manual_proxy', force)
    client('tcp', force); assert peer() == '10.88.0.1'
    direct = client('dns', 'manual-direct.example').stdout.strip(); learned('manual_direct', direct)
    client('tcp', direct); assert peer() == '10.77.0.2'
    assert client('tcp', '198.18.0.77', check=False).returncode != 0
    print('PASS: explicit proxy overrides domestic IP; explicit direct overrides default proxy; stale Fake-IP is rejected')
    # Mixed TCP/UDP traffic must exercise real forked TCP workers alongside
    # the UDP parent's nftset writes, with all answers and learned sets intact.
    front_pid = int((root / 'run/front.pid').read_text())
    children_path = pathlib.Path(f'/proc/{front_pid}/task/{front_pid}/children')
    seen_children = set()
    def concurrent_query(i):
        flags = (['TCP'] if i % 3 else []) + (['AAAA'] if i % 2 else [])
        name = f'q{i}.outside.example'
        address = client('dns', name, *flags).stdout.strip()
        assert address == ('2001:db8:55::2' if i % 2 else '198.51.100.2'), address
        if children_path.exists(): seen_children.update(children_path.read_text().split())
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(concurrent_query, range(128)))
    assert seen_children, 'normal TCP fork path was not exercised'
    backend('ready')
    dns_log = (root / 'run/dnsmasq.log').read_text()
    assert not re.search(r'nftset .*?(?:netlink:|Error:)', dns_log), dns_log
    learned('foreign', '198.51.100.2'); learned('foreign', '2001:db8:55::2')
    client('tcp', '198.51.100.2'); client('udp', '198.51.100.2')
    print('PASS: 128 mixed dual-stack TCP/UDP DNS queries with concurrent real TCP children keep nftset learning and Xray forwarding healthy')
    for address in ('198.51.100.2','2001:db8:55::2'):
        client('udp443',address)
    run('nft','-f','/dev/stdin',input='delete table inet flowdns\n'+(work/'native-reject-firewall.nft').read_text())
    (root/'run/active.nft').write_text((work/'native-reject-firewall.nft').read_text())
    for address in ('203.0.113.2','2001:db8:44::2'):
        client('udp443',address)
    for address in ('198.51.100.2','2001:db8:55::2'):
        started=time.monotonic();assert client('udp443',address,check=False).returncode!=0
        assert time.monotonic()-started<2, 'QUIC reject must be immediate'
        client('udp',address)
    print('PASS: explicit allow carries real UDP443; router-level QUIC rejection is immediate for proxy IPv4/IPv6 only and preserves domestic/other UDP')
    stream_script=root/'stream.py'
    stream_script.write_text('''import pathlib,socket,sys,time
r=pathlib.Path(sys.argv[1]);s=socket.create_connection(('198.51.100.2',18888),5);s.settimeout(5)
assert s.recv(50)==b'native-ok'
for i in range(1000):
 s.sendall(b'x');assert s.recv(1)==b'x';(r/'stream-progress').write_text(str(i))
 if (r/'stream-stop').exists():break
 time.sleep(.05)
''')
    streamlog=stack.enter_context((root/'stream.log').open('w'))
    stream=subprocess.Popen(['nsenter','-t',str(peers['client'].pid),'-n',sys.executable,str(stream_script),temp],stdout=streamlog,stderr=streamlog)
    stack.callback(lambda: stream.wait(timeout=8) if stream.poll() is not None else (stream.terminate(),stream.wait(timeout=8)))
    for _ in range(100):
        if (root/'stream-progress').exists():break
        assert stream.poll() is None;time.sleep(.05)
    stable={name:(root/('run/'+name+'.pid')).read_text() for name in ('core','front','transparent')}
    run('nft','add','element','inet','flowdns','foreign4','{ 198.51.100.111 }')
    old_config=(root/'run/config.json').read_text()
    switched=json.loads(old_config)
    switched['dns']['servers'][1]['server_port']=domestic.server_address[1]
    policy=json.loads((root/'run/active.json').read_text());policy['overseas_dns']='cloudflare'
    def transaction(config, policy, token):
        request=dict(id=token,engine_pid=process.pid,started=time.time(),reason='fixture',policy=policy,
                     **{'from':dict(overseas='google'),'to':dict(overseas='cloudflare')})
        (root/'run/dns-next.json').write_text(json.dumps(config))
        (root/'run/dns-reload.json').write_text(json.dumps(request))
        (root/'run/dns-reload.response').unlink(missing_ok=True)
        (root/'run/dns-reload.request').write_text(token+' '+str(process.pid)+'\n')
        deadline=time.monotonic()+40
        while not (root/'run/dns-reload.response').exists():
            assert process.poll() is None,(root/'launch.log').read_text()
            assert stream.poll() is None,(root/'stream.log').read_text()
            assert time.monotonic()<deadline,(root/'launch.log').read_text()+(root/'run/dns-reload.log').read_text()
            time.sleep(.05)
        for name,pid in stable.items():assert (root/('run/'+name+'.pid')).read_text()==pid,name
        run('nft','get','element','inet','flowdns','foreign4','{ 198.51.100.111 }')
        return (root/'run/dns-reload.response').read_text().strip()
    old_dns=(root/'run/dns.pid').read_text()
    assert transaction(switched,policy,'1-1')=='1-1 done'
    assert (root/'run/dns.pid').read_text()!=old_dns
    assert json.loads((root/'run/active.json').read_text())['overseas_dns']=='cloudflare'
    client('dns','www.qq.com');client('dns','outside.example','TCP')
    bad=json.loads(json.dumps(switched));bad['inbounds'][0]['listen']='192.0.2.99'
    assert transaction(bad,dict(policy,overseas_dns='google'),'1-2')=='1-2 rolled-back'
    assert json.loads((root/'run/config.json').read_text())==switched
    assert json.loads((root/'run/active.json').read_text())['overseas_dns']=='cloudflare'
    assert json.loads((root/'run/dns-switch.json').read_text())['preserved'] is True
    client('dns','outside.example');client('tcp','198.51.100.2')
    assert int((root/'stream-progress').read_text())>10
    (root/'stream-stop').touch();assert stream.wait(timeout=5)==0,(root/'stream.log').read_text()
    print('PASS: DNS-only replacement and runtime bind-failure rollback preserve the SAME live TCP stream, Xray/frontend PIDs and learned nft elements')
    # Readiness requires each actual process, not ports held by unrelated PIDs.
    saved = (root / 'run/front.pid').read_text()
    (root / 'run/front.pid').write_text(str(os.getpid()))
    assert backend('ready', False).returncode != 0
    (root / 'run/front.pid').write_text(saved)
    backend('ensure'); backend('detach')
    children = [int((root / ('run/' + name + '.pid')).read_text()) for name in ('dns', 'front', 'transparent')]
    os.kill(children[2], 15)
    assert process.wait(timeout=8) != 0
    for pid in children:
        try: os.kill(pid, 0)
        except ProcessLookupError: pass
        else: raise AssertionError('transparent child leaked: ' + str(pid))
    print('PASS: production readiness checks all child owners; one child failure shuts down the complete engine group')
    if os.environ.get('FLOWDNS_TEST_REALITY') == '1':
        print('PASS: real VLESS Reality/Vision handshake and dual-stack TCP/UDP data plane against a local controlled node')
