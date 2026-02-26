from __future__ import annotations

import base64
import contextlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO

# Kitty graphics protocol chunk size (4096 is the recommended max)
_CHUNK_SIZE = 4096

# Max columns for image display
_MAX_COLS = 100

# Max rows for image display
_MAX_ROWS = 35

# Minimum visible width (in terminal columns) for very tall diagrams.
_MIN_READABLE_COLS = 50

# Upper bound for row expansion when preserving readability of tall diagrams.
_MAX_TALL_ROWS = 120

# Image formats that need conversion to PNG
_NEEDS_CONVERSION = {".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg"}

# Approximate pixels per terminal cell (typical for most terminals)
_PIXELS_PER_COL = 9
_PIXELS_PER_ROW = 18

_SVG_SIPS_SCALE = 2.0
_SVG_SIPS_MAX_DIM = 4096

_SVG_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"([^\"]+)"')

_SVG_COLOR_REPLACEMENTS = {
    "var(--bg)": "#FFFFFF",
    "var(--fg)": "#27272A",
    "var(--_text)": "#27272A",
    "var(--_text-sec)": "#6B7280",
    "var(--_text-muted)": "#9CA3AF",
    "var(--_text-faint)": "#D1D5DB",
    "var(--_line)": "#9CA3AF",
    "var(--_arrow)": "#6B7280",
    "var(--_node-fill)": "#F9FAFB",
    "var(--_node-stroke)": "#D1D5DB",
    "var(--_group-fill)": "#FFFFFF",
    "var(--_group-hdr)": "#F3F4F6",
    "var(--_inner-stroke)": "#E5E7EB",
    "var(--_key-badge)": "#F3F4F6",
}

_SVG_CSS_DEFAULTS = {
    "text": "#27272A",
    "text-sec": "#6B7280",
    "text-muted": "#9CA3AF",
    "text-faint": "#D1D5DB",
    "line": "#9CA3AF",
    "arrow": "#6B7280",
    "node-fill": "#F9FAFB",
    "node-stroke": "#D1D5DB",
    "group-fill": "#FFFFFF",
    "group-hdr": "#F3F4F6",
    "inner-stroke": "#E5E7EB",
    "key-badge": "#F3F4F6",
}


def _get_png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract width and height from PNG header (IHDR chunk)."""
    # PNG signature (8 bytes) + IHDR length (4 bytes) + "IHDR" (4 bytes) + width (4 bytes) + height (4 bytes)
    if len(data) < 28 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _get_svg_viewbox(svg_text: str) -> tuple[float, float, float, float] | None:
    match = _SVG_VIEWBOX_RE.search(svg_text)
    if match is None:
        return None
    parts = match.group(1).split()
    if len(parts) != 4:
        return None
    try:
        x, y, width, height = (float(part) for part in parts)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _svg_thumb_likely_cropped(
    svg_viewbox: tuple[float, float, float, float] | None, png_dims: tuple[int, int] | None
) -> bool:
    if svg_viewbox is None or png_dims is None:
        return False
    _, _, svg_width, svg_height = svg_viewbox
    png_width, png_height = png_dims
    if png_width <= 0 or png_height <= 0:
        return False
    svg_ratio = max(svg_width, svg_height) / min(svg_width, svg_height)
    png_ratio = max(png_width, png_height) / min(png_width, png_height)
    return svg_ratio >= 3 and png_ratio < svg_ratio / 2


def _normalize_svg_for_sips(svg_text: str) -> str:
    normalized = svg_text
    for source, replacement in _SVG_COLOR_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)

    for name, color in _SVG_CSS_DEFAULTS.items():
        normalized = re.sub(rf"--_{re.escape(name)}\s*:\s*[^;]+;", f"--_{name}: {color};", normalized)

    svg_open_end = normalized.find(">")
    if svg_open_end != -1:
        svg_open_tag = normalized[: svg_open_end + 1]
        width_match = re.search(r'width\s*=\s*"([0-9]+(?:\.[0-9]+)?)"', svg_open_tag)
        height_match = re.search(r'height\s*=\s*"([0-9]+(?:\.[0-9]+)?)"', svg_open_tag)
        if width_match is not None and height_match is not None:
            width = float(width_match.group(1))
            height = float(height_match.group(1))
            current_max = max(width, height)
            if current_max > 0:
                scale = min(_SVG_SIPS_SCALE, _SVG_SIPS_MAX_DIM / current_max)
                if scale > 1:
                    scaled_width = width * scale
                    scaled_height = height * scale
                    svg_open_tag = re.sub(
                        r'width\s*=\s*"([0-9]+(?:\.[0-9]+)?)"',
                        f'width="{scaled_width:g}"',
                        svg_open_tag,
                        count=1,
                    )
                    svg_open_tag = re.sub(
                        r'height\s*=\s*"([0-9]+(?:\.[0-9]+)?)"',
                        f'height="{scaled_height:g}"',
                        svg_open_tag,
                        count=1,
                    )
                    normalized = f"{svg_open_tag}{normalized[svg_open_end + 1 :]}"

    normalized = _expand_svg_text_tspans(normalized)

    viewbox = _get_svg_viewbox(normalized)
    if viewbox is None:
        return normalized

    x, y, width, height = viewbox
    background = f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#FFFFFF" />'
    if "</defs>" in normalized:
        return normalized.replace("</defs>", f"</defs>\n{background}", 1)

    svg_open_end = normalized.find(">")
    if svg_open_end == -1:
        return normalized
    return f"{normalized[: svg_open_end + 1]}\n{background}{normalized[svg_open_end + 1 :]}"


def _expand_svg_text_tspans(svg_text: str) -> str:
    def _replace_text(match: re.Match[str]) -> str:
        text_attrs = match.group(1)
        inner = match.group(2)

        y_match = re.search(r'\sy\s*=\s*"([0-9.+-]+)"', text_attrs)
        if y_match is None:
            return match.group(0)
        try:
            baseline_y = float(y_match.group(1))
        except ValueError:
            return match.group(0)

        tspan_matches = list(re.finditer(r"<tspan\b([^>]*)>(.*?)</tspan>", inner, flags=re.S))
        if len(tspan_matches) < 2:
            return match.group(0)
        if not any(re.search(r'\sdy\s*=\s*"([0-9.+-]+)"', tspan.group(1)) for tspan in tspan_matches):
            return match.group(0)

        base_x_match = re.search(r'\sx\s*=\s*"([0-9.+-]+)"', text_attrs)
        default_x = base_x_match.group(1) if base_x_match is not None else None
        common_attrs = re.sub(r'\s[xy]\s*=\s*"[^\"]*"', "", text_attrs)

        current_y = baseline_y
        line_texts: list[str] = []
        for tspan in tspan_matches:
            tspan_attrs = tspan.group(1)
            content = tspan.group(2)

            dy_match = re.search(r'\sdy\s*=\s*"([0-9.+-]+)"', tspan_attrs)
            if dy_match is not None:
                with contextlib.suppress(ValueError):
                    current_y += float(dy_match.group(1))

            x_match = re.search(r'\sx\s*=\s*"([0-9.+-]+)"', tspan_attrs)
            x_value = x_match.group(1) if x_match is not None else default_x

            cleaned_tspan_attrs = re.sub(r'\s(?:x|y|dy)\s*=\s*"[^\"]*"', "", tspan_attrs)
            x_attr = f' x="{x_value}"' if x_value is not None else ""
            line_texts.append(f'<text{common_attrs}{cleaned_tspan_attrs}{x_attr} y="{current_y:g}">{content}</text>')

        return "".join(line_texts)

    return re.sub(r"<text([^>]*)>(.*?)</text>", _replace_text, svg_text, flags=re.S)


def _convert_to_png(path: Path) -> bytes | None:
    """Convert image to PNG using sips (macOS) or convert (ImageMagick)."""
    if path.suffix.lower() == ".svg":
        svg_text = path.read_text(encoding="utf-8", errors="ignore")
        svg_viewbox = _get_svg_viewbox(svg_text)
        normalized_svg = _normalize_svg_for_sips(svg_text)

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                result = subprocess.run(
                    ["qlmanage", "-t", "-s", "1024", "-o", tmp_dir, str(path)],
                    capture_output=True,
                )
            except FileNotFoundError:
                result = None
            if result is not None and result.returncode == 0:
                ql_output = Path(tmp_dir) / f"{path.name}.png"
                if ql_output.exists():
                    ql_data = ql_output.read_bytes()
                    if not _svg_thumb_likely_cropped(svg_viewbox, _get_png_dimensions(ql_data)):
                        return ql_data

        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", encoding="utf-8", delete=True) as svg_tmp:
            svg_tmp.write(normalized_svg)
            svg_tmp.flush()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
                tmp_path = tmp.name
                result = subprocess.run(
                    ["sips", "-s", "format", "png", svg_tmp.name, "--out", tmp_path],
                    capture_output=True,
                )
                if result.returncode == 0:
                    return Path(tmp_path).read_bytes()
                result = subprocess.run(
                    ["convert", svg_tmp.name, tmp_path],
                    capture_output=True,
                )
                if result.returncode == 0:
                    return Path(tmp_path).read_bytes()
        return None

    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
        tmp_path = tmp.name
        # Try sips first (macOS built-in)
        result = subprocess.run(
            ["sips", "-s", "format", "png", str(path), "--out", tmp_path],
            capture_output=True,
        )
        if result.returncode == 0:
            return Path(tmp_path).read_bytes()
        # Fallback to ImageMagick convert
        result = subprocess.run(
            ["convert", str(path), tmp_path],
            capture_output=True,
        )
        if result.returncode == 0:
            return Path(tmp_path).read_bytes()
    return None


def print_kitty_image(file_path: str | Path, *, file: IO[str] | None = None) -> None:
    """Print an image to the terminal using Kitty graphics protocol.

    Only specifies column width; Kitty auto-scales height to preserve aspect ratio.
    """
    path = Path(file_path) if isinstance(file_path, str) else file_path
    if not path.exists():
        print(f"Image not found: {path}", file=file or sys.stdout, flush=True)
        return

    try:
        source_data = path.read_bytes()

        # Some producers may write PNG bytes with a non-PNG extension (e.g. .svg).
        # If the file is already PNG, render it directly without conversion.
        if _get_png_dimensions(source_data) is not None:
            data = source_data
        elif path.suffix.lower() in _NEEDS_CONVERSION:
            data = _convert_to_png(path)
            if data is None:
                print(f"Saved image: {path}", file=file or sys.stdout, flush=True)
                return
        else:
            data = source_data

        encoded = base64.standard_b64encode(data).decode("ascii")
        out = file or sys.stdout

        term_size = shutil.get_terminal_size()
        target_cols = min(_MAX_COLS, term_size.columns)

        size_param = ""
        dimensions = _get_png_dimensions(data)
        if dimensions is not None:
            img_width, img_height = dimensions
            img_cols = max(img_width // _PIXELS_PER_COL, 1)
            img_rows = max(img_height // _PIXELS_PER_ROW, 1)
            exceeds_width = img_cols > target_cols
            exceeds_height = img_rows > _MAX_ROWS
            if exceeds_width and exceeds_height:
                # Both exceed: use the more constrained dimension to preserve aspect ratio
                width_scale = target_cols / img_cols
                height_scale = _MAX_ROWS / img_rows
                size_param = f"c={target_cols}" if width_scale < height_scale else f"r={_MAX_ROWS}"
            elif exceeds_width:
                size_param = f"c={target_cols}"
            elif exceeds_height:
                size_param = "" if img_rows <= _MAX_TALL_ROWS else f"r={_MAX_ROWS}"

            if not size_param and exceeds_height and img_cols < _MIN_READABLE_COLS:
                readable_cols = min(_MIN_READABLE_COLS, target_cols)
                rows_if_readable = (img_rows * readable_cols + img_cols - 1) // img_cols
                if rows_if_readable <= _MAX_TALL_ROWS:
                    size_param = f"c={readable_cols}"

            if size_param.startswith("r="):
                constrained_rows = int(size_param[2:])
                constrained_cols = img_cols * constrained_rows / img_rows
                if constrained_cols < _MIN_READABLE_COLS:
                    required_rows = (_MIN_READABLE_COLS * img_rows + img_cols - 1) // img_cols
                    boosted_rows = min(max(constrained_rows, required_rows), _MAX_TALL_ROWS)
                    if exceeds_width:
                        rows_if_width_constrained = (img_rows * target_cols + img_cols - 1) // img_cols
                        if rows_if_width_constrained <= _MAX_TALL_ROWS:
                            size_param = f"c={target_cols}"
                        else:
                            size_param = f"r={boosted_rows}"
                    elif img_rows <= boosted_rows:
                        size_param = ""
                    else:
                        size_param = f"r={boosted_rows}"
        else:
            # Fallback: constrain by height since we can't determine image size
            size_param = f"r={_MAX_ROWS}"
        print("", file=out)
        _write_kitty_graphics(out, encoded, size_param=size_param)
        print("", file=out)
        out.flush()
    except Exception:
        print(f"Saved image: {path}", file=file or sys.stdout, flush=True)


def _write_kitty_graphics(out: IO[str], encoded_data: str, *, size_param: str) -> None:
    """Write Kitty graphics protocol escape sequences.

    Protocol format: ESC _ G <control>;<payload> ESC \\
    - a=T: direct transmission (data in payload)
    - f=100: PNG format (auto-detected by Kitty)
    - c=N: display width in columns
    - r=N: display height in rows
    - m=1: more data follows, m=0: last chunk
    """
    total_len = len(encoded_data)

    for i in range(0, total_len, _CHUNK_SIZE):
        chunk = encoded_data[i : i + _CHUNK_SIZE]
        is_last = i + _CHUNK_SIZE >= total_len

        if i == 0:
            # First chunk: include control parameters
            base_ctrl = f"a=T,f=100,{size_param}" if size_param else "a=T,f=100"
            ctrl = f"{base_ctrl},m={0 if is_last else 1}"
            out.write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            # Subsequent chunks: only m parameter needed
            out.write(f"\033_Gm={0 if is_last else 1};{chunk}\033\\")
