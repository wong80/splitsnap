#!/bin/sh
set -e
# Apply migrations before the web server starts (single-command startup).
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi
exec "$@"
