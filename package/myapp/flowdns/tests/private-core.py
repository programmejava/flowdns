#!/usr/bin/env python3
"""Exercise production Lua and shell engine selection without touching system binaries."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

lua, modules = [str(Path(v).resolve()) for v in sys.argv[1:]]
with tempfile.TemporaryDirectory(prefix='flowdns-private-core-') as temp:
    root = Path(temp)
    global_bin, private_bin = root/'system', root/'private'
    global_bin.mkdir(); private_bin.mkdir()
    def binary(path, label):
        path.write_text('#!/bin/sh\nprintf "%s\\n" "'+label+'"\n')
        path.chmod(0o755)
    binary(global_bin/'sing-box', 'original-system-core')
    original = (global_bin/'sing-box').read_bytes()
    env = dict(os.environ, PATH=str(global_bin)+':/usr/bin:/bin',
               LUA_PATH=modules+'/?.lua;;', LUA_CPATH=modules+'/?.so;;')
    source = Path('package/myapp/flowdns/root/usr/libexec/flowdns').read_text()
    prefix = source.split('local uci =', 1)[0].replace('/usr/libexec/flowdns-bin', str(private_bin))
    driver = root/'selection.lua'
    driver.write_text(prefix+"\nlocal p=assert(io.popen('sing-box version'));print(p:read('*l'));p:close()\n")
    def selected():
        return subprocess.check_output([lua,str(driver)],env=env,text=True).strip()
    assert selected()=='original-system-core'
    binary(private_bin/'sing-box', 'private-compatible-core')
    assert selected()=='private-compatible-core'
    run = root/'run';run.mkdir();(run/'engine-mode').write_text('socks')
    shell = Path('package/myapp/flowdns/root/usr/libexec/flowdns-engine').read_text()
    shell = shell.replace('/usr/libexec/flowdns-bin',str(private_bin)).replace('/var/run/flowdns',str(run))
    launch = root/'engine.sh';launch.write_text(shell)
    assert subprocess.check_output(['sh',str(launch)],env=env,text=True).strip()=='private-compatible-core'
    (private_bin/'sing-box').unlink()
    assert selected()=='original-system-core'
    assert subprocess.check_output(['sh',str(launch)],env=env,text=True).strip()=='original-system-core'
    assert (global_bin/'sing-box').read_bytes()==original
print('PASS: production backend and engine prefer optional private core, fall back when absent, and preserve system binary')
