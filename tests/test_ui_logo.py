"""Behavior tests for optional header-logo decoding."""

import os
from pathlib import Path

import pytest
from PIL import Image

import work_transfer_app.ui.logo as logo_module
from work_transfer_app.ui.logo import LogoLoadError, prepare_header_logo


def test_prepare_header_logo_supports_svg_and_raster(tmp_path: Path) -> None:
    """Render safe SVG and raster files into the bounded header box."""

    svg_path = tmp_path / "brand.svg"
    svg_path.write_text(
        """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">
  <defs>
    <linearGradient id="brand" x1="0" x2="1">
      <stop offset="0" stop-color="#1F3B64"/>
      <stop offset="1" stop-color="#E4592D"/>
    </linearGradient>
    <path id="mark" d="M0 0h100v50H0z"/>
  </defs>
  <use href="#mark" fill="url(#brand)"/>
</svg>
""".strip(),
        encoding="utf-8",
    )
    png_path = tmp_path / "brand.png"
    Image.new("RGBA", (12, 6), (31, 59, 100, 255)).save(png_path)

    svg_logo = prepare_header_logo(svg_path)
    png_logo = prepare_header_logo(png_path)

    assert svg_logo.mode == "RGBA"
    assert svg_logo.size == (48, 24)
    assert png_logo.mode == "RGBA"
    assert png_logo.size == (48, 24)


def test_prepare_header_logo_rejects_external_svg_resources(tmp_path: Path) -> None:
    """Reject SVG references which could read files or make network requests."""

    logo_path = tmp_path / "external.svg"
    logo_path.write_text(
        """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
  <image href="file:///etc/passwd" width="20" height="20"/>
</svg>
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(LogoLoadError, match="external resources"):
        prepare_header_logo(logo_path)


def test_prepare_header_logo_rejects_oversized_raster(tmp_path: Path) -> None:
    """Reject excessive decoded dimensions before loading raster pixels."""

    logo_path = tmp_path / "oversized.png"
    Image.new("1", (5000, 4000)).save(logo_path)

    with pytest.raises(LogoLoadError, match="pixel limit"):
        prepare_header_logo(logo_path)


def test_prepare_header_logo_rejects_encoded_size_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject oversized files from metadata before allocating their contents."""

    logo_path = tmp_path / "oversized.png"
    with logo_path.open("wb") as logo_file:
        logo_file.truncate(5 * 1024 * 1024 + 1)

    def unexpected_read(_path: Path) -> bytes:
        """Fail if the implementation reads a file already known to be oversized."""

        raise AssertionError("oversized logo was read")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)

    with pytest.raises(LogoLoadError, match="encoded-size limit"):
        prepare_header_logo(logo_path)


def test_prepare_header_logo_reads_the_opened_file_when_path_is_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep validation and decoding bound to one descriptor during replacement."""

    logo_path = tmp_path / "brand.png"
    replacement_path = tmp_path / "replacement.png"
    Image.new("RGBA", (12, 6), (31, 59, 100, 255)).save(logo_path)
    Image.new("RGBA", (9, 9), (188, 32, 38, 255)).save(replacement_path)
    real_fstat = os.fstat
    path_was_replaced = False

    def replace_path_after_open(file_descriptor: int) -> os.stat_result:
        """Replace the pathname while preserving the already-open descriptor."""

        nonlocal path_was_replaced
        if not path_was_replaced:
            replacement_path.replace(logo_path)
            path_was_replaced = True
        return real_fstat(file_descriptor)

    monkeypatch.setattr(logo_module, "fstat", replace_path_after_open)

    logo = prepare_header_logo(logo_path)

    assert path_was_replaced is True
    assert logo.size == (48, 24)
    assert logo.getpixel((24, 12)) == (31, 59, 100, 255)


@pytest.mark.parametrize("suffix", [".txt", ".svgz", ".tiff"])
def test_prepare_header_logo_rejects_unsupported_formats(
    tmp_path: Path,
    suffix: str,
) -> None:
    """Keep decoding restricted to the documented logo format allowlist."""

    logo_path = tmp_path / f"brand{suffix}"
    logo_path.write_bytes(b"not an accepted logo")

    with pytest.raises(LogoLoadError, match="Unsupported logo format"):
        prepare_header_logo(logo_path)
