"""Enumerate a board's real GATT table.

Newer Tuya boards (0xFD50) don't expose the classic 0x2b10/0x2b11 characteristics
the vendored protocol hardcodes. Connect once and list every service +
characteristic so we can identify the real notify/write pair and patch
tuya_eboard_ble/_vendor/tuya_ble/const.py.

Free the board from the phone first (force-quit the app / phone BT off).

Optional: `python tools/gatt.py [NAME]` to target a board by advertised name;
otherwise the first Tuya BLE advertiser is used.
"""

import asyncio
import sys

from bleak import BleakClient, BleakScanner

TARGET_NAME = sys.argv[1] if len(sys.argv) > 1 else None
TUYA_FRAGMENTS = ("a201", "fd50")


def _is_board(dev, adv) -> bool:
    if TARGET_NAME and (dev.name or "").strip() == TARGET_NAME:
        return True
    uuids = [u.lower() for u in (adv.service_uuids or [])]
    return any(frag in u for u in uuids for frag in TUYA_FRAGMENTS)


async def main() -> None:
    print("Scanning for the board ...")
    dev = await BleakScanner.find_device_by_filter(_is_board, timeout=15.0)
    if dev is None:
        print("Board not found. Powered on, in range, and not held by the phone?")
        return

    print(f"Connecting to {dev.address} ({dev.name!r}) ...\n")
    async with BleakClient(dev) as client:
        print(f"Connected: {client.is_connected}\n")
        notify_candidates = []
        write_candidates = []
        for service in client.services:
            print(f"[service] {service.uuid}  {service.description}")
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                print(f"    [char] {ch.uuid}  ({props})")
                if {"notify", "indicate"} & set(ch.properties):
                    notify_candidates.append(ch.uuid)
                if {"write", "write-without-response"} & set(ch.properties):
                    write_candidates.append(ch.uuid)
                for d in ch.descriptors:
                    print(f"        [desc] {d.uuid}")

        print("\n--- candidates ---")
        print("NOTIFY/INDICATE (device -> us):")
        for u in notify_candidates:
            print(f"    {u}")
        print("WRITE (us -> device):")
        for u in write_candidates:
            print(f"    {u}")


if __name__ == "__main__":
    asyncio.run(main())
