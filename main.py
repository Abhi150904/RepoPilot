from __future__ import annotations

from pathlib import Path
import sys


BACKEND_PATH = Path(__file__).resolve().parent / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
