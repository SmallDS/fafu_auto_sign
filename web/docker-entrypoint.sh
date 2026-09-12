#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/users /data/logs
    chown -R fafu:fafu /data
    exec gosu fafu "$@"
fi

exec "$@"
