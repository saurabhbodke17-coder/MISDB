"""Explicit schema migrations and account provisioning; no automatic destructive setup."""

import argparse
import getpass
import hashlib
from pathlib import Path

import psycopg
from pwdlib import PasswordHash

from app.config import settings


def migrate():
    with psycopg.connect(settings().database_url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(81427193)")
        conn.execute("CREATE SCHEMA IF NOT EXISTS mis")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mis.schema_migrations (name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz DEFAULT now())"
        )
        for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            source = path.read_text()
            checksum = hashlib.sha256(source.encode()).hexdigest()
            old = conn.execute(
                "SELECT checksum FROM mis.schema_migrations WHERE name=%s", (path.name,)
            ).fetchone()
            if old:
                if old[0] != checksum:
                    raise RuntimeError(f"Applied migration changed: {path.name}")
                continue
            conn.execute(source)
            conn.execute(
                "INSERT INTO mis.schema_migrations(name,checksum) VALUES (%s,%s)", (path.name, checksum)
            )
            print(f"Applied {path.name}")


def create_account(username, name, role, password=None):
    password = password or getpass.getpass("New password (minimum 12 characters): ")
    if len(password) < 12:
        raise ValueError("Password must have at least 12 characters")
    with psycopg.connect(settings().database_url) as conn:
        conn.execute(
            "INSERT INTO mis.accounts(username,display_name,role,password_hash) VALUES (%s,%s,%s,%s)",
            (username.lower().strip(), name, role, PasswordHash.recommended().hash(password)),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    user = sub.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--name", required=True)
    user.add_argument("--role", choices=["admin", "operator", "viewer"], default="viewer")
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    else:
        create_account(args.username, args.name, args.role)
