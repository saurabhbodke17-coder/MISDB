"""Apply committed migrations using the separate local owner credential."""

import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
owner = (root / ".runtime/owner-dsn").read_text().strip()
subprocess.run(
    [
        str(root / "backend/.venv/bin/python"),
        str(root / "backend/manage.py"),
        "migrate",
    ],
    env=os.environ | {"DATABASE_URL": owner},
    check=True,
)
