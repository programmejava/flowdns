#!/usr/bin/env python3
"""Start unmodified dual-stack DNS/TProxy in an isolated network namespace.

Usage: sh startup.sh SING_BOX WORK LUA MODULES
Uses the actual backend ready action, Lua libraries and kernel socket tables.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

binary, work, lua, modules = [str(pathlib.Path(x).resolve()) for x in sys.argv[1:]]
assert os.readlink('/proc/self/ns/net') != os.environ['FLOWDNS_TEST_PARENT_NETNS'], 'requires isolated network namespace'
links = json.loads(subprocess.check_output(['ip', '-j', 'link', 'show'], text=True))
assert [link['ifname'] for link in links] == ['lo'], 'requires an empty network namespace'
subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
with tempfile.TemporaryDirectory(prefix='flowdns-startup-') as temp:
    root = pathlib.Path(temp)
    config = json.loads((pathlib.Path(work) / 'config-1.json').read_text())
    config['log']['output'] = str(root / 'core.log')
    config['experimental']['cache_file']['path'] = str(root / 'cache.db')
    path = root / 'config.json'
    path.write_text(json.dumps(config))
    # Reproduce this router's ip-full error exactly, while all actual networking
    # remains in this namespace. All-table JSON dumps still use the real ip.
    real_ip = shutil.which('ip')
    bindir = root / 'bin'
    bindir.mkdir()
    shim = bindir / 'ip'
    shim.write_text('#!' + sys.executable + '\n' + '''import os, subprocess, sys
real_ip = ''' + repr(real_ip) + '''
args = sys.argv[1:]
if 'route' in args and args[-4:] == ['route', 'show', 'table', '20260']:
    result = subprocess.run([real_ip] + args, capture_output=True)
    if result.returncode and b'does not exist' in result.stderr:
        sys.stderr.write('Dump terminated\\n')
        sys.stdout.buffer.write(result.stdout)
        sys.exit(result.returncode)
os.execv(real_ip, [real_ip] + args)
''')
    shim.chmod(0o755)
    env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;', PATH=str(bindir) + ':' + os.environ['PATH'])
    missing = subprocess.run(['ip', '-4', 'route', 'show', 'table', '20260'], env=env, capture_output=True, text=True)
    assert missing.returncode != 0 and missing.stderr == 'Dump terminated\n', missing
    with (root / 'stderr.log').open('w') as log:
        process = subprocess.Popen([binary, 'run', '-c', str(path)], stdout=log, stderr=log)
        # Runtime PID identity is part of readiness, not merely occupied ports.
        (root / 'run').mkdir(exist_ok=True)
        (root / 'run/core.pid').write_text(str(process.pid))
        try:
            deadline = time.monotonic() + 15
            while True:
                result = subprocess.run([lua, 'package/myapp/flowdns/tests/rpc-runtime.lua',
                                         'package/myapp/flowdns/root/usr/libexec/flowdns', str(root), 'ready'],
                                        env=env, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    assert json.loads(result.stdout)['ok']
                    break
                assert process.poll() is None, (root / 'stderr.log').read_text()
                assert time.monotonic() < deadline, result.stdout + result.stderr
                time.sleep(.1)
            assert 'sing-box started' in (root / 'core.log').read_text()
            print('PASS: original DNS/TProxy inbounds start; real backend detects TCP/UDP listeners through actual /proc tables')
            (root / 'run/active.nft').write_text((pathlib.Path(work) / 'firewall.nft').read_text())
            def backend(action, check=True):
                result = subprocess.run([lua, 'package/myapp/flowdns/tests/rpc-runtime.lua',
                                         'package/myapp/flowdns/root/usr/libexec/flowdns', str(root), action, 'network-live'],
                                        env=env, capture_output=True, text=True, timeout=10)
                if check: assert result.returncode == 0, result.stdout + result.stderr
                return result
            try:
                (root / 'run/core.pid').write_text(str(os.getpid()))
                unrelated = backend('ready', check=False)
                assert unrelated.returncode == 1, unrelated.stdout
                (root / 'run/core.pid').write_text(str(process.pid))
                print('PASS: listeners owned by a different live PID are rejected as core readiness')
                backend('attach')
                print('PASS: router-specific Dump terminated on an absent table does not block backend attach')
                backend('ensure')
                backend('attach')
                assert (root / 'run/attached').exists()
                print('PASS: actual backend attaches IPv4/IPv6 policy routes and nft rules, ensures and reattaches idempotently')
            finally:
                backend('detach')
            for family in ('-4', '-6'):
                assert '20260:' not in subprocess.check_output(['ip', family, 'rule', 'show'], text=True)
            print('PASS: actual backend detaches both protocol families')
            # Exercise the real event/change detector without restarting core.
            (root / 'router-config').mkdir()
            nodefile = root / 'router-config/shadowsocksr'
            nodefile.write_text('node A')
            (root / 'run/active.json').write_text(json.dumps({'mode':'socks','provider':'ssrplus','proxy_port':1080}))
            backend('attach'); backend('ensure')
            (root / 'run/egress-recovery.json').unlink()
            oldstat = nodefile.stat()
            nodefile.write_text('node B')
            os.utime(nodefile, ns=(oldstat.st_atime_ns, oldstat.st_mtime_ns))
            backend('ensure')
            assert (root / 'run/egress-recovery.json').exists()
            assert not (root / 'run/reload-needed').exists()
            assert int((root / 'run/core.pid').read_text()) == process.pid
            status = json.loads(backend('status').stdout)
            assert status['egress_ready'] is False and status['running'] is True
            (root / 'run/egress-recovery.json').unlink()
            backend('proxy_changed'); backend('ensure')
            assert (root / 'run/egress-recovery.json').exists()
            backend('detach')
            print('PASS: same-size/same-mtime node edits and explicit events trigger recovery without restarting SOCKS core; listeners alone never imply overseas readiness')
            for family, destination in (('-4', '203.0.113.0/24'), ('-6', '2001:db8::/32')):
                subprocess.run(['ip', family, 'route', 'add', 'blackhole', destination, 'table', '20260'], check=True)
                before = subprocess.check_output(['ip', family, '-j', 'route', 'show', 'table', '20260'], text=True)
                (root / ('run/route-' + family[-1])).write_text('owned')  # stale marker from an interrupted session
                result = backend('attach', check=False)
                assert result.returncode == 1 and '20260' in result.stdout, result.stdout + result.stderr
                backend('detach')
                assert before == subprocess.check_output(['ip', family, '-j', 'route', 'show', 'table', '20260'], text=True)
                subprocess.run(['ip', family, 'route', 'del', 'blackhole', destination, 'table', '20260'], check=True)
            print('PASS: foreign routes survive rejected attach and cleanup even with stale ownership markers')
            subprocess.run(['ip', '-6', 'rule', 'add', 'pref', '20260', 'fwmark', '0x1', 'lookup', '220'], check=True)
            result = backend('attach', check=False)
            assert result.returncode == 1 and 'IPv6' in result.stdout, result.stdout + result.stderr
            backend('detach')
            assert '20260:' not in subprocess.check_output(['ip', '-4', 'rule', 'show'], text=True)
            assert 'fwmark 0x1 lookup 220' in subprocess.check_output(['ip', '-6', 'rule', 'show'], text=True)
            subprocess.run(['ip', '-6', 'rule', 'del', 'pref', '20260', 'fwmark', '0x1', 'lookup', '220'], check=True)
            print('PASS: IPv6 rule conflict preserves the foreign rule while cleaning up partially installed IPv4 state')
        finally:
            process.terminate()
            process.wait(timeout=5)
