"""Run on the execution host every minute, independently of the app/SSH connection."""
from datetime import datetime, timezone
import json
import subprocess


def reap() -> None:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=repopilot.sandbox=true"],
        capture_output=True, text=True, check=True, timeout=20,
    )
    for container in result.stdout.split():
        if len(container) != 12 or any(char not in "0123456789abcdef" for char in container):
            continue
        inspected = subprocess.run(["docker", "inspect", container], capture_output=True,
                                   text=True, timeout=20, check=False)
        if inspected.returncode:
            continue
        info = json.loads(inspected.stdout)[0]
        if info.get("Config", {}).get("Labels", {}).get("repopilot.sandbox") != "true":
            continue
        created = datetime.fromisoformat(info["Created"].replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - created).total_seconds() > 600:
            subprocess.run(["docker", "rm", "--force", container], check=False, timeout=20)


if __name__ == "__main__":
    reap()
