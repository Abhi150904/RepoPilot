"""Read-only app-host checks; send only an empty success/failure heartbeat."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


PING_FILE = Path("/etc/repopilot/healthchecks-url")
SERVICES = ("api", "database", "worker", "proxy")
SITE = "https://repo-pilot-sigma.vercel.app"
QUEUE_MAX_SECONDS = 1200

# This runs inside the existing API container, using its configured DB connection.
# Only aggregate health data leaves the container, never requests or credentials.
QUEUE_PROBE = """
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, select, func, or_
from app.api.runs import RunRow
from app.core.config import get_settings

now = datetime.now(timezone.utc)
engine = create_engine(get_settings().database_url, connect_args={
    "connect_timeout": 5, "options": "-c statement_timeout=10000"
})
try:
    with engine.connect() as connection:
        oldest = connection.scalar(select(func.min(RunRow.created_at)).where(
            RunRow.lifecycle_status == "queued"))
        stale = connection.scalar(select(func.count()).select_from(RunRow).where(
            RunRow.lifecycle_status == "running",
            or_(RunRow.lease_expires_at < now - timedelta(seconds=60),
                func.coalesce(RunRow.last_heartbeat_at, RunRow.updated_at)
                < now - timedelta(seconds=300))))
    print(json.dumps({"oldest_queue_seconds": max(0, (now - oldest).total_seconds())
                      if oldest else 0, "stale_running": stale}))
finally:
    engine.dispose()
"""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def command_json(arguments: list[str], timeout: int = 20):
    result = subprocess.run(arguments, capture_output=True, text=True,
                            timeout=timeout, check=True)
    return json.loads(result.stdout)


def request(url: str, *, json_body: bool = False) -> None:
    opener = build_opener(ProxyHandler({}), NoRedirects())
    with opener.open(Request(url, headers={"User-Agent": "RepoPilot-monitor/1"}), timeout=10) as response:
        if response.status != 200:
            raise ValueError("Unexpected HTTP status")
        if json_body:
            body = json.loads(response.read(65537))
            if body.get("status") != "ok" or body.get("service") != "repopilot":
                raise ValueError("Unexpected health response")


def queue_is_healthy(probe: dict) -> bool:
    age, stale = probe["oldest_queue_seconds"], probe["stale_running"]
    return (isinstance(age, (int, float)) and 0 <= age <= QUEUE_MAX_SECONDS
            and isinstance(stale, int) and stale == 0)


def check_production() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for service in SERVICES:
        try:
            state = command_json(["docker", "inspect", "--format", "{{json .State}}",
                                  f"repopilot-aws-{service}-1"])
            checks[service] = state.get("Running") is True and (
                service not in {"api", "database"}
                or state.get("Health", {}).get("Status") == "healthy")
        except Exception:
            checks[service] = False

    try:
        probe = command_json(["docker", "exec", "repopilot-aws-api-1",
                              "python", "-c", QUEUE_PROBE], timeout=40)
        checks["queue_and_leases"] = queue_is_healthy(probe)
    except Exception:
        checks["queue_and_leases"] = False

    for label, path in (("root_disk", "/"), ("workspace_disk", "/opt/repopilot/data")):
        try:
            disk = shutil.disk_usage(path)
            checks[label] = disk.free >= 2 * 1024**3 and disk.used / disk.total < 0.85
        except Exception:
            checks[label] = False

    for label, url, json_body in (
        ("website", SITE, False),
        ("public_api", SITE + "/api/health", True),
    ):
        try:
            request(url, json_body=json_body)
            checks[label] = True
        except Exception:
            checks[label] = False
    return checks


def load_ping_url(path: Path = PING_FILE) -> str:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Heartbeat file must be root-owned, private, and regular")
    url = path.read_text().strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "hc-ping.com"
            or parsed.query or parsed.fragment):
        raise ValueError("Expected an HTTPS hc-ping.com check URL")
    if parsed.path != "/" + str(UUID(parsed.path.lstrip("/"))):
        raise ValueError("Expected a canonical check UUID")
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Check locally without sending a heartbeat")
    args = parser.parse_args(argv)
    checks = check_production()
    healthy = bool(checks) and all(checks.values())
    print(json.dumps({"healthy": healthy, "checks": checks}), flush=True)
    if not args.check_only:
        try:
            url = load_ping_url()
            request(url if healthy else url + "/fail")
        except Exception:
            # Network exceptions may contain the secret URL. Never log their text.
            print("Heartbeat delivery failed; check local configuration or outbound access.", file=sys.stderr)
            return 2
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
