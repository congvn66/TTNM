# PostgreSQL local runtime

`infra/compose/dev.yml` starts PostgreSQL 16 and mounts
`doc/initial-schema.sql` as the first-init SQL script. The SQL file is the
reviewed baseline; it is not a substitute for versioned Alembic migrations.

## Start

```powershell
docker compose -f infra/compose/dev.yml up -d postgres
docker compose -f infra/compose/dev.yml ps
```

The database is available at:

```text
postgresql://sourcelens:sourcelens-dev-only@127.0.0.1:5432/sourcelens
```

The current API still defaults to the JSON adapter. Do not set
`PERSISTENCE_BACKEND=postgres` until the repository cutover and migration
smoke tests are complete; the health endpoint will report whether the driver
and database are reachable.

## Reset a disposable local database

This removes only the named Docker volume for this project:

```powershell
docker compose -f infra/compose/dev.yml down -v
docker compose -f infra/compose/dev.yml up -d postgres
```

Never run the reset command against a shared or production volume.
