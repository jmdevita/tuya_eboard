"""Pytest bootstrap.

The library is vendored inside the integration (custom_components/tuya_eboard/), so
add that directory to sys.path to let tests import it by its short name,
``tuya_eboard_ble``, instead of the full custom_components path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "tuya_eboard"))
