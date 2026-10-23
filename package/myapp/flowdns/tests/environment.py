#!/usr/bin/env python3
"""Version warnings must not block startup; actual config errors still must.

Uses the real backend/native Lua modules, confined dependency/service fixtures,
and the supplied real engine for version, rule compilation and config checks.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

lua, modules, engine = [str(pathlib.Path(x).resolve()) for x in sys.argv[1:]]
env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;')
backend = 'package/myapp/flowdns/root/usr/libexec/flowdns'

with tempfile.TemporaryDirectory(prefix='flowdns-environment-') as temp:
    root = pathlib.Path(temp)
    (root / 'run').mkdir()

    def options(**values):
        (root / 'options.json').write_text(json.dumps(values))
        (root / 'run/environment.json').unlink(missing_ok=True)

    def call(action, success=True, extra=None):
        args = [lua, 'package/myapp/flowdns/tests/rpc-runtime.lua', backend,
                temp, action, 'ssr-bootstrap']
        if extra is not None:
            args.append(extra)
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        return json.loads(result.stdout)

    for version in ('1.12.0', '1.12.22', '1.12.24', '1.12.25', '1.12.26', '1.13.0',
                    '1.12.25-dev', 'unknown'):
        banner = 'sing-box version ' + version
        options(version_output=banner + '\n')
        # This reproduces r1's stale rejection during a live package upgrade.
        (root / 'run/environment.json').write_text(json.dumps(
            dict(ok=False, time=2**32, message='obsolete version rejection')))
        result = call('environment')
        assert result['ok'] and result['schema'] == 2, result
        assert result['version_verified'] == (version == '1.12.25'), result
        if version != '1.12.25':
            assert result['warnings'] and banner in result['message'], result
        assert call('apply')['ok']
    print('PASS: older/newer/dev/unknown versions only warn; old rejection cache cannot block apply')

    options(real_engine=engine)
    detected = subprocess.check_output([engine, 'version'], text=True).splitlines()[0]
    assert call('environment')['versions']['sing_box'] == detected
    for name in ('domains', 'ip'):
        (root / ('data/rules/current/' + name + '.srs')).unlink()
    assert call('apply')['ok']
    assert (root / 'run/engine-check.json').exists()
    assert (root / 'data/rules/current/domains.srs').read_bytes() != b'fixture-srs'
    print('PASS: real engine version, rule compilation and generated configuration pass through apply: ' + detected)

    options(supervised=True)
    assert call('explain', extra='www.qq.com')['scope'] == '已保存但未运行的配置'
    print('PASS: a live supervisor without a ready core cannot make stale policy appear active')

    options(autostart=True)
    assert call('status')['autostart'] is True
    (root / 'run/recovery.log').write_text('fixture: previous crash recovered\n')
    assert 'previous crash recovered' in call('status')['recent_errors']
    options(autostart=False)
    assert call('status')['autostart'] is False
    print('PASS: backend reports actual startup registration and retains recovery evidence in recent errors')

    options(version_output='sing-box version unknown\n', fail_check=True)
    active = (root / 'run/active.json').read_bytes()
    reply = call('apply', False)
    assert 'sing-box 配置检查失败' in reply['message'], reply
    assert 'incompatible configuration' in reply['message'], reply
    assert (root / 'run/active.json').read_bytes() == active
    print('PASS: actual configuration validation remains blocking for an unverified version')

    for tool in ('sing-box version', 'curl --version'):
        options(missing_tool=tool)
        reply = call('environment')
        assert not reply['ok'] and '不可用' in reply['message'], reply
        assert '不可用' in call('apply', False)['message']
    print('PASS: missing mandatory dependencies still block preparation')
