#!/bin/sh
# Local regression entry point. Must run from the repository root.
set -eu
[ "$#" -ge 3 ] || { echo 'usage: run.sh LUA HOST_LUA_MODULES HOST_SING_BOX [OUTPUT] [HOST_XRAY HOST_PRIVATE_DNS]' >&2; exit 2; }
FLOWDNS_TEST_LUA=$(realpath "$1")
FLOWDNS_TEST_MODULES=$(realpath "$2")
FLOWDNS_TEST_ENGINE=$(realpath "$3")
FLOWDNS_TEST_OUTPUT=${4:-/tmp/flowdns-regression}
export FLOWDNS_TEST_LUA FLOWDNS_TEST_MODULES
export LUA_PATH="$FLOWDNS_TEST_MODULES/?.lua;;"
export LUA_CPATH="$FLOWDNS_TEST_MODULES/?.so;;"
mkdir -p "$FLOWDNS_TEST_OUTPUT"
"$FLOWDNS_TEST_LUA" package/myapp/flowdns/tests/core.lua "$FLOWDNS_TEST_OUTPUT" --jsonc --binary
"$FLOWDNS_TEST_ENGINE" rule-set compile --output "$FLOWDNS_TEST_OUTPUT/domains.srs" "$FLOWDNS_TEST_OUTPUT/domains.json"
"$FLOWDNS_TEST_ENGINE" rule-set compile --output "$FLOWDNS_TEST_OUTPUT/ip.srs" "$FLOWDNS_TEST_OUTPUT/ip.json"
for config in "$FLOWDNS_TEST_OUTPUT"/config-*.json; do "$FLOWDNS_TEST_ENGINE" check -c "$config"; done
python3 package/myapp/flowdns/tests/rpc.py "$FLOWDNS_TEST_LUA" package/myapp/luci-app-flowdns/root/usr/libexec/rpcd/luci.flowdns
python3 package/myapp/flowdns/tests/rpc-runtime.py "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
python3 package/myapp/flowdns/tests/features.py "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
python3 package/myapp/flowdns/tests/updates.py "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
python3 package/myapp/flowdns/tests/private-core.py "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
python3 package/myapp/flowdns/tests/environment.py "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES" "$FLOWDNS_TEST_ENGINE"
python3 package/myapp/flowdns/tests/init.py
python3 package/myapp/flowdns/tests/supervisor.py
node package/myapp/flowdns/tests/frontend.js
python3 package/myapp/flowdns/tests/tls-fixture.py
python3 package/myapp/flowdns/tests/integration.py "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_OUTPUT" tls
python3 package/myapp/flowdns/tests/integration.py "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_OUTPUT" https
python3 package/myapp/flowdns/tests/benchmark.py
sh package/myapp/flowdns/tests/firewall.sh "$FLOWDNS_TEST_OUTPUT/firewall.nft"
sh package/myapp/flowdns/tests/startup.sh "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_OUTPUT" "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
sh package/myapp/flowdns/tests/lan.sh "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_OUTPUT"
if [ "$#" -ge 5 ]; then
	[ "$#" -ge 6 ] || { echo 'native tests require the built private DNS frontend as argument 6' >&2; exit 2; }
	FLOWDNS_TEST_FRONT=$(realpath "$6")
	export FLOWDNS_TEST_FRONT
	FLOWDNS_TEST_XRAY=$(realpath "$5")
	"$FLOWDNS_TEST_LUA" package/myapp/flowdns/tests/transparent.lua "$FLOWDNS_TEST_OUTPUT"
	python3 package/myapp/flowdns/tests/native-backend.py "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES" "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_XRAY"
	sh package/myapp/flowdns/tests/transparent.sh "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_XRAY" "$FLOWDNS_TEST_OUTPUT" "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
	FLOWDNS_TEST_REALITY=1 sh package/myapp/flowdns/tests/transparent.sh "$FLOWDNS_TEST_ENGINE" "$FLOWDNS_TEST_XRAY" "$FLOWDNS_TEST_OUTPUT" "$FLOWDNS_TEST_LUA" "$FLOWDNS_TEST_MODULES"
else
	echo 'SKIP: transparent-core tests require HOST_XRAY as argument 5'
fi
