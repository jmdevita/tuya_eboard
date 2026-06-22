"""Phase -1 reconnaissance: confirm a Tuya BLE board is reachable.

Reports any device advertising a Tuya service UUID (0xA201 legacy or 0xFD50
newer). No local key needed - pure GATT-layer discovery. Run with the board
powered on and in range.

Optional, to highlight a specific board:
    python tools/scan.py [NAME] [MAC]
With neither, every Tuya BLE advertiser is listed.
"""

import asyncio
import sys

from bleak import BleakScanner

TARGET_NAME = sys.argv[1] if len(sys.argv) > 1 else None
TARGET_MAC = sys.argv[2] if len(sys.argv) > 2 else None
# Older Tuya BLE devices advertise 0xA201; newer ones use 0xFD50.
TUYA_SERVICE_FRAGMENTS = ("a201", "fd50")


async def main() -> None:
    print("Scanning 12s for Tuya BLE devices (0xA201 / 0xFD50)...\n")
    found_tuya = False
    found_target = False

    devices = await BleakScanner.discover(timeout=12.0, return_adv=True)
    for address, (dev, adv) in devices.items():
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        is_tuya = any(frag in u for u in uuids for frag in TUYA_SERVICE_FRAGMENTS)
        is_named = bool(TARGET_NAME) and (dev.name or "").strip() == TARGET_NAME
        is_target = (
            bool(TARGET_MAC) and address.upper() == TARGET_MAC.upper()
        ) or is_named

        if is_target or is_tuya:
            tag = []
            if is_target:
                tag.append("<-- TARGET")
                found_target = True
            if is_tuya:
                tag.append("[Tuya service]")
                found_tuya = True
            print(f"{address}  rssi={adv.rssi:>4}  name={dev.name!r}  {' '.join(tag)}")
            if uuids:
                print(f"    service_uuids: {uuids}")

    print()
    if found_target or (TARGET_NAME is None and TARGET_MAC is None and found_tuya):
        print("OK: Tuya BLE device found. Next step is the session handshake.")
    else:
        print("No matching device found. Is it powered on / in range? "
              "macOS may also list it under a random address rather than its MAC.")


if __name__ == "__main__":
    asyncio.run(main())
