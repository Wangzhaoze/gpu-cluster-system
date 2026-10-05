#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/lib/postgresql/14/bin:$PATH
mkdir -p "$PGDATA"
chown postgres:postgres "$PGDATA"
chmod 700 "$PGDATA"
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    umask 077
    printf '%s' "$POSTGRES_PASSWORD" > /tmp/lab-pg-password
    chown postgres:postgres /tmp/lab-pg-password
    runuser -u postgres -- initdb -D "$PGDATA" --encoding=UTF8 --locale=C.UTF-8 --username="$POSTGRES_USER" --pwfile=/tmp/lab-pg-password --auth-host=scram-sha-256 --auth-local=trust
    rm /tmp/lab-pg-password
    printf "\nlisten_addresses = '*'\n" >> "$PGDATA/postgresql.conf"
    printf '\nhost all all all scram-sha-256\n' >> "$PGDATA/pg_hba.conf"
    runuser -u postgres -- pg_ctl -D "$PGDATA" -o '-c listen_addresses=' -w start
    runuser -u postgres -- createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
    runuser -u postgres -- pg_ctl -D "$PGDATA" -m fast -w stop
fi
exec runuser -u postgres -- postgres -D "$PGDATA"
