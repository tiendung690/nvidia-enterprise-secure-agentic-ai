from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "ops" / "sql"
MIGRATIONS = (
    "001_enterprise_schema.sql",
    # 002 is intentionally demo operational seed data and is not applied in AWS production.
    "003_seed_document_registry.sql",
    "004_governed_memory_and_trace.sql",
    "005_v6_security_hardening.sql",
    "006_messaging_lab.sql",
)


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def ensure_role(conn: psycopg.Connection, name: str, password: str, *, bypass_rls: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
        exists = cur.fetchone() is not None
        bypass = sql.SQL("BYPASSRLS") if bypass_rls else sql.SQL("NOBYPASSRLS")
        if exists:
            cur.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE {}").format(
                    sql.Identifier(name), bypass
                ),
                (password,),
            )
        else:
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE {}").format(
                    sql.Identifier(name), bypass
                ),
                (password,),
            )


def main() -> None:
    admin_url = required("MIGRATION_DATABASE_URL")
    app_password = required("DB_APP_PASSWORD")
    registry_password = required("DB_REGISTRY_PASSWORD")

    if len(app_password) < 24 or len(registry_password) < 24:
        raise RuntimeError("database role passwords must be at least 24 characters")

    with psycopg.connect(admin_url, autocommit=True) as conn:
        ensure_role(conn, "agentic_app", app_password, bypass_rls=False)
        ensure_role(conn, "agentic_registry", registry_password, bypass_rls=False)

        for filename in MIGRATIONS:
            path = SQL_DIR / filename
            if not path.exists():
                raise FileNotFoundError(path)
            print(f"Applying {filename}", flush=True)
            conn.execute(path.read_text(encoding="utf-8"))

    print("PostgreSQL migrations completed", flush=True)


if __name__ == "__main__":
    main()
