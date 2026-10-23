#!/usr/bin/env python3
"""Actual updater/scheduler with confined downloads and compiler/service peers."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

lua, modules = [str(pathlib.Path(x).resolve()) for x in sys.argv[1:]]
env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;', FLOWDNS_TEST_LUA=lua)
with tempfile.TemporaryDirectory(prefix='flowdns-updates-') as temp:
    root = pathlib.Path(temp)
    def options(**data):
        (root / 'options.json').write_text(json.dumps(data))
    def call(action, success=True):
        result = subprocess.run([lua, 'package/myapp/flowdns/tests/rpc-runtime.lua',
                                 'package/myapp/flowdns/root/usr/libexec/flowdns', temp, action, 'ssr-bootstrap'],
                                env=env, capture_output=True, text=True, timeout=5)
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        return json.loads(result.stdout)
    options(auto_update='1')
    reply = call('scheduled')
    assert reply['ok'] and (root / 'run/reload-needed').exists()
    current = root / 'data/rules/current'
    assert (current / 'domains.srs').read_text() == 'fixture-srs'
    before = json.loads((current / 'manifest.json').read_text())
    assert before['updated'] and before['sources'] and before['changes']['domain_count']['delta'] == 100
    assert call('scheduled')['skipped']
    print('PASS: due automatic update creates persistent SRS, records sources/diff, requests apply and respects interval')
    options(download_count=210)
    call('update')
    newer = json.loads((current / 'manifest.json').read_text())
    assert newer['changes']['domain_count']['delta'] == 110
    options(download_count=100)
    reply = call('update', False)
    assert '30%' in reply['message']
    assert json.loads((current / 'manifest.json').read_text())['version'] == newer['version']
    print('PASS: a dataset decreasing by over 30 percent is rejected before switching the published version')
    options(fail_download=True)
    call('update', False)
    assert json.loads((current / 'manifest.json').read_text())['version'] == newer['version']
    print('PASS: download failure keeps the last published rule version')
    options()
    call('rollback')
    assert json.loads((current / 'manifest.json').read_text())['version'] == before['version']
    print('PASS: rollback restores an earlier complete rule/SRS version')
    options(auto_update='0', fail_download=True)
    assert call('scheduled')['skipped']
    print('PASS: disabled scheduler does not download or change rules')
