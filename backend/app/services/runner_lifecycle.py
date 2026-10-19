from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import re
import subprocess
import time

import httpx


logger = logging.getLogger(__name__)
ARM_ORIGIN = "https://management.azure.com"
IMDS_TOKEN_URL = "http://169.254.169.254/metadata/identity/oauth2/token"
API_VERSION = "2024-07-01"


class RunnerUnavailable(Exception):
    """A sanitized, retryable infrastructure failure; no run has been claimed."""


def valid_vm_resource_id(value: str | None) -> bool:
    return bool(value and re.fullmatch(
        r"/subscriptions/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        r"/resourceGroups/[A-Za-z0-9_.()-]+/providers/Microsoft\.Compute/virtualMachines/[A-Za-z0-9_-]+",
        value,
        flags=re.IGNORECASE,
    ))


class AzureRunnerVM:
    """Manage exactly one VM using the app host's system-assigned identity."""

    def __init__(self, resource_id: str, *, client: httpx.Client | None = None) -> None:
        if not valid_vm_resource_id(resource_id):
            raise ValueError("Invalid Azure runner VM resource ID.")
        self._url = ARM_ORIGIN + resource_id
        self._client = client or httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
        self._token: str | None = None
        self._expires_at = 0.0

    def close(self) -> None:
        self._client.close()

    def _access_token(self) -> str:
        if self._token and time.time() < self._expires_at - 120:
            return self._token
        response = self._client.get(
            IMDS_TOKEN_URL,
            params={"api-version": "2018-02-01", "resource": ARM_ORIGIN + "/"},
            headers={"Metadata": "true"},
        )
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        if not isinstance(token, str) or not token:
            raise ValueError("Invalid managed identity response.")
        self._expires_at = float(data["expires_on"])
        self._token = token
        return token

    def _request(self, method: str, operation: str) -> httpx.Response:
        try:
            response = self._client.request(
                method, self._url + "/" + operation,
                params={"api-version": API_VERSION},
                headers={"Authorization": "Bearer " + self._access_token()},
            )
            if response.status_code == 401:
                self._token = None
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Never surface token responses, request headers or cloud error bodies.
            raise RunnerUnavailable("Azure runner control unavailable; check managed identity and VM-scoped permissions.") from None

    def power_state(self) -> str:
        try:
            statuses = self._request("GET", "instanceView").json()["statuses"]
            for status in statuses:
                code = status.get("code", "")
                if code.startswith("PowerState/"):
                    return code.removeprefix("PowerState/")
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        raise RunnerUnavailable("Azure did not report a runner power state.")

    def start(self) -> None:
        self._request("POST", "start")

    def deallocate(self) -> None:
        self._request("POST", "deallocate")


def docker_ready(host: str, image: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "--host", host, "image", "inspect", "--format", "{{.Id}}", "--", image],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=15, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class RunnerLifecycle:
    def __init__(self, vm, *, ready, idle_seconds: float = 600, boot_timeout: float = 600,
                 clock=time.monotonic, sleep=time.sleep, shutdown_marker: Path | None = None) -> None:
        self.vm = vm
        self.ready = ready
        self.idle_seconds = idle_seconds
        self.boot_timeout = boot_timeout
        self.clock = clock
        self.sleep = sleep
        self._idle_since: float | None = None
        self._last_action: tuple[str, float] | None = None
        self._shutdown_marker = shutdown_marker
        self._shutdown_pending = bool(shutdown_marker and shutdown_marker.exists())

    def _action(self, action: str) -> None:
        now = self.clock()
        if self._last_action and self._last_action[0] == action and now - self._last_action[1] < 60:
            return
        if action == "deallocate":
            if self._shutdown_marker:
                self._shutdown_marker.touch(mode=0o600)
            self._shutdown_pending = True
        # Also throttle ambiguous timeouts: the cloud may have accepted the action.
        self._last_action = (action, now)
        getattr(self.vm, action)()
        logger.info("Runner VM %s requested.", action)

    def _observe_deallocated(self) -> None:
        if not self._shutdown_pending:
            return
        if self._shutdown_marker:
            self._shutdown_marker.unlink(missing_ok=True)
        self._shutdown_pending = False
        self._last_action = None

    def tick(self, has_work: bool) -> bool:
        """Only return True when it is safe for the sole worker to claim work."""
        if has_work:
            self._idle_since = None
            deadline = self.clock() + self.boot_timeout
            while self.clock() < deadline:
                state = self.vm.power_state()
                if state == "deallocated":
                    self._observe_deallocated()
                if self._shutdown_pending:
                    # An accepted shutdown may still report running briefly.
                    # Finish it before starting/claiming, even after a restart.
                    if state in {"running", "stopped"}:
                        self._action("deallocate")
                    self.sleep(5)
                    continue
                if state == "running" and self.ready():
                    self._last_action = None
                    return True
                if state in {"deallocated", "stopped"}:
                    self._action("start")
                elif state not in {"running", "starting", "stopping", "deallocating"}:
                    raise RunnerUnavailable("Runner VM is in an unexpected power state.")
                self.sleep(5)
            raise RunnerUnavailable("Runner is still preparing; queued runs will be retried.")

        now = self.clock()
        if self._idle_since is None:
            self._idle_since = now
        if now - self._idle_since >= self.idle_seconds:
            state = self.vm.power_state()
            if state in {"running", "stopped"}:
                self._action("deallocate")
            elif state in {"deallocated", "deallocating"}:
                if state == "deallocated":
                    self._observe_deallocated()
                self._idle_since = now
            # A previous start can complete after the queue was cleared. Keep
            # checking until it reaches running, then release its compute too.
        return False


@contextmanager
def runner_controller(settings):
    if not settings.azure_runner_enabled:
        yield None
        return
    if not settings.azure_runner_resource_id or not settings.sandbox_docker_host:
        raise SystemExit("Azure runner requires a VM resource ID and SSH Docker host.")
    try:
        import fcntl
    except ImportError:
        raise SystemExit("Azure runner automation requires a Linux worker.") from None
    path = Path(settings.azure_runner_lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("An Azure runner worker already holds the controller lock.") from None
        vm = AzureRunnerVM(settings.azure_runner_resource_id)
        try:
            yield RunnerLifecycle(
                vm,
                ready=lambda: docker_ready(settings.sandbox_docker_host, settings.sandbox_image),
                idle_seconds=settings.azure_runner_idle_seconds,
                boot_timeout=settings.azure_runner_boot_timeout_seconds,
                shutdown_marker=path.with_suffix(".deallocating"),
            )
        finally:
            vm.close()
            fcntl.flock(lock, fcntl.LOCK_UN)
