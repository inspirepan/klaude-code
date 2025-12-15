"""Rich rendering utilities.

This package installs a small monkey-patch that improves CJK line breaking in Rich.
"""

from __future__ import annotations

from .cjk_wrap import install_rich_cjk_wrap_patch

install_rich_cjk_wrap_patch()
