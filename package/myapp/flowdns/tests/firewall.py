#!/usr/bin/env python3
"""Validate install/replace/removal only inside a new network namespace.

unshare --user --map-root-user --net python3 tests/firewall.py generated.nft
"""
import json
import os
import pathlib
import subprocess
import sys


def run(*args, capture=False):
    return subprocess.run(args, check=True, text=True, capture_output=capture)


parent_namespace = os.environ.get('FLOWDNS_TEST_PARENT_NETNS')
assert parent_namespace and os.readlink('/proc/self/ns/net') != parent_namespace, 'Refusing to modify the parent network namespace'
links = json.loads(run('ip', '-j', 'link', 'show', capture=True).stdout)
assert [link['ifname'] for link in links] == ['lo'], 'Expected an empty, isolated network namespace'
run('ip', 'link', 'set', 'lo', 'up')
path = pathlib.Path(sys.argv[1]).resolve()
run('nft', '-c', '-f', str(path))
run('nft', '-f', str(path))
print('PASS: generated nftables rules install in the isolated namespace')
for family in ('-4', '-6'):
    run('ip', family, 'route', 'add', 'local', 'default', 'dev', 'lo', 'table', '20260')
    run('ip', family, 'rule', 'add', 'pref', '20260', 'fwmark', '0x40000000/0x40000000', 'lookup', '20260')
    text = run('ip', family, 'rule', 'show', capture=True).stdout
    assert 'fwmark 0x40000000/0x40000000 lookup 20260' in text
print('PASS: IPv4 and IPv6 marked policy routes install')
replacement = path.parent / 'firewall-replace.nft'
replacement.write_text('delete table inet flowdns\n' + path.read_text())
run('nft', '-c', '-f', str(replacement))
run('nft', '-f', str(replacement))
data = json.loads(run('nft', '-j', 'list', 'table', 'inet', 'flowdns', capture=True).stdout)
assert len([item for item in data['nftables'] if 'table' in item]) == 1
print('PASS: atomic replacement does not duplicate the rules table')
run('nft', 'delete', 'table', 'inet', 'flowdns')
for family in ('-4', '-6'):
    run('ip', family, 'rule', 'del', 'pref', '20260', 'fwmark', '0x40000000/0x40000000', 'lookup', '20260')
    run('ip', family, 'route', 'del', 'local', 'default', 'dev', 'lo', 'table', '20260')
    assert '20260:' not in run('ip', family, 'rule', 'show', capture=True).stdout
print('PASS: rule table and policy routes cleanly detach')
