"""Read Harness/.env into the environment. Standard library only, so lightweight commands can use it."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = DEFAULT_ENV) -> None:
    """Read KEY=value lines into os.environ without overriding variables that are already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        k = k.strip()
        if sep and k and not k.startswith("#"):
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))
