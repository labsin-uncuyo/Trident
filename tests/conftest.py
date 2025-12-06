from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTAINERS = [
    "lab_router",
    "lab_switch",
    "lab_slips_defender",
    "lab_compromised",
    "lab_server",
]


def _load_env() -> Dict[str, str]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path = ROOT / ".env.example"
    data: Dict[str, str] = {}
    with env_path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            data[key.strip()] = value.strip()
    return data


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("COMPOSE_PROJECT_NAME", "lab")
    env.update(_ENV_CACHE)
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def wait_for_health(containers: list[str], timeout: int = 120) -> None:
    deadline = time.time() + timeout
    template = "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
    while time.time() < deadline:
        states = []
        for name in containers:
            result = subprocess.run(
                ["docker", "inspect", "-f", template, name],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            state = result.stdout.strip() if result.returncode == 0 else "missing"
            states.append(state)
        if all(state == "healthy" for state in states):
            return
        time.sleep(3)
    raise AssertionError(f"Containers not healthy: {states}")


_ENV_CACHE = _load_env()


def _prepare_outputs(run_id: str) -> None:
    base = ROOT / "outputs" / run_id
    for name in ("pcaps", "slips"):
        (base / name).mkdir(parents=True, exist_ok=True)
    pcaps = base / "pcaps"
    for pattern in ("pytest_injected_*.pcap*", "manual_test_*.pcap*", "test.pcap*"):
        for leftover in pcaps.glob(pattern):
            try:
                leftover.unlink()
            except OSError:
                pass


@pytest.fixture(scope="session")
def lab_env() -> Dict[str, str]:
    return _ENV_CACHE


@pytest.fixture(scope="session", autouse=True)
def stack_ready(lab_env: Dict[str, str]):
    _prepare_outputs(lab_env.get("RUN_ID", "run_local"))
    run(["make", "down"], check=False)
    run(["make", "up"])
    wait_for_health(CONTAINERS)
    yield
    try:
        run(["make", "down"], check=False)
    except Exception:
        pass


@pytest.fixture()
def runner():
    def _runner(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        return run(cmd, check=check)

    return _runner
