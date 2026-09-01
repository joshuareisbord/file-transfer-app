"""Packaging guarantees for the standalone Ubuntu executable."""

from pathlib import Path


def test_build_pins_required_lts_and_checks_runtime_without_python() -> None:
    """Keep every exported artifact tied to the supported standalone runtime."""

    dockerfile = (
        Path(__file__).resolve().parents[1] / "packaging" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "ARG UBUNTU_VERSION=24.04" in dockerfile
    assert "ubuntu:latest" not in dockerfile
    assert "FROM ubuntu:${UBUNTU_VERSION} AS runtime-check" in dockerfile
    assert "RUN ! command -v python3" in dockerfile
    assert "RUN /work-transfer --self-check" in dockerfile
    assert "COPY --from=runtime-check /work-transfer /work-transfer" in dockerfile
