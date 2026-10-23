#!/usr/bin/env python3
"""Call the real RPC dispatcher with real Lua nixio/jsonc modules.

Usage: rpc-runtime.py path/to/lua path/to/host/lua-module-directory
Compile the modules from this checkout's luci-lib-nixio/luci-lib-jsonc sources.
Only temporary fixture files and a local background shell worker are used.
"""
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import time

lua = str(pathlib.Path(sys.argv[1]).resolve())
modules = str(pathlib.Path(sys.argv[2]).resolve())
env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;', FLOWDNS_TEST_LUA=lua)
plugin = 'package/myapp/luci-app-flowdns/root/usr/libexec/rpcd/luci.flowdns'
backend = 'package/myapp/flowdns/root/usr/libexec/flowdns'
driver = 'package/myapp/flowdns/tests/rpc-runtime.lua'


def call(root, method, args=None, scenario='normal', script=plugin, allow_error=False):
    result = subprocess.run([lua, driver, script, str(root), method, scenario],
                            input=json.dumps(args if args is not None else {}),
                            env=env, text=True, capture_output=True, timeout=5)
    assert result.returncode == 0 or (allow_error and result.returncode == 1), result.stderr + result.stdout
    reply = json.loads(result.stdout)
    assert isinstance(reply, dict), reply
    return reply


with tempfile.TemporaryDirectory(prefix='flowdns-rpc-runtime-') as temp:
    root = pathlib.Path(temp)
    assert call(root, 'status', scenario='mode-repro')['ok']
    print('PASS: real nixio rejects 448, accepts 700 and sets rwx------')
    reply = call(root, 'status', script=backend)
    assert reply['enabled'] is False and reply['attached'] is False
    print('PASS: real backend initialization/status returns valid JSON')
    assert call(root, 'status')['enabled'] is False
    print('PASS: RPC status invokes the backend and returns an object')
    (root / 'run/state').write_text('starting\n')
    starting = call(root, 'status', script=backend, scenario='supervised')
    assert starting['supervised'] is True and starting['starting'] is True
    assert starting['running'] is False and starting['dns_ready'] is False and not starting.get('active')
    (root / 'run/state').write_text('failed\n')
    failed = call(root, 'status', script=backend, scenario='supervised')
    assert failed['starting'] is False and failed['running'] is False and failed['state'] == 'failed'
    print('PASS: a live procd supervisor alone is never reported as a ready core or effective configuration')
    blocked = call(root, 'status', scenario='ssr-unconfigured', script=backend)
    assert len(blocked['setup']) == 3 and all(not step['ready'] for step in blocked['setup'])
    assert blocked['dns_ready'] is False and blocked['running'] is False
    assert call(root, 'apply', scenario='ssr-unconfigured', script=backend, allow_error=True)['ok'] is False
    print('PASS: screenshot configuration reports all three missing prerequisites and never mistakes an unrelated listener for FlowDNS')
    rules = root / 'data/rules/current'
    rules.mkdir(parents=True)
    (rules / 'policy.json').write_text(json.dumps({'version': 'fixture', 'domains': ['qq.com']}))
    (rules / 'manifest.json').write_text(json.dumps({'version': 'fixture', 'domain_count': 100}))
    configured = call(root, 'status', scenario='ssr-ready', script=backend)
    assert all(step['ready'] for step in configured['setup'])
    print('PASS: correctly configured SSR SOCKS mode and initialized rules clear the setup checklist')
    for table in ('table inet ss_spec { chain ss_spec_wan_fw { tcp dport 443 redirect to :1234; } }',
                  'table ip ss_spec_mangle { chain prerouting { type filter hook prerouting priority -150; } }',
                  'table inet SSR_SPEC { }', 'table inet PSW2 { }'):
        (root / 'options.json').write_text(json.dumps({'firewall': table}))
        blocked = call(root, 'apply', scenario='ssr-bootstrap', script=backend, allow_error=True)
        assert blocked['ok'] is False and '防火墙仍有' in blocked['message'], blocked
        if 'ss_spec' in table:
            assert '遗留' in blocked['message'] and '不会自动删除' in blocked['message'], blocked
        assert not (root / 'run/candidate.json').exists(), 'must block before starting or preparing a replacement'
    (root / 'options.json').unlink()
    print('PASS: native SSR ss_spec and ss_spec_mangle leftovers block apply before replacing the live service; legacy uppercase markers still work')
    bootstrap = root / 'bootstrap'
    bootstrap.mkdir()
    (bootstrap / 'options.json').write_text(json.dumps({'firewall': 'table inet fw4 { }\ntable inet flowdns { }'}))
    reply = call(bootstrap, 'apply', scenario='ssr-bootstrap', script=backend)
    assert reply['ok'] is True, reply
    manifest = json.loads((bootstrap / 'data/rules/current/manifest.json').read_text())
    assert manifest['domain_count'] == 100 and manifest['ipv4_count'] == 100 and manifest['ipv6_count'] == 10
    assert (bootstrap / 'run/candidate.json').exists() and (bootstrap / 'run/attached').exists()
    print('PASS: first apply initializes all datasets and waits through 25 seconds of fixture startup before reporting success')
    reply = call(root, 'explain', {'domain': 'www.example.cn'})
    assert reply['action'] == 'direct', reply
    print('PASS: RPC explain parses input and invokes the policy backend')
    assert call(root, 'action', {'name': 'not-allowed'})['ok'] is False
    assert call(root, 'action', {'name': {}})['ok'] is False
    print('PASS: malformed and unknown action names produce readable JSON errors')
    for scenario in ('chmod-error', 'write-error', 'spawn-error'):
        reply = call(root, 'action', {'name': 'diagnose'}, scenario=scenario)
        assert reply['ok'] is False and reply['message'], reply
        assert not (root / 'run/job.lock').exists(), scenario
        if scenario == 'spawn-error':
            assert json.loads((root / 'run/job.json').read_text())['state'] == 'error'
    print('PASS: permission/write/launch failures return JSON and release the job lock')
    reply = call(root, 'status', scenario='backend-error')
    assert reply['ok'] is False and 'backend test failure' in reply['message']
    print('PASS: backend stderr is surfaced as a readable diagnostic')
    reply = call(root, 'action', {'name': 'sample'})
    assert reply['ok'] is True, reply
    assert isinstance(reply['id'], str) and reply['id']
    assert call(root, 'action', {'name': 'sample'})['ok'] is False
    time.sleep(.8)
    job = json.loads((root / 'run/job.json').read_text())
    assert job['state'] == 'done' and job['action'] == 'sample' and job['id'] == reply['id'], job
    assert (root / 'run/metrics.json').exists()
    print('PASS: real queued worker acquires the kernel lock, samples metrics, and reports matching completion')
    holder_code = "local n=require 'nixio'; local s=dofile('package/myapp/flowdns/src/system.lua'); local f=assert(n.open(arg[1], 'w', 600)); assert(f:lock('tlock')); s.write(arg[2],{pid=n.getpid(),ticks=s.ticks(n.getpid()),action='diagnose',started_uptime=tonumber(s.read('/proc/uptime'):match('^[%d.]+'))}); print('locked'); io.stdout:flush(); n.nanosleep(30)"
    holder_script = root / 'hold.lua'
    holder_script.write_text(holder_code)
    holder = subprocess.Popen([lua, str(holder_script), str(root / 'run/work.lock'), str(root / 'run/operation.json')], env=env, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'locked'
        blocked = call(root, 'action', {'name': 'sample'})
        assert blocked['ok'] is False and '完整诊断' in blocked['message']
        (root / 'run/error').write_text('original DNS frontend failure')
        busy_boot = call(root, 'boot', script=backend, allow_error=True)
        assert busy_boot['busy'] is True and '完整诊断' in busy_boot['message']
        assert (root / 'run/error').read_text() == 'original DNS frontend failure'
        assert call(root, 'status', script=backend)['operation']['pid'] == holder.pid
        print('PASS: another process holding the kernel lock prevents a concurrent operation')
        print('PASS: lock contention identifies the live operation and never overwrites the original startup failure')
    finally:
        holder.kill(); holder.wait()
    dead_job = {'id': 'dead', 'state': 'running', 'pid': holder.pid, 'ticks': 1, 'started': time.time() - 10000}
    (root / 'run/job.json').write_text(json.dumps(dead_job))
    reply = call(root, 'status', script=backend)
    assert reply['job']['state'] == 'error'
    reply = call(root, 'action', {'name': 'sample'})
    assert reply['ok'] is True
    time.sleep(.8)
    assert json.loads((root / 'run/job.json').read_text())['state'] == 'done'
    print('PASS: process death releases the kernel lock and stale job is explained; a new task can run')
