"""Safely decode optional SVG and raster branding for the application header."""

from __future__ import annotations

import math
import re
import stat
import tkinter as tk
import warnings
from io import BytesIO
from os import fstat
from pathlib import Path
from xml.etree import ElementTree

import resvg_py
from PIL import Image, ImageTk, UnidentifiedImageError

_HEADER_LOGO_SIZE = (48, 48)
_MAX_INPUT_BYTES = 5 * 1024 * 1024
_MAX_RASTER_SIDE = 4096
_MAX_RASTER_PIXELS = 16_000_000
_RASTER_SUFFIXES = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})
_RASTER_FORMATS = ("GIF", "JPEG", "PNG", "WEBP")
_SVG_LENGTH = re.compile(
    r"^\s*(?P<value>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?:px)?\s*$"
)
_SVG_URL = re.compile(r"url\(\s*['\"]?(?P<target>[^)'\"\s]+)['\"]?\s*\)", re.IGNORECASE)
_FORBIDDEN_SVG_TEXT = ("<!doctype", "<!entity", "<script", "<foreignobject", "@import")
_FORBIDDEN_SVG_ELEMENTS = frozenset({"foreignobject", "image", "script"})


class LogoLoadError(ValueError):
    """Report an unsafe, unsupported, or unreadable header logo."""


def prepare_header_logo(
    path: Path,
    *,
    target_size: tuple[int, int] = _HEADER_LOGO_SIZE,
) -> Image.Image:
    """Decode one allowlisted logo into a bounded metadata-free RGBA image."""

    logo_path = path.expanduser().resolve()
    suffix = logo_path.suffix.casefold()
    if suffix != ".svg" and suffix not in _RASTER_SUFFIXES:
        raise LogoLoadError(
            "Unsupported logo format. Use SVG, PNG, JPEG, GIF, or WebP."
        )
    if target_size[0] < 1 or target_size[1] < 1:
        raise ValueError("Logo target dimensions must be positive.")

    source = _read_bounded_file(logo_path)
    if suffix == ".svg":
        source = _render_safe_svg(source, target_size)
    return _decode_raster(source, target_size)


def create_tk_header_logo(
    parent: tk.Misc,
    image: Image.Image,
) -> ImageTk.PhotoImage:
    """Create the Tk image retained by the owning application window."""

    return ImageTk.PhotoImage(image, master=parent)


def _read_bounded_file(path: Path) -> bytes:
    """Read a regular file while enforcing the encoded-size ceiling."""

    try:
        with path.open("rb") as logo_file:
            file_status = fstat(logo_file.fileno())
            if not stat.S_ISREG(file_status.st_mode):
                raise LogoLoadError("Logo path must reference a regular file.")
            if file_status.st_size > _MAX_INPUT_BYTES:
                raise LogoLoadError("Logo file exceeds the 5 MiB encoded-size limit.")
            source = logo_file.read(_MAX_INPUT_BYTES + 1)
    except LogoLoadError:
        raise
    except (OSError, ValueError) as error:
        raise LogoLoadError(f"Unable to read logo file: {error}") from error

    if not source:
        raise LogoLoadError("Logo file is empty.")
    if len(source) > _MAX_INPUT_BYTES:
        raise LogoLoadError("Logo file exceeds the 5 MiB encoded-size limit.")
    return source


def _render_safe_svg(source: bytes, target_size: tuple[int, int]) -> bytes:
    """Validate an isolated SVG and render it directly to bounded PNG bytes."""

    try:
        svg_text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LogoLoadError("SVG logo must be valid UTF-8.") from error

    normalized = svg_text.casefold()
    if any(token in normalized for token in _FORBIDDEN_SVG_TEXT):
        raise LogoLoadError("SVG logo contains unsupported active content.")
    try:
        root = ElementTree.fromstring(svg_text)
    except ElementTree.ParseError as error:
        raise LogoLoadError(f"SVG logo is malformed: {error}") from error
    if _local_name(root.tag) != "svg":
        raise LogoLoadError("SVG logo must have an <svg> root element.")

    for element in root.iter():
        if _local_name(element.tag) in _FORBIDDEN_SVG_ELEMENTS:
            raise LogoLoadError("SVG logo cannot load external resources.")
        for attribute, value in element.attrib.items():
            if _local_name(attribute) == "href" and not value.strip().startswith("#"):
                raise LogoLoadError("SVG logo cannot load external resources.")
    for match in _SVG_URL.finditer(svg_text):
        if not match.group("target").startswith("#"):
            raise LogoLoadError("SVG logo cannot load external resources.")

    source_size = _svg_dimensions(root)
    output_width, output_height = _fit_size(source_size, target_size)
    try:
        return resvg_py.svg_to_bytes(
            svg_string=svg_text,
            width=output_width,
            height=output_height,
            log_information=False,
        )
    except (OverflowError, TypeError, ValueError) as error:
        raise LogoLoadError(f"Unable to render SVG logo: {error}") from error


def _svg_dimensions(root: ElementTree.Element) -> tuple[float, float]:
    """Extract finite positive SVG dimensions without invoking a renderer."""

    attributes = {_local_name(key): value for key, value in root.attrib.items()}
    view_box = attributes.get("viewbox")
    if view_box is not None:
        parts = [part for part in re.split(r"[\s,]+", view_box.strip()) if part]
        if len(parts) != 4:
            raise LogoLoadError("SVG viewBox must contain four numeric values.")
        try:
            width, height = float(parts[2]), float(parts[3])
        except ValueError as error:
            raise LogoLoadError(
                "SVG viewBox must contain four numeric values."
            ) from error
        return _validated_dimensions(width, height)

    return _validated_dimensions(
        _svg_length(attributes.get("width"), "width"),
        _svg_length(attributes.get("height"), "height"),
    )


def _svg_length(value: str | None, name: str) -> float:
    """Parse one unitless or pixel-based SVG dimension."""

    match = _SVG_LENGTH.fullmatch(value or "")
    if match is None:
        raise LogoLoadError(f"SVG logo requires a numeric {name} or a valid viewBox.")
    return float(match.group("value"))


def _validated_dimensions(width: float, height: float) -> tuple[float, float]:
    """Reject non-finite or non-positive source dimensions."""

    if not math.isfinite(width) or not math.isfinite(height):
        raise LogoLoadError("SVG logo dimensions must be finite.")
    if width <= 0 or height <= 0:
        raise LogoLoadError("SVG logo dimensions must be positive.")
    return width, height


def _decode_raster(source: bytes, target_size: tuple[int, int]) -> Image.Image:
    """Decode an allowlisted raster without retaining metadata or animation."""

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(source), formats=_RASTER_FORMATS) as opened:
                width, height = opened.size
                if (
                    width > _MAX_RASTER_SIDE
                    or height > _MAX_RASTER_SIDE
                    or width * height > _MAX_RASTER_PIXELS
                ):
                    raise LogoLoadError(
                        "Logo exceeds the 4096px side or 16M decoded-pixel limit."
                    )
                opened.seek(0)
                opened.load()
                sanitized = opened.convert("RGBA")
    except LogoLoadError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        raise LogoLoadError(f"Unable to decode logo image: {error}") from error

    output_size = _fit_size(sanitized.size, target_size)
    if sanitized.size == output_size:
        return sanitized
    return sanitized.resize(output_size, Image.Resampling.LANCZOS)


def _fit_size(
    source_size: tuple[float, float] | tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int]:
    """Fit one aspect ratio within the target box, including safe upscaling."""

    width, height = source_size
    scale = min(target_size[0] / width, target_size[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _local_name(qualified_name: str) -> str:
    """Return a case-insensitive XML local name from a qualified name."""

    return qualified_name.rsplit("}", 1)[-1].casefold()
