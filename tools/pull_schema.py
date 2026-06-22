"""Pull the Tuya Cloud 'Things Data Model' (DP id -> code/type/scale/unit) for
the device, to compare deterministic cloud labels against our hand-mapped DPs.
Cloud call only - no board needed."""

import json
from pathlib import Path

import tinytuya

cfg = json.loads(Path("tinytuya.json").read_text())
DEVICE_ID = cfg["apiDeviceID"]

c = tinytuya.Cloud(
    apiRegion=cfg["apiRegion"],
    apiKey=cfg["apiKey"],
    apiSecret=cfg["apiSecret"],
    apiDeviceID=DEVICE_ID,
)

print(f"# device {DEVICE_ID}\n")

for name, fn in (("getdps", c.getdps), ("getproperties", c.getproperties)):
    print(f"================ {name}() ================")
    try:
        result = fn(DEVICE_ID)
        print(json.dumps(result, indent=2)[:6000])
    except Exception as exc:
        print(f"error: {exc!r}")
    print()
