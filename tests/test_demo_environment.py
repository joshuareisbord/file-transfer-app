"""Integration contract for the two-computer Docker demo topology."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_demo_compose_defines_two_browser_computers_and_key_bootstrap() -> None:
    """Require an app sender and visible file-browser receiver on local ports."""

    if shutil.which("docker") is None:
        pytest.skip("Docker is unavailable")

    project_directory = Path(__file__).resolve().parents[1]
    compose_file = project_directory / "compose.demo.yaml"
    assert compose_file.is_file()

    result = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            str(compose_file),
            "config",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(result.stdout)["services"]

    assert set(services) == {"computer-a", "computer-b", "demo-keygen"}
    assert services["computer-a"]["environment"]["PEER_HOST"] == "computer-b"
    assert "PEER_HOST" not in services["computer-b"]["environment"]
    assert services["computer-a"]["ports"][0]["published"] == "6081"
    assert services["computer-b"]["ports"][0]["published"] == "6082"
    assert services["computer-a"]["depends_on"]["demo-keygen"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["computer-b"]["depends_on"]["demo-keygen"]["condition"] == (
        "service_completed_successfully"
    )

    a_key_volume = next(
        volume
        for volume in services["computer-a"]["volumes"]
        if volume["target"] == "/demo-keys"
    )
    b_key_volume = next(
        volume
        for volume in services["computer-b"]["volumes"]
        if volume["target"] == "/demo-keys"
    )
    assert a_key_volume["source"] != b_key_volume["source"]
    assert "22" not in services["computer-a"].get("expose", [])
    assert "22" in services["computer-b"]["expose"]

    entrypoint = (project_directory / "packaging/demo/side-entrypoint.sh").read_text()
    assert '"$demo_home/library-updates"' in entrypoint
    assert '"$demo_home/software-updates"' in entrypoint
    assert "/home/demo/incoming" not in entrypoint
    assert '/usr/local/bin/demo-desktop "$side"' in entrypoint

    desktop = (project_directory / "packaging/demo/desktop.sh").read_text()
    dockerfile = (project_directory / "packaging/Dockerfile").read_text()
    assert "--logo /usr/local/share/work-transfer/work-transfer-mark.svg" in desktop
    assert 'pcmanfm --no-desktop "$HOME/library-updates"' in desktop
    assert "pcmanfm" in dockerfile
    assert "packaging/demo/work-transfer-mark.svg" in dockerfile
    assert "install -d -m 755 /usr/local/share/work-transfer" in dockerfile
    assert "-rfbauth" in desktop
    assert "-nopw" not in desktop
