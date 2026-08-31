from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from work_transfer_app.config import (
    ConfigLoadError,
    MockTestDefinition,
    load_mock_tests,
    load_update_destinations,
)


def test_bundled_update_destinations_are_safe_fixed_defaults() -> None:
    destinations = load_update_destinations()

    assert destinations.library_update == "~/library-updates"
    assert destinations.software_update == "~/software-updates"
    with pytest.raises(FrozenInstanceError):
        destinations.library_update = "/changed"  # type: ignore[misc]


def test_update_destinations_normalize_valid_posix_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "updates.toml"
    config_path.write_text(
        """
[destinations]
library_update = "~/updates/./library/"
software_update = "/srv/work-transfer/./software/"
""".strip(),
        encoding="utf-8",
    )

    destinations = load_update_destinations(config_path)

    assert destinations.library_update == "~/updates/library"
    assert destinations.software_update == "/srv/work-transfer/software"


@pytest.mark.parametrize(
    "content, expected_detail",
    [
        ("[destinations]\nlibrary_update = '~/library-updates'", "software_update"),
        (
            (
                "[destinations]\nlibrary_update = 'relative/path'\n"
                "software_update = '~/software-updates'"
            ),
            "absolute POSIX path or start with '~/'",
        ),
        (
            (
                "[destinations]\nlibrary_update = '~/../library'\n"
                "software_update = '~/software-updates'"
            ),
            "must not contain '..'",
        ),
        (
            (
                "[destinations]\nlibrary_update = '~/library-updates'\n"
                "software_update = '/srv/software'\nunexpected = '/tmp'"
            ),
            "unexpected key",
        ),
        (
            (
                '[destinations]\nlibrary_update = "~/bad\\u0000path"\n'
                "software_update = '~/software-updates'"
            ),
            "must not contain NUL",
        ),
        (
            (
                '[destinations]\nlibrary_update = "~/bad\\npath"\n'
                "software_update = '~/software-updates'"
            ),
            "must not contain NUL",
        ),
        (
            (
                '[destinations]\nlibrary_update = "~/bad\\rpath"\n'
                "software_update = '~/software-updates'"
            ),
            "must not contain NUL",
        ),
    ],
)
def test_update_destinations_reject_invalid_content(
    tmp_path: Path,
    content: str,
    expected_detail: str,
) -> None:
    config_path = tmp_path / "updates.toml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigLoadError, match=expected_detail):
        load_update_destinations(config_path)


def test_bundled_mock_tests_satisfy_the_configurable_contract() -> None:
    definitions = load_mock_tests()

    assert definitions
    assert all(definition.id and definition.name for definition in definitions)
    with pytest.raises(FrozenInstanceError):
        definitions[0].name = "Changed"  # type: ignore[misc]


def test_mock_tests_load_ordered_custom_definitions(tmp_path: Path) -> None:
    config_path = tmp_path / "tests.toml"
    config_path.write_text(
        """
[[tests]]
id = "second_stage"
name = "Second stage"

[[tests]]
id = "first_stage"
name = "First stage"
""".strip(),
        encoding="utf-8",
    )

    assert load_mock_tests(config_path) == (
        MockTestDefinition(id="second_stage", name="Second stage"),
        MockTestDefinition(id="first_stage", name="First stage"),
    )


@pytest.mark.parametrize(
    "content, expected_detail",
    [
        ("tests = []", "at least one"),
        ("[[tests]]\nid = 'unsafe id'\nname = 'Test'", "safe identifier"),
        (
            "[[tests]]\nid = 'same'\nname = 'A'\n[[tests]]\nid = 'same'\nname = 'B'",
            "duplicate",
        ),
        ("[[tests]]\nid = 'valid'\nname = '   '", "nonblank"),
        ("[[tests]]\nid = 'valid'\nname = 'Test'\nextra = true", "unexpected key"),
    ],
)
def test_mock_tests_reject_invalid_content(
    tmp_path: Path,
    content: str,
    expected_detail: str,
) -> None:
    config_path = tmp_path / "tests.toml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigLoadError, match=expected_detail):
        load_mock_tests(config_path)


@pytest.mark.parametrize("loader", [load_update_destinations, load_mock_tests])
def test_application_config_reports_missing_or_malformed_files(
    tmp_path: Path,
    loader: object,
) -> None:
    missing_path = tmp_path / "missing.toml"
    malformed_path = tmp_path / "malformed.toml"
    malformed_path.write_text("not valid = [", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="Unable to read"):
        loader(missing_path)  # type: ignore[operator]
    with pytest.raises(ConfigLoadError, match="Invalid TOML"):
        loader(malformed_path)  # type: ignore[operator]
