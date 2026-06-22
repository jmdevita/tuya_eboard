"""Handshake probe: does the board answer the device-info request, and under
which protocol version / write type?

Sends FUN_SENDER_DEVICE_INFO (the first handshake packet) encrypted with the
login key, trying protocol versions 2/3/4 and both write types, printing any
raw notification the board sends back. Pure diagnosis — no DP writes.

  silence on all  -> request malformed for this firmware (key? security flag?)
  bytes on one    -> that's our protocol version; parser is next
"""

import asyncio
import hashlib
import secrets
import sys
from pathlib import Path
from struct import pack

from bleak import BleakClient, BleakScanner
from Crypto.Cipher import AES

# Allow running as `python tools/diag.py` from the project root: the library is
# vendored inside the integration, so import it from there.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "custom_components" / "tuya_eboard"),
)
from tuya_eboard_ble.credentials import load_credentials  # noqa: E402

NOTIFY = "00000002-0000-1001-8001-00805f9b07d0"
WRITE = "00000001-0000-1001-8001-00805f9b07d0"


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte & 0xFF
        for _ in range(8):
            tmp = crc & 1
            crc >>= 1
            if tmp:
                crc ^= 0xA001
    return crc


def pack_int(value: int) -> bytearray:
    result = bytearray()
    while True:
        curr = value & 0x7F
        value >>= 7
        if value != 0:
            curr |= 0x80
        result += pack(">B", curr)
        if value == 0:
            break
    return result


def build_device_info(
    login_key: bytes, proto: int, seq: int = 1, data: bytes = b""
) -> list[bytes]:
    code = 0x0000  # FUN_SENDER_DEVICE_INFO
    iv = secrets.token_bytes(16)
    raw = bytearray()
    raw += pack(">IIHH", seq, 0, code, len(data))
    raw += data
    raw += pack(">H", crc16(raw))
    while len(raw) % 16 != 0:
        raw += b"\x00"
    encrypted = b"\x04" + iv + AES.new(login_key, AES.MODE_CBC, iv).encrypt(bytes(raw))

    packets = []
    pn = 0
    pos = 0
    length = len(encrypted)
    while pos < length:
        p = bytearray()
        p += pack_int(pn)
        if pn == 0:
            p += pack_int(length)
            p += pack(">B", proto << 4)
        chunk = encrypted[pos:pos + 20 - len(p)]
        p += chunk
        packets.append(bytes(p))
        pos += len(chunk)
        pn += 1
    return packets


async def _attempt(dev, login_key: bytes, proto: int, data: bytes) -> None:
    """Fresh connection, send device-info at one proto version, watch result."""
    received: list[bytes] = []
    dropped = asyncio.Event()

    def on_disconnect(_c) -> None:
        dropped.set()

    def handler(_sender, data: bytearray) -> None:
        received.append(bytes(data))
        print(f"    NOTIFY <- {bytes(data).hex()}")

    print(f"--- proto={proto}  data={data.hex() or '(empty)'}: connecting fresh ---")
    client = BleakClient(dev, disconnected_callback=on_disconnect)
    try:
        await client.connect()
        await client.start_notify(NOTIFY, handler)
        await asyncio.sleep(0.5)  # let any proactive report land before we send
        for pkt in build_device_info(login_key, proto, seq=1, data=data):
            await client.write_gatt_char(WRITE, pkt, response=False)
        # Watch for ~6s: did we get a reply, or get disconnected?
        for _ in range(12):
            if received or dropped.is_set():
                break
            await asyncio.sleep(0.5)
        if received:
            print(f"    => RESPONSE under proto={proto}  ({len(received)} frame(s))")
        elif dropped.is_set():
            print(f"    => board DISCONNECTED us (rejected proto={proto} frame)")
        else:
            print(f"    => silence, still connected (proto={proto} ignored)")
    except Exception as exc:
        print(f"    error: {exc!r}")
    finally:
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass
        await asyncio.sleep(1.0)


async def main() -> None:
    creds = load_credentials()
    login_key = hashlib.md5(creds.local_key[:6].encode()).digest()
    print(f"login_key derived from local_key[:6] = {creds.local_key[:6]!r}\n")

    # v4 firmware (modern Tuya boards) expects the device-info payload [0x00, 0xF3];
    # an empty payload makes it drop the link. Test the promising combos.
    combos = [
        (4, bytes([0x00, 0xF3])),
        (3, bytes([0x00, 0xF3])),
        (4, b""),
    ]
    for proto, data in combos:
        dev = await BleakScanner.find_device_by_filter(
            lambda d, a: any(
                f in u.lower()
                for u in (a.service_uuids or [])
                for f in ("a201", "fd50")
            ),
            timeout=15.0,
        )
        if dev is None:
            print(f"proto={proto}: board not found (free it from the phone?).")
            continue
        await _attempt(dev, login_key, proto, data)


if __name__ == "__main__":
    asyncio.run(main())
