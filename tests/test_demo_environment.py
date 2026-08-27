"""Integration contract for the two-computer Docker demo topology."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_demo_compose_defines_two_browser_computers_and_key_bootstrap() -> None:
    """Require two reciprocal app/SSH services behind localhost browser ports."""

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
    assert services["computer-b"]["environment"]["PEER_HOST"] == "computer-a"
    assert services["computer-a"]["ports"][0]["published"] == "6081"
    assert services["computer-b"]["ports"][0]["published"] == "6082"
    assert services["computer-a"]["depends_on"]["demo-keygen"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["computer-b"]["depends_on"]["demo-keygen"]["condition"] == (
        "service_completed_successfully"
    )
