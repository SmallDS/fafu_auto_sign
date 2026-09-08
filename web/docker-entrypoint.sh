#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/images/library /data/images/latest /data/logs
    chown -R fafu:fafu /data
    exec gosu fafu "$@"
fi

exec "$@"
