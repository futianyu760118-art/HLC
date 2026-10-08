#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "migrate-first-tenant.sh must run as root" >&2
    exit 1
fi

umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON_ENTRY="$SCRIPT_DIR/backend-python/scripts/server_first_tenant_migration.py"
if [ -L "$SCRIPT_DIR/current" ] && [ -f "$SCRIPT_DIR/current/backend-python/scripts/server_first_tenant_migration.py" ]; then
    PYTHON_ENTRY="$SCRIPT_DIR/current/backend-python/scripts/server_first_tenant_migration.py"
fi
exec python3 "$PYTHON_ENTRY" \
    --deployment-root "$SCRIPT_DIR" "$@"
