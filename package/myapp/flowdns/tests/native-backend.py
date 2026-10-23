#!/usr/bin/env python3
"""Actual prepare/apply using real SSR generator, Xray and DNS config checks."""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

lua, modules, engine, xray = [str(pathlib.Path(x).resolve()) for x in sys.argv[1:]]
env = dict(os.environ, LUA_PATH=modules + '/?.lua;;', LUA_CPATH=modules + '/?.so;;', FLOWDNS_TEST_LUA=lua)
with tempfile.TemporaryDirectory(prefix='flowdns-native-backend-') as temp:
    root = pathlib.Path(temp)
    def options(**kw):
        data = dict(mode='transparent', real_engine=engine, real_xray=xray)
        data.update(kw)
        (root / 'options.json').write_text(json.dumps(data))
    def call(action, good=True):
        r = subprocess.run([lua, 'package/myapp/flowdns/tests/rpc-runtime.lua',
                            'package/myapp/flowdns/root/usr/libexec/flowdns', temp, action, 'ssr-bootstrap'],
                           env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == (0 if good else 1), r.stdout + r.stderr
        return json.loads(r.stdout)
    options()
    assert call('apply')['ok']
    active = (root / 'run/active.json').read_bytes()
    config = json.loads((root / 'run/xray.json').read_text())
    assert config['outbounds'][0]['protocol'] == 'vless'
    assert config['inbounds'][0]['streamSettings']['sockopt']['tproxy'] == 'tproxy'
    assert 'dns' not in config and len(config['routing']['rules']) == 1
    assert (root / 'run/engine-mode').read_text() == 'transparent'
    print('PASS: actual backend generates SSR node config, validates Xray/DNS/nft candidate and activates the complete transparent bundle')
    keys = subprocess.check_output([xray, 'x25519'], text=True)
    public = re.search(r'(?:Public key|Password):\s*(\S+)', keys).group(1)
    node = dict(type='v2ray', v2ray_protocol='vless', server='127.0.0.1', server_port='33445',
                vmess_id='79bec4b7-45fb-4db7-8584-161d337dc2db', transport='raw', reality='1',
                reality_publickey=public, reality_shortid='aabb', tls_host='example.com',
                fingerprint='chrome', tls_flow='xtls-rprx-vision')
    options(node=node)
    assert call('apply')['ok']
    generated = json.loads((root / 'run/xray.json').read_text())['outbounds'][0]
    assert generated['streamSettings']['realitySettings']['publicKey'] == public
    assert generated['settings']['vnext'][0]['users'][0]['flow'] == 'xtls-rprx-vision'
    active = (root / 'run/active.json').read_bytes()
    print('PASS: real SSR generator and Xray validation preserve VLESS Reality, fingerprint and Vision flow')
    for variant in ('no-tag', 'empty-tag', 'direct-first-no-tag'):
        options(node=node, generator_variant=variant)
        assert call('apply')['ok']
        adapted = json.loads((root / 'run/xray.json').read_text())
        proxy = next(v for v in adapted['outbounds'] if v['protocol'] == 'vless')
        assert proxy['tag'] == adapted['routing']['rules'][0]['outboundTag']
        assert proxy['streamSettings']['realitySettings']['publicKey'] == public
        assert proxy['settings']['vnext'][0]['users'][0]['flow'] == 'xtls-rprx-vision'
    active = (root / 'run/active.json').read_bytes()
    print('PASS: tagless, empty-tag and direct-first SSR variants pass actual Xray validation with Reality/Vision preserved')
    for values, message in ((dict(no_nftset=True), '私有 DNS 前端'), (dict(fail_xray=True), 'Xray 配置检查失败'),
                            (dict(node=dict(type='trojan')), 'Xray 节点')):
        options(**values)
        assert message in call('apply', False)['message']
        assert (root / 'run/active.json').read_bytes() == active
    print('PASS: unsupported node, missing nftset and invalid Xray config never replace the active bundle')
    options(mode='socks')
    assert call('apply')['ok']
    assert (root / 'run/engine-mode').read_text() == 'socks'
    assert (root / 'run/xray.json').read_text() == ''
    assert (root / 'run/previous-engine-mode').read_text() == 'transparent'
    print('PASS: switching back to SOCKS clears native files and preserves a complete previous-mode snapshot')
