#!/bin/sh
set -eu
FLOWDNS_TEST_PARENT_NETNS=$(readlink /proc/self/ns/net)
export FLOWDNS_TEST_PARENT_NETNS
exec unshare --user --map-root-user --net python3 "$(dirname "$0")/transparent.py" "$@"
