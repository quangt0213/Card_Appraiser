"""Create carddata.db from schema.sql. Run once during setup:  python database/init_db.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_config          # noqa: E402
from database.repository import Repository  # noqa: E402


def main() -> None:
    cfg = get_config()
    cfg.ensure_dirs()
    schema = Path(__file__).resolve().parent / "schema.sql"
    repo = Repository(cfg.db_file)
    repo.initialize(schema)
    print(f"Initialized database at {cfg.db_file} ({repo.card_count()} cards).")


if __name__ == "__main__":
    main()
