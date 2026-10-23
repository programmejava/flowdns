#!/usr/bin/env python3
"""Exercise the repository's actual rc.common registration and FlowDNS init.

All files are under a temporary IPKG_INSTROOT. procd/UCI are adapters; this
checks registration and the submitted service contract, not a real procd boot.
"""
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile

source = pathlib.Path('package/myapp/flowdns/root')
rc = pathlib.Path('package/base-files/files/etc/rc.common').resolve()
with tempfile.TemporaryDirectory(prefix='flowdns-init-') as temp:
    root = pathlib.Path(temp)
    for directory in ('etc/init.d', 'etc/rc.d', 'lib/functions', 'bin', 'var/run/flowdns'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy('package/base-files/files/lib/functions.sh', root / 'lib/functions.sh')
    shutil.copy('package/base-files/files/lib/functions/service.sh', root / 'lib/functions/service.sh')
    events = root / 'events'
    (root / 'lib/functions/procd.sh').write_text('''
fixture_event() { printf '%s\\n' "$*" >>"$IPKG_INSTROOT/events"; }
procd_open_service() { fixture_event open_service "$@"; }
procd_close_service() { fixture_event close_service "$@"; }
procd_open_instance() { fixture_event open_instance "$@"; }
procd_close_instance() { fixture_event close_instance "$@"; }
procd_set_param() { fixture_event param "$@"; }
procd_add_reload_trigger() { fixture_event reload_trigger "$@"; }
procd_add_interface_trigger() { fixture_event interface_trigger "$@"; }
procd_lock() { fixture_event procd_lock; }
''')
    # Confine runtime paths; leave every init function and command intact.
    init = root / 'etc/init.d/flowdns'
    backend = root / 'bin/backend'
    backend.write_text('#!/bin/sh\nprintf "backend %s\\n" "$*" >>"$IPKG_INSTROOT/events"\n[ "$FIXTURE_BUSY" != 1 ]\n')
    backend.chmod(0o755)
    init_source = pathlib.Path(os.environ.get('FLOWDNS_TEST_INIT_SOURCE', source / 'etc/init.d/flowdns'))
    init.write_text(init_source.read_text().replace('/var/run/flowdns', str(root / 'var/run/flowdns')).replace('/usr/libexec/flowdns queue', str(backend) + ' queue'))
    uci = root / 'bin/uci'
    uci.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_ENABLED"\n')
    uci.chmod(0o755)
    env = dict(os.environ, IPKG_INSTROOT=temp, FIXTURE_ENABLED='1', PATH=str(root / 'bin') + ':' + os.environ['PATH'])

    def call(action, good=True, **extra):
        command = ['bash', str(rc), str(init), action]
        if action == 'service_triggers':
            command = ['bash', '-c', '. "$IPKG_INSTROOT/lib/functions.sh"; . "$IPKG_INSTROOT/lib/functions/procd.sh"; . "$1"; service_triggers', 'fixture', str(init)]
        result = subprocess.run(command,
                                env=dict(env, **extra), capture_output=True, text=True, timeout=5)
        assert result.returncode == (0 if good else 1), result.stdout + result.stderr
        return events.read_text() if events.exists() else ''

    defaults = (source / 'etc/uci-defaults/95-flowdns').read_text()
    defaults = defaults.replace('/etc/flowdns', str(root / 'etc/flowdns'))
    defaults = defaults.replace('/etc/init.d/flowdns', 'bash ' + shlex.quote(str(rc)) + ' ' + shlex.quote(str(init)))
    subprocess.run(['bash', '-c', defaults], env=env, check=True, capture_output=True)
    call('enabled')
    assert (root / 'etc/rc.d/S99flowdns').is_symlink()
    assert (root / 'etc/rc.d/K10flowdns').is_symlink()
    assert (root / 'etc/flowdns').stat().st_mode & 0o777 == 0o700
    print('PASS: installation defaults register actual rc.common start/stop links with private data directory')

    calls = call('boot')
    assert 'open_instance main\n' in calls
    assert 'param command /usr/libexec/flowdns-run boot\n' in calls
    assert 'param respawn 3600 5 3\n' in calls and 'param term_timeout 10\n' in calls
    assert (root / 'var/run/flowdns/state').read_text().strip() == 'waiting'
    print('PASS: enabled boot submits the dependency-waiting supervisor and respawn contract')

    events.unlink()
    calls = call('boot', FIXTURE_ENABLED='0')
    assert 'open_instance' not in calls and 'param command' not in calls
    print('PASS: disabling FlowDNS prevents a core instance from being registered on boot')

    events.unlink()
    calls = call('start_recovery')
    assert 'param command /usr/libexec/flowdns-run recovery\n' in calls
    events.unlink()
    calls = call('service_triggers', CONFIG_main_networks='lan lan2')
    assert 'reload_trigger flowdns\n' not in calls
    assert 'interface_trigger interface.*.up lan /etc/init.d/flowdns reload\n' in calls
    assert 'interface_trigger interface.*.up lan2 /etc/init.d/flowdns reload\n' in calls
    print('PASS: recovery mode and configured LAN interface triggers are submitted correctly')

    for mode in ('prepared', 'recovery'):
        events.unlink()
        calls = call('start', FLOWDNS_MODE=mode)
        assert 'param command /usr/libexec/flowdns-run ' + mode + '\n' in calls
        events.unlink()
        calls = call('reload', good=False, FIXTURE_BUSY='1')
        assert 'backend queue apply\n' in calls
        assert 'open_instance' not in calls and 'param command' not in calls
    events.unlink()
    calls = call('reload')
    assert 'backend queue apply\n' in calls and 'param command' not in calls
    print('PASS: concurrent reload never replaces a prepared/recovery instance with a boot waiting on its apply lock')

    call('disable')
    assert not (root / 'etc/rc.d/S99flowdns').is_symlink()
    assert not (root / 'etc/rc.d/K10flowdns').is_symlink()
    print('PASS: disabling init registration removes only this service start/stop links')
