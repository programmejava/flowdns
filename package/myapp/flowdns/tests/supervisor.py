#!/usr/bin/env python3
"""Actual shell supervisor with confined clock, dependencies and child fixtures."""
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

source = pathlib.Path('package/myapp/flowdns/root/usr/libexec/flowdns-run').read_text()
scenarios = ('slow', 'dependency', 'exit', 'timeout', 'attach-error', 'degraded', 'reload', 'bad-refresh',
             'proxy-recovery', 'crash', 'firewall-loss', 'bad-restart', 'log-rotate', 'dns-reload')
assert all(name in scenarios for name in sys.argv[1:])
for scenario in sys.argv[1:] or scenarios:
    with tempfile.TemporaryDirectory(prefix='flowdns-supervisor-') as temp:
        root = pathlib.Path(temp)
        (root / 'config.json').write_text('{}')
        (root / 'ticks').write_text('0')
        if scenario == 'log-rotate':
            (root / 'core.log').write_text('x' * 1100000)
        def executable(name, content):
            p = root / name; p.write_text('#!/usr/bin/env python3\n' + content); p.chmod(0o755)
        executable('sleep', '''import pathlib, time, os, sys
+p = pathlib.Path(os.environ['FIXTURE_ROOT']) / 'ticks'
+tmp = p.with_suffix('.new'); tmp.write_text(str(int(p.read_text()) + int(sys.argv[1]))); tmp.replace(p)
+time.sleep(.01)
+'''.replace('\n+', '\n'))
        executable('date', '''import pathlib, os, sys
r = pathlib.Path(os.environ['FIXTURE_ROOT'])
print(1792500000 + int((r / 'ticks').read_text()) if sys.argv[1] == '+%s' else 'fixture time')
''')
        executable('uci', "print('60')\n")
        executable('sing-box', '''import os, sys, time, pathlib
+r = pathlib.Path(os.environ['FIXTURE_ROOT'])
+p = r / 'starts'; value = str(int(p.read_text()) + 1) if p.exists() else '1'
+tmp = p.with_suffix('.new'); tmp.write_text(value); tmp.replace(p)
+if os.environ['FIXTURE_SCENARIO'] == 'exit':
+    print('FATAL fixture startup error', file=sys.stderr, flush=True); sys.exit(2)
+if os.environ['FIXTURE_SCENARIO'] == 'bad-restart' and p.read_text() == '2':
+    print('FATAL fixture updated core failed', file=sys.stderr, flush=True); sys.exit(43)
+if os.environ['FIXTURE_SCENARIO'] == 'crash' and p.read_text() == '1':
+    while not (r / 'healthy').exists(): time.sleep(.01)
+    print('FATAL fixture runtime crash', file=sys.stderr, flush=True); sys.exit(42)
+time.sleep(60)
+'''.replace('\n+', '\n'))
        executable('backend', '''import os, pathlib, sys
+r = pathlib.Path(os.environ['FIXTURE_ROOT'])
+s, a = os.environ['FIXTURE_SCENARIO'], sys.argv[1]
+with (r / 'calls').open('a') as f: f.write(a + '\\n')
+if a == 'boot':
+    p = r / 'boots'; count = int(p.read_text()) + 1 if p.exists() else 1; p.write_text(str(count))
+    if s == 'dependency' and count < 4:
+        (r / 'error').write_text('SOCKS/time/network fixture not ready'); sys.exit(1)
+if a == 'ready':
+    if s == 'bad-restart' and (r / 'config.json').read_text() != '{}': sys.exit(1)
+    sys.exit(0 if s != 'timeout' and int((r / 'ticks').read_text()) >= 25 else 1)
+if a == 'attach':
+    if s == 'attach-error': (r / 'error').write_text('fixture route conflict'); sys.exit(1)
+    (r / 'attached').touch()
+if a == 'ensure':
+    (r / 'healthy').touch()
+    if s == 'firewall-loss' and not (r / 'lost').exists():
+        (r / 'lost').touch(); (r / 'attached').unlink(missing_ok=True)
+        (r / 'error').write_text('fixture firewall was removed'); sys.exit(1)
+if a == 'health':
+    if s == 'degraded': (r / 'state').write_text('degraded')
+    if s == 'proxy-recovery':
+        p = r / 'healths'; n = int(p.read_text()) + 1 if p.exists() else 1; p.write_text(str(n))
+        (r / 'state').write_text('degraded' if n < 3 else 'ready')
+        if n >= 3: (r / 'recovered').touch()
+    if s in ('reload', 'bad-refresh', 'bad-restart', 'dns-reload') and not (r / 'requested').exists():
+        (r / 'reload-needed').touch(); (r / 'requested').touch()
+if a == 'refresh':
+    if s == 'dns-reload': (r / 'refresh-dns-only').touch()
+    if s == 'bad-refresh': (r / 'error').write_text('fixture invalid update'); sys.exit(1)
+    if s == 'bad-restart':
+        for name in ('config.json', 'active.json', 'active.nft'):
+            (r / ('previous-' + name)).write_text('{}')
+            (r / name).write_text('{"candidate":true}')
+    (r / 'refreshed').touch()
+if a == 'detach': (r / 'attached').unlink(missing_ok=True)
+'''.replace('\n+', '\n'))
        script = root / 'supervisor.sh'
        source = source.replace('/usr/libexec/flowdns-engine', 'sing-box run -c')
        script.write_text(source.replace('/var/run/flowdns', str(root)).replace('/usr/libexec/flowdns', str(root / 'backend')))
        env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], FIXTURE_ROOT=temp, FIXTURE_SCENARIO=scenario)
        process = subprocess.Popen(['sh', str(script)], env=env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, process.communicate()
                assert time.monotonic() < deadline, scenario
                state = (root / 'state').read_text().strip() if (root / 'state').exists() else ''
                error = (root / 'error').read_text() if (root / 'error').exists() else ''
                starts = int((root / 'starts').read_text()) if (root / 'starts').exists() else 0
                calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
                if scenario in ('slow', 'dependency') and (root / 'healthy').exists():
                    assert starts == 1 and (root / 'attached').exists()
                    if scenario == 'dependency': assert int((root / 'boots').read_text()) >= 4
                    print(f'PASS: {scenario} waits/retries until actual listener readiness and attaches')
                    break
                if scenario in ('exit', 'timeout', 'attach-error') and state == 'waiting' and error:
                    expected = {'exit': 'FATAL', 'timeout': '90', 'attach-error': 'route conflict'}[scenario]
                    record = (root / 'recovery.log').read_text()
                    assert expected in error + record, (error, record)
                    assert not (root / 'attached').exists()
                    print(f'PASS: {scenario} explains failure, detaches and remains alive for retry')
                    break
                if scenario == 'degraded' and state == 'degraded':
                    assert starts == 1 and (root / 'attached').exists()
                    print('PASS: failed proxy health preserves the live core and interception for domestic traffic')
                    break
                if scenario == 'reload' and starts >= 2 and state == 'ready':
                    assert (root / 'refreshed').exists()
                    print('PASS: valid DNS/rule reload is prepared before replacing the core')
                    break
                if scenario == 'dns-reload' and (root / 'refreshed').exists() and not (root / 'reload-needed').exists():
                    assert starts == 1 and (root / 'attached').exists()
                    print('PASS: successful DNS-only refresh keeps the outer core and interception running')
                    break
                if scenario == 'bad-refresh' and 'refresh\n' in calls:
                    assert starts == 1 and (root / 'attached').exists()
                    print('PASS: invalid refresh leaves the existing core and interception in place')
                    break
                if scenario == 'proxy-recovery' and (root / 'recovered').exists() and state == 'ready':
                    assert starts == 1 and (root / 'attached').exists()
                    print('PASS: proxy health recovers automatically without restarting the core or detaching domestic traffic')
                    break
                if scenario == 'crash' and starts >= 2 and state == 'ready':
                    record = (root / 'recovery.log').read_text()
                    assert '42' in record and 'FATAL fixture runtime crash' in record, record
                    assert (root / 'attached').exists()
                    assert not (root / 'error').read_text()
                    print('PASS: a runtime core crash restarts and reattaches; exit status and cause survive successful recovery')
                    break
                if scenario == 'firewall-loss' and starts >= 2 and state == 'ready':
                    assert (root / 'attached').exists()
                    assert 'firewall was removed' in (root / 'recovery.log').read_text()
                    print('PASS: failed interception repair triggers retry and restores attachment with a retained failure record')
                    break
                if scenario == 'bad-restart' and starts >= 3 and state == 'ready':
                    assert (root / 'config.json').read_text() == '{}', (starts, state, calls, (root / 'recovery.log').read_text(), (root / 'config.json').read_text())
                    assert (root / 'attached').exists()
                    assert '43' in (root / 'recovery.log').read_text()
                    print('PASS: a validated update that fails at runtime restores the previous config and reattaches')
                    break
                if scenario == 'log-rotate' and (root / 'core.log.previous').exists() and (root / 'core.log').stat().st_size == 0:
                    assert (root / 'core.log.previous').stat().st_size == 65536
                    assert (root / 'core.log').stat().st_size == 0
                    assert starts == 1 and (root / 'attached').exists()
                    print('PASS: log rotation bounds RAM usage while keeping the core and interception running')
                    break
                time.sleep(.01)
            child = int((root / 'core.pid').read_text()) if (root / 'core.pid').exists() else None
            process.send_signal(signal.SIGTERM)
            out, err = process.communicate(timeout=5)
            assert process.returncode == 0, (out, err)
            assert not (root / 'attached').exists()
            assert (root / 'state').read_text().strip() == 'stopped'
            if child:
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('core leaked after stopping supervisor')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL); process.wait()
