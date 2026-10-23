#!/usr/bin/env python3
"""Inspect final target IPKs and execute tests against their minified UI."""
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile


def contents(path):
    with tarfile.open(path) as outer:
        data = next(m for m in outer if m.name.endswith('data.tar.gz'))
        with tarfile.open(fileobj=io.BytesIO(outer.extractfile(data).read())) as inner:
            return {m.name.lstrip('./'): (m, inner.extractfile(m).read()) for m in inner if m.isfile()}


def control(path):
    with tarfile.open(path) as outer:
        member = next(m for m in outer if m.name.endswith('control.tar.gz'))
        with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read())) as inner:
            entry = next(m for m in inner if m.name.lstrip('./') == 'control')
            return dict(line.split(': ', 1) for line in inner.extractfile(entry).read().decode().splitlines() if ': ' in line and not line.startswith(' '))


service, ui, *private_core = [pathlib.Path(x) for x in sys.argv[1:]]
assert len(private_core) <= 1
service_meta, ui_meta = control(service), control(ui)
assert service_meta['Package'] == 'flowdns' and ui_meta['Package'] == 'luci-app-flowdns'
assert service_meta['Version'] == ui_meta['Version'], 'service/UI versions differ'
assert ui_meta['Architecture'] == 'all'
for name in ('flowdns', 'luci-app-flowdns'):
    import re
    makefile = pathlib.Path('package/myapp', name, 'Makefile').read_text()
    version = re.search(r'^PKG_VERSION:=(.+)$', makefile, re.M).group(1)
    release = re.search(r'^PKG_RELEASE:=(.+)$', makefile, re.M).group(1)
    assert service_meta['Version'] == version + '-r' + release, 'package/source version mismatch'
print('PASS: service/UI package versions match source metadata')
files = contents(service)
for source in pathlib.Path('package/myapp/flowdns/root').rglob('*'):
    if source.is_file():
        dest = str(source.relative_to('package/myapp/flowdns/root'))
        assert files[dest][1] == source.read_bytes(), dest
for source in pathlib.Path('package/myapp/flowdns/src').glob('*.lua'):
    assert files['usr/lib/lua/flowdns/' + source.name][1] == source.read_bytes()
for name in ('usr/libexec/flowdns', 'usr/libexec/flowdns-run', 'usr/libexec/flowdns-engine', 'etc/init.d/flowdns'):
    assert files[name][0].mode & 0o111, name
print('PASS: target service package matches tested source/compiler/modules and executable permissions')
frontend = files['usr/libexec/flowdns-dns']
assert frontend[0].mode & 0o111
payload = frontend[1]
assert payload[:4] == b'\x7fELF' and payload[5] in (1, 2)
machine = int.from_bytes(payload[18:20], 'little' if payload[5] == 1 else 'big')
arch = service_meta['Architecture']
expected = next((value for prefix, value in (
    ('aarch64', (183, 2)), ('x86_64', (62, 2)), ('i386', (3, 1)), ('i686', (3, 1)),
    ('arm', (40, 1)), ('mips64', (8, None)), ('mips', (8, 1)),
    ('riscv64', (243, 2)), ('powerpc64', (21, 2)), ('powerpc', (20, 1)))
    if arch.startswith(prefix)), None)
assert expected is not None, 'add explicit ELF architecture check for ' + arch
encoding = (1 if 'el' in arch else 2) if arch.startswith('mips') else ((1 if 'le' in arch else 2) if arch.startswith('powerpc') else 1)
assert payload[5] == encoding, (arch, 'unexpected ELF byte order', payload[5])
assert machine == expected[0] and (expected[1] is None or payload[4] == expected[1]), (arch, machine, payload[4])
assert 'usr/share/flowdns/COPYING.dnsmasq' in files
assert files['usr/share/flowdns/COPYING.flowdns'][1] == pathlib.Path('package/myapp/flowdns/COPYING').read_bytes()
assert not any(name.startswith('usr/sbin/dnsmasq') or name.startswith('etc/config/dhcp') for name in files)
print('PASS: private DNS ELF matches ' + arch + '; both licenses present; system DNS/DHCP untouched')
files = contents(ui)
menu_name = 'usr/share/luci/menu.d/luci-app-flowdns.json'
assert json.loads(files[menu_name][1]) == json.loads(pathlib.Path('package/myapp/luci-app-flowdns/root/usr/share/luci/menu.d/luci-app-flowdns.json').read_text())
with tempfile.TemporaryDirectory(prefix='flowdns-release-ui-') as temp:
    root = pathlib.Path(temp)
    for name, (_, payload) in files.items():
        if name.endswith('.js'):
            p = root / name.removeprefix('www/luci-static/resources/')
            p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(payload)
            subprocess.run(['node', '--check', str(p)], check=True)
    assert not (root / 'flowdns.js').exists()
    assert not (root / 'flowdns/ui_v6.js').exists()
    assert not (root / 'flowdns/ui_v02.js').exists()
    assert not (root / 'view/flowdns/v02').exists()
    assert not (root / 'view/flowdns/v03').exists()
    assert not (root / 'flowdns/ui_v04.js').exists()
    assert not (root / 'view/flowdns/v04').exists()
    assert not (root / 'flowdns/ui_v031.js').exists()
    assert not (root / 'view/flowdns/v031').exists()
    subprocess.run(['node', 'package/myapp/flowdns/tests/frontend.js', str(root)], check=True)
print('PASS: UI package menu, fresh resource versions and minified interactions are consistent')

if private_core:
    meta = control(private_core[0])
    assert meta['Package'] == 'flowdns-core' and meta['Architecture'] == arch
    core_files = contents(private_core[0])
    assert set(core_files) == {'usr/libexec/flowdns-bin/sing-box', 'usr/share/flowdns-core/LICENSE.sing-box', 'usr/share/flowdns-core/COPYING'}
    entry, core_bin = core_files['usr/libexec/flowdns-bin/sing-box']
    assert entry.mode & 0o111 and core_bin[:4] == b'\x7fELF'
    assert core_bin[4:6] == frontend[1][4:6] and core_bin[18:20] == frontend[1][18:20]
    assert core_files['usr/share/flowdns-core/COPYING'][1] == pathlib.Path('package/myapp/flowdns-core/COPYING').read_bytes()
    assert 'kmod-nft-socket' not in service_meta.get('Depends', '')
    print('PASS: optional private engine architecture/license match; package contains no system binary/config/init replacement')
