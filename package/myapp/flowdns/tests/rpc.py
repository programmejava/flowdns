#!/usr/bin/env python3
"""Check the actual executable signature against rpcd's method requirements.

Usage: rpc.py path/to/lua path/to/usr/libexec/rpcd/luci.flowdns
"""
import json
import pathlib
import subprocess
import sys

lua, plugin = sys.argv[1:]
result = subprocess.run([lua, plugin, 'list'], check=True, text=True, capture_output=True)
methods = json.loads(result.stdout)
assert isinstance(methods, dict)
assert set(methods) == {'status', 'explain', 'action'}
for name, signature in methods.items():
    assert isinstance(signature, dict), f'rpcd skips {name}: signature must be an object, not an array'
assert methods['status'] == {}
assert methods['explain'] == {'domain': ''}
assert methods['action'] == {'name': ''}
assert pathlib.Path(plugin).stat().st_mode & 0o111
print('PASS: status, explain and action all expose valid rpcd method signatures')
