#!/usr/bin/env python3
"""Create a credential-free, versioned FlowDNS distribution from an OpenWrt tree."""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / 'package/myapp/flowdns'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path):
    with tarfile.open(path) as outer:
        item = next(m for m in outer if m.name.endswith('control.tar.gz'))
        with tarfile.open(fileobj=io.BytesIO(outer.extractfile(item).read())) as inner:
            item = next(m for m in inner if m.name.lstrip('./') == 'control')
            return dict(line.split(': ', 1) for line in inner.extractfile(item).read().decode().splitlines()
                        if ': ' in line and not line.startswith(' '))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', type=Path, required=True)
    parser.add_argument('--ui', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--core', type=Path, help='Optional private flowdns-core IPK')
    parser.add_argument('--core-source', type=Path, help='Matching upstream source with vendored Go dependencies')
    args = parser.parse_args()
    service, ui, output = args.service.resolve(), args.ui.resolve(), args.output.resolve()
    if bool(args.core) != bool(args.core_source):
        parser.error('--core and --core-source must be supplied together')
    core = args.core.resolve() if args.core else None
    folders = (PACKAGE, ROOT / 'package/myapp/luci-app-flowdns', ROOT / 'package/myapp/flowdns-core')
    package_args = [str(service), str(ui)] + ([str(core)] if core else [])
    for source in folders:
        if output == source or source in output.parents:
            parser.error('output must be outside package source directories')
    if output.exists() and any(output.iterdir()):
        parser.error('output must be an empty directory')
    subprocess.run(['python3', str(PACKAGE / 'tests/release.py'), *package_args], cwd=ROOT, check=True)
    meta = metadata(service)
    makefile = (PACKAGE / 'Makefile').read_text()
    version = re.search(r'^PKG_VERSION:=(.+)$', makefile, re.M).group(1)
    upstream_name = re.search(r'^PKG_SOURCE:=(.+)$', makefile, re.M).group(1)
    upstream_hash = re.search(r'^PKG_HASH:=(.+)$', makefile, re.M).group(1)
    upstream = ROOT / 'dl' / upstream_name
    if digest(upstream) != upstream_hash:
        raise SystemExit('upstream source hash mismatch')
    output.mkdir(parents=True, exist_ok=True)
    for source in (service, ui) + ((core,) if core else ()):
        shutil.copyfile(source, output / source.name)
    prefix = 'flowdns-' + version
    archive = output / (prefix + '-source.tar.gz')
    source_files = []
    for folder in folders:
        for path in sorted(folder.rglob('*')):
            rel = path.relative_to(ROOT)
            if any(part.startswith('.') or part == '__pycache__' for part in rel.parts):
                continue
            if path.is_symlink():
                raise SystemExit('unexpected source symlink: ' + str(rel))
            if path.is_file() and path.suffix not in ('.pyc', '.pyo'):
                source_files.append((str(rel), path.read_bytes(), 0o755 if path.stat().st_mode & 0o111 else 0o644))
    source_files += [('dl/' + upstream_name, upstream.read_bytes(), 0o644), ('README.md', b'''# FlowDNS source distribution

Copy package/myapp/flowdns, package/myapp/luci-app-flowdns, and optional
package/myapp/flowdns-core into a matching
OpenWrt/ImmortalWrt SDK. Copy dl/dnsmasq-2.93.tar.xz into its dl cache.
Start with package/myapp/flowdns/README.md, RELEASE.md and PORTING.md.
Original FlowDNS code: GPL-3.0-or-later (COPYING in each package).
Separate private dnsmasq component: upstream COPYING inside the source tarball.
Optional private engine: pinned upstream source and license are included;
when its IPK is shipped, upstream/ also contains a source archive with vendor/.
This is package source, not a complete OpenWrt toolchain or router backup.
''', 0o644)]
    core_recipe = folders[2] / 'Makefile'
    if core_recipe.exists():
        recipe = core_recipe.read_text()
        core_version = re.search(r'^PKG_VERSION:=(.+)$', recipe, re.M).group(1)
        core_hash = re.search(r'^PKG_HASH:=(.+)$', recipe, re.M).group(1)
        core_upstream = ROOT / 'dl' / ('sing-box-' + core_version + '.tar.gz')
        if digest(core_upstream) != core_hash:
            raise SystemExit('private engine source hash mismatch')
        source_files.append(('dl/' + core_upstream.name, core_upstream.read_bytes(), 0o644))
    if core:
        vendor_source = args.core_source.resolve()
        with tarfile.open(vendor_source) as tar:
            names = {m.name.lstrip('./') for m in tar}
            if not {'go.mod', 'go.sum', 'LICENSE', 'vendor/modules.txt'}.issubset(names):
                raise SystemExit('private engine source lacks module metadata/vendor/license')
        source_files.append(('upstream/' + vendor_source.name, vendor_source.read_bytes(), 0o644))
    with archive.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for name, data, mode in sorted(source_files):
                item = tarfile.TarInfo(prefix + '/' + name)
                item.size, item.mode, item.mtime = len(data), mode, 0
                item.uid = item.gid = 0
                tar.addfile(item, io.BytesIO(data))
    manifest = {
        'project': 'FlowDNS', 'version': meta['Version'], 'architecture': meta['Architecture'],
        'baseline': '1.0.0-r1', 'private_dns': {'version': '2.93', 'source': upstream_name, 'sha256': upstream_hash},
        'licenses': {'flowdns': 'GPL-3.0-or-later', 'private_dns': 'GPL-2.0'},
        'files': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()},
        'validation': 'See source package COMPATIBILITY.md and diagnostics/2026-10-23-rk3568-install.md; other targets require acceptance.',
    }
    if core:
        manifest['licenses']['private_core'] = 'GPL-3.0-or-later'
        manifest['private_core'] = {'package_version': metadata(core)['Version'], 'source': 'sing-box-' + core_version + '.tar.gz', 'source_sha256': core_hash, 'vendored_source_sha256': digest(args.core_source.resolve()), 'system_core_replaced': False}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    sums = ''.join(digest(p) + '  ' + p.name + '\n' for p in sorted(output.iterdir()) if p.is_file())
    (output / 'SHA256SUMS').write_text(sums)
    print('RELEASE_READY ' + str(output))


if __name__ == '__main__':
    main()
