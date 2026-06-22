"""Load a per-product DP map (the 'data', one file per product_id).

For v1 the entity platforms hardcode transforms for the 11 confirmed DPs; this loader
supplies device metadata (a nicer model name) and is the seam for future board-agnostic,
registry-driven entities. See tuya_eboard_ble/dpmaps/<product_id>.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_DPMAPS_DIR = Path(__file__).parent / "tuya_eboard_ble" / "dpmaps"

# product_id is user-supplied in the config flow and used to build a filename, so
# constrain it to the Tuya id charset - no path separators / traversal.
_SAFE_PRODUCT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def load_dpmap(product_id: str | None) -> dict[str, Any]:
    """Return the parsed dpmap for ``product_id`` ({} if unknown/unsafe/missing)."""
    if not product_id or not _SAFE_PRODUCT_ID.match(product_id):
        return {}
    path = _DPMAPS_DIR / f"{product_id}.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def device_meta(product_id: str | None) -> dict[str, Any]:
    """Return the ``device:`` metadata block from the dpmap ({} if absent)."""
    return load_dpmap(product_id).get("device", {}) or {}
