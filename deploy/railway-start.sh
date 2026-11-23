#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" -eq 0 ]; then
    test "${RAILWAY_VOLUME_MOUNT_PATH:-}" = /workspace/volume
    export DOCINTEL_DATA=/workspace/volume/ledger
    install -d -m 0700 -o ledger -g ledger "$DOCINTEL_DATA"
    exec gosu ledger:ledger python -m app.serve
fi
exec python -m app.serve
