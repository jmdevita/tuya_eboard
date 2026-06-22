"""Pure DP (datapoint) codec — no BLE, no crypto, fully unit-testable.

This decodes/encodes the *application* payload that sits inside an already
decrypted Tuya BLE frame: a flat stream of datapoints. It mirrors exactly what
the vendored ``TuyaBLEDevice._parse_datapoints_v3`` does on the wire, so frames
captured in Phase 0 round-trip through here.

Wire format per datapoint::

    +------+------+--------------+------------------+
    | id   | type |    length    | value (length B) |
    | 1 B  | 1 B  | 1 B (v3)     |       N B        |
    |      |      | 2 B (v4, BE) |                  |
    +------+------+--------------+------------------+

The length field width depends on the Tuya BLE protocol generation: **v3 uses 1
byte, v4 uses 2 bytes** (big-endian). Pass ``length_bytes=1`` for v3 or ``2`` for
v4 (the default — modern Tuya boards are v4). Multibyte values are big-endian
throughout; a ``value`` DP is whatever width the device sends, decoded big-endian
signed. Mirrors the vendored ``_parse_datapoints_v3`` / ``_parse_datapoints_v4``.

NOTE: the design doc's §3.3 described a 2-byte length + fixed 4-byte values —
that's the Tuya *MCU serial* protocol, a different layer; the BLE DP stream is as
drawn above.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class DataPointType(IntEnum):
    RAW = 0
    BOOL = 1
    VALUE = 2
    STRING = 3
    ENUM = 4
    BITMAP = 5


DecodedValue = bytes | bool | int | str


@dataclass(frozen=True)
class DataPoint:
    id: int
    type: DataPointType
    raw: bytes  # exact bytes on the wire (for fixtures / lossless re-encode)
    value: DecodedValue  # decoded per type

    def __repr__(self) -> str:  # compact, capture-log friendly
        return (
            f"DP(id={self.id}, type={self.type.name}, "
            f"value={self.value!r}, raw={self.raw.hex()})"
        )


def decode_value(dp_type: DataPointType, raw: bytes) -> DecodedValue:
    """Decode a single DP value per its type. Inverse of :func:`encode_value`."""
    match dp_type:
        case DataPointType.RAW | DataPointType.BITMAP:
            return raw
        case DataPointType.BOOL:
            return int.from_bytes(raw, "big") != 0
        case DataPointType.VALUE | DataPointType.ENUM:
            return int.from_bytes(raw, "big", signed=True)
        case DataPointType.STRING:
            return raw.decode()
    raise ValueError(f"Unknown DP type: {dp_type!r}")


def encode_value(dp_type: DataPointType, value: DecodedValue, width: int = 4) -> bytes:
    """Encode a value to wire bytes. ``width`` only applies to VALUE/ENUM ints."""
    match dp_type:
        case DataPointType.RAW | DataPointType.BITMAP:
            if not isinstance(value, (bytes, bytearray)):
                raise TypeError("RAW/BITMAP value must be bytes")
            return bytes(value)
        case DataPointType.BOOL:
            return b"\x01" if value else b"\x00"
        case DataPointType.VALUE | DataPointType.ENUM:
            return int(value).to_bytes(width, "big", signed=True)
        case DataPointType.STRING:
            return str(value).encode()
    raise ValueError(f"Unknown DP type: {dp_type!r}")


def decode_datapoints(
    data: bytes, start_pos: int = 0, length_bytes: int = 2
) -> list[DataPoint]:
    """Decode a flat DP stream (``length_bytes``: 1 for v3, 2 for v4).

    Stops when fewer than one full DP header (2 + ``length_bytes``) remains,
    matching the device's own loop guard.
    """
    if length_bytes not in (1, 2):
        raise ValueError("length_bytes must be 1 (v3) or 2 (v4)")
    header = 2 + length_bytes
    out: list[DataPoint] = []
    pos = start_pos
    while len(data) - pos >= header:
        dp_id = data[pos]
        raw_type = data[pos + 1]
        if raw_type > DataPointType.BITMAP:
            raise ValueError(f"Invalid DP type byte {raw_type} at pos {pos + 1}")
        length = int.from_bytes(data[pos + 2:pos + 2 + length_bytes], "big")
        value_start = pos + header
        value_end = value_start + length
        if value_end > len(data):
            raise ValueError(
                f"DP {dp_id} claims length {length} but only "
                f"{len(data) - value_start} bytes remain"
            )
        dp_type = DataPointType(raw_type)
        raw = data[value_start:value_end]
        out.append(DataPoint(dp_id, dp_type, raw, decode_value(dp_type, raw)))
        pos = value_end
    return out


def encode_datapoints(datapoints: list[DataPoint], length_bytes: int = 2) -> bytes:
    """Encode DPs back to wire bytes. Round-trips :func:`decode_datapoints`."""
    if length_bytes not in (1, 2):
        raise ValueError("length_bytes must be 1 (v3) or 2 (v4)")
    cap = (1 << (8 * length_bytes)) - 1
    buf = bytearray()
    for dp in datapoints:
        if len(dp.raw) > cap:
            raise ValueError(
                f"DP {dp.id} value too long for {length_bytes}-byte length field"
            )
        buf.append(dp.id)
        buf.append(int(dp.type))
        buf += len(dp.raw).to_bytes(length_bytes, "big")
        buf += dp.raw
    return bytes(buf)
