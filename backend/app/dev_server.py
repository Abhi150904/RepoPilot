from __future__ import annotations

import subprocess
import sys


def main() -> None:
    print("Starting RepoPilot API dev server on http://127.0.0.1:8000", flush=True)
    print(
        "Watching only backend/app and backend/migrations.",
        flush=True,
    )
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.api.app:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--reload",
                "--reload-dir",
                "backend/app",
                "--reload-dir",
                "backend/migrations",
            ]
        )
    )


if __name__ == "__main__":
    main()
