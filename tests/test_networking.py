from __future__ import annotations

import json
import shutil
import time

import paramiko
import pytest

from conftest import CONTAINERS, ROOT, run, wait_for_health


def _container_health(name: str) -> str:
    template = "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
    result = run(["docker", "inspect", "-f", template, name], check=False)
    if result.returncode != 0:
        return "missing"
    return result.stdout.strip()


def _ssh_check(port: int, password: str) -> str:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("127.0.0.1", port=port, username="labuser", password=password, timeout=15)
    try:
        _, stdout, _ = client.exec_command("echo ok")
        return stdout.read().decode().strip()
    finally:
        client.close()


def test_stack_up(stack_ready):
    wait_for_health(CONTAINERS)
    for name in CONTAINERS:
        assert _container_health(name) == "healthy", f"{name} not healthy"


def test_ssh_reachability(lab_env):
    password = lab_env["LAB_PASSWORD"]
    assert _ssh_check(2223, password) == "ok"


def test_network_connectivity():
    result = run([
        "docker",
        "exec",
        "lab_compromised",
        "bash",
        "-lc",
        "curl -s -o /tmp/body -w '%{http_code}' http://172.31.0.10:80",
    ])
    assert result.stdout.strip().endswith("200")


def test_alert_flow(lab_env):
    run_id = lab_env["RUN_ID"]
    outputs_dir = ROOT / "outputs" / run_id
    dataset_dir = outputs_dir / "pcaps"
    slips_output_dir = outputs_dir / "slips"
    alert_file = outputs_dir / "slips" / "defender_alerts.ndjson"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    slips_output_dir.mkdir(parents=True, exist_ok=True)

    server_pcap = dataset_dir / "server.pcap"
    deadline = time.time() + 60
    while time.time() < deadline:
        if server_pcap.exists() and server_pcap.stat().st_size > 0:
            break
        run(["docker", "exec", "lab_compromised", "ping", "-c", "1", "172.31.0.10"], check=False)
        time.sleep(2)
    else:
        pytest.fail("server.pcap not populated")

    injected = dataset_dir / f"pytest_injected_{int(time.time())}.pcap"
    shutil.copy(server_pcap, injected)

    def _alerts_snapshot():
        snapshot = {}
        for path in slips_output_dir.glob("**/alerts.log"):
            with path.open("r", encoding="utf-8") as handle:
                snapshot[path] = len(handle.readlines())
        return snapshot

    before_snapshot = _alerts_snapshot()
    before_defender_lines = alert_file.read_text().splitlines() if alert_file.exists() else []

    deadline = time.time() + 240
    while time.time() < deadline:
        time.sleep(3)
        current_snapshot = _alerts_snapshot()
        delta = any(current_snapshot.get(path, 0) > before_snapshot.get(path, 0) for path in current_snapshot)
        defender_ready = alert_file.exists() and len(alert_file.read_text().splitlines()) > len(before_defender_lines)
        if delta and defender_ready:
            break
    else:
        pytest.fail("SLIPS alerts were not produced in time")

    found = False
    with alert_file.open() as fh:
        for line in fh:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("run_id") == run_id:
                found = True
                break
    assert found, "run_id not found in defender alerts"


def test_logrotate_and_pcap_rotation(lab_env):
    pcap_dir = ROOT / "outputs" / lab_env["RUN_ID"] / "pcaps"
    pcap_dir.mkdir(parents=True, exist_ok=True)
    run([
        "docker",
        "exec",
        "lab_router",
        "bash",
        "-lc",
        "dd if=/dev/zero of=/pcaps/test.pcap bs=1M count=12 >/dev/null 2>&1",
    ])
    run([
        "docker",
        "exec",
        "lab_router",
        "/management.sh",
        "rotate_pcaps",
    ])
    deadline = time.time() + 10
    rotated = None
    while time.time() < deadline:
        rotated = [p for p in pcap_dir.glob("test.pcap*") if p.name != "test.pcap"]
        if rotated:
            break
        time.sleep(1)
    assert rotated, "pcap rotation did not produce artifacts"


def test_restart_policy():
    run(["docker", "exec", "lab_server", "pkill", "-9", "nginx"])
    wait_for_health(["lab_server"], timeout=60)
    assert _container_health("lab_server") == "healthy"


def test_teardown():
    run(["make", "down"], check=False)
    result = run(["docker", "ps", "-a", "--format", "{{.Names}}"])
    leftovers = [name for name in result.stdout.splitlines() if name.startswith("lab_")]
    assert not leftovers, f"containers still running: {leftovers}"
