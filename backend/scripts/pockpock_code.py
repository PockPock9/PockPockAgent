"""Launcher for PockPock Code, the terminal coding agent: python backend/scripts/pockpock_code.py [request]."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from projects.coding_cli.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
