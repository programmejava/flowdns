#!/usr/bin/env python3
"""Health failover and resource/queue features through the actual Lua backend.
Only upstream responses are fixtures; state files, libraries and locks are real.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

lua, modules = [str(pathlib.Path(p).resolve()) for p in sys.argv[1:]]
env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;', FLOWDNS_TEST_LUA=lua)
backend = 'package/myapp/flowdns/root/usr/libexec/flowdns'
with tempfile.TemporaryDirectory(prefix='flowdns-features-') as temp:
    root = pathlib.Path(temp)
    (root / 'run').mkdir()
    (root / 'run/attached').touch()
    (root / 'run/state').write_text('ready')
    config = dict(provider='manual', proxy_port=1080, domestic_dns='alidns', overseas_dns='google', transport='https',
                  dns_failover=True, udp=True, local_dns_port=53, local_domains=['lan'], direct_domains=[],
                  proxy_domains=[], realip_domains=[], log_level='info')
    def save_config():
        (root / 'run/active.json').write_text(json.dumps(config))
    def fixture(**values):
        (root / 'upstreams.json').write_text(json.dumps(values))
    def call(action):
        result = subprocess.run([lua, 'package/myapp/flowdns/tests/rpc-runtime.lua', backend, temp, action, 'health-fixture'],
                                capture_output=True, text=True, env=env, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    save_config()
    fixture(alidns=False)
    assert call('health')['reload'] is False
    assert call('health')['reload'] is True
    selection = json.loads((root / 'run/dns-selection.json').read_text())
    assert selection['domestic']['active'] == 'dnspod' and selection['overseas']['active'] == 'google'
    assert (root / 'run/reload-needed').exists()
    print('PASS: two verified primary failures select a healthy encrypted backup in the same group')
    config['domestic_active'] = 'dnspod'; save_config()
    (root / 'run/egress-recovery.json').unlink(missing_ok=True)
    (root / 'run/state').write_text('ready')
    selection['domestic']['switched'] = int(time.time()) - 301
    (root / 'run/dns-selection.json').write_text(json.dumps(selection))
    fixture()
    assert call('health')['reload'] is False
    assert call('health')['reload'] is False
    assert call('health')['reload'] is True
    assert json.loads((root / 'run/dns-selection.json').read_text())['domestic']['active'] == 'alidns'
    print('PASS: failback requires three successful primary probes and at least five minutes')
    config.pop('domestic_active'); save_config()
    (root / 'run/dns-selection.json').unlink()
    fixture(proxy=False)
    reply = call('health')
    assert reply['proxy'] is False and reply['groups']['domestic']['ok'] is True
    assert reply['reload'] is False and reply['groups']['overseas']['active'] == 'google'
    assert (root / 'run/state').read_text() == 'recovering'
    print('PASS: failed SOCKS keeps domestic service and never redirects foreign DNS to a direct resolver')
    fixture()
    assert call('health')['ok'] is True
    assert (root / 'run/state').read_text() == 'ready'
    print('PASS: restored SOCKS/upstreams automatically return health to ready without detaching domestic service')
    (root / 'run/dns-selection.json').unlink()
    fixture(alidns=False, dnspod=False, google=False, cloudflare=False)
    call('health'); reply = call('health')
    assert reply['reload'] is False
    print('PASS: no healthy encrypted backup means no unsafe fallback or restart loop')
    config['dns_failover'] = False; save_config()
    (root / 'run/dns-selection.json').unlink()
    fixture(alidns=False)
    call('health'); assert call('health')['reload'] is False
    print('PASS: failover can be disabled')
    config['dns_failover'] = True; save_config()
    (root / 'run/dns-selection.json').unlink()
    (root / 'run/egress-recovery.json').write_text('{}')
    fixture(alidns=False)
    assert call('health')['reload'] is True
    assert json.loads((root / 'run/dns-selection.json').read_text())['domestic']['active'] == 'dnspod'
    print('PASS: recovery selects a verified encrypted backup on the first failed active probe')
    config['provider'] = 'ssrplus'; save_config()
    (root / 'router-config').mkdir()
    (root / 'router-config/shadowsocksr').write_text('initial generation')
    before = (root / 'run/health.json').read_bytes()
    fixture(mutate_revision=True)
    assert call('health')['stale'] is True
    assert (root / 'run/health.json').read_bytes() == before
    print('PASS: a probe completed for an obsolete node generation cannot publish readiness for its replacement')
