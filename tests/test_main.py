import pytest

from work_transfer_app.__main__ import main


def test_self_check_loads_transport_and_language_resources(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The packaged readiness check covers its runtime dependencies."""

    exit_code = main(["--self-check"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "work-transfer: ready (SCP transport and language resources loaded)\n"
    )
