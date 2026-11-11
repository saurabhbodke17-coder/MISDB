"""Restore LMS structure/data into an EMPTY standalone database, excluding platform execution and secrets.

Usage: python scripts/restore_dump.py --dump staging_lms_v2.dump --database-url ... --pg-restore pg_restore
The URL can instead be supplied in RESTORE_DATABASE_URL. Does not drop existing data.
"""

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

EXCLUDED_DATA = {
    "app_config",
    "auth_sessions",
    "otp_verifications",
    "web_refresh_tokens",
    "user_devices",
    "user_identities",
    "user_details",
    "user_mapping",
    "user_devices_backup_20260805",
    "user_invites",
    "users_backup",
}
ALLOWED = r"TYPE|DOMAIN|TABLE|TABLE DATA|SEQUENCE|SEQUENCE OWNED BY|SEQUENCE SET|DEFAULT|CONSTRAINT|FK CONSTRAINT|INDEX"


def restore(dump, database_url, binary, source_schema="public"):
    import psycopg
    from psycopg import sql

    with psycopg.connect(database_url) as conn:
        if conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') LIMIT 1").fetchone():
            raise RuntimeError("Restore requires an empty destination database")
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(source_schema)))
    listing = subprocess.check_output([binary, "--list", str(dump)], text=True)
    selected = []
    for line in listing.splitlines():
        match = re.match(rf"^\d+; \d+ \d+ ({ALLOWED}) {re.escape(source_schema)} (\S+)", line)
        if match and not (match[1] == "TABLE DATA" and match[2] in EXCLUDED_DATA):
            selected.append(line)
    if not selected:
        raise RuntimeError("No LMS objects found in selected schema")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".list") as f:
        f.write("\n".join(selected) + "\n")
        f.flush()
        env = os.environ | {"PGDATABASE": database_url}
        subprocess.run(
            [
                binary,
                "--no-owner",
                "--no-acl",
                "--single-transaction",
                "--exit-on-error",
                "--use-list",
                f.name,
                "--dbname",
                database_url,
                str(dump),
            ],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
        )
    if source_schema != "public":
        with psycopg.connect(database_url) as conn:
            conn.execute("DROP SCHEMA public")
            conn.execute(sql.SQL("ALTER SCHEMA {} RENAME TO public").format(sql.Identifier(source_schema)))
    print(
        f"Restored {len(selected)} selected LMS objects. Excluded platform schemas, functions, triggers, policies and secret-bearing table data."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dump", type=Path, required=True)
    p.add_argument("--database-url", default=os.getenv("RESTORE_DATABASE_URL"))
    p.add_argument("--pg-restore", default="pg_restore")
    p.add_argument("--source-schema", default="public")
    a = p.parse_args()
    if not a.database_url:
        p.error("Provide RESTORE_DATABASE_URL")
    restore(a.dump, a.database_url, a.pg_restore, a.source_schema)
