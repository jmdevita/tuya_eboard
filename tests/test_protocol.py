"""Pure DP codec tests - no BLE, no hardware. Run: pytest -q

Once you capture real DP dumps with `python tools/cli.py dump --save tests/fixtures`,
the `test_real_fixtures_roundtrip` test will pick them up automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuya_eboard_ble.protocol import (
    DataPoint,
    DataPointType,
    decode_datapoints,
    decode_value,
    encode_datapoints,
    encode_value,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("lb", [1, 2])
def test_value_dp_is_big_endian_signed(lb):
    # id=1, type=VALUE(2), len(lb bytes)=4, value=0x000004D2 = 1234
    raw = bytes.fromhex("0102") + (4).to_bytes(lb, "big") + bytes.fromhex("000004D2")
    dps = decode_datapoints(raw, length_bytes=lb)
    assert len(dps) == 1
    assert dps[0].id == 1
    assert dps[0].type is DataPointType.VALUE
    assert dps[0].value == 1234


def test_value_dp_negative():
    assert decode_value(DataPointType.VALUE, bytes.fromhex("FFFFFFFF")) == -1


def test_bool_enum_string_raw():
    assert decode_value(DataPointType.BOOL, b"\x01") is True
    assert decode_value(DataPointType.BOOL, b"\x00") is False
    assert decode_value(DataPointType.ENUM, b"\x03") == 3
    assert decode_value(DataPointType.STRING, b"hi") == "hi"
    assert decode_value(DataPointType.RAW, b"\xde\xad") == b"\xde\xad"


def test_v3_and_v4_length_field_widths_differ():
    """Same DP, different wire width: v3 length is 1 byte, v4 is 2 (big-endian)."""
    dp = [DataPoint(5, DataPointType.VALUE, b"\x00\x2a", 42)]
    assert encode_datapoints(dp, length_bytes=1) == bytes.fromhex("0502" "02" "002a")
    assert encode_datapoints(dp, length_bytes=2) == bytes.fromhex("0502" "0002" "002a")


@pytest.mark.parametrize("lb", [1, 2])
def test_multiple_datapoints_in_one_stream(lb):
    dps_in = [
        DataPoint(1, DataPointType.BOOL, b"\x01", True),
        DataPoint(2, DataPointType.VALUE, b"\x00\x00\x00\x0a", 10),
        DataPoint(3, DataPointType.ENUM, b"\x02", 2),
    ]
    dps = decode_datapoints(encode_datapoints(dps_in, lb), length_bytes=lb)
    assert [d.id for d in dps] == [1, 2, 3]
    assert dps[0].value is True
    assert dps[1].value == 10
    assert dps[2].value == 2


@pytest.mark.parametrize("lb", [1, 2])
def test_roundtrip_encode_decode(lb):
    dps = [
        DataPoint(1, DataPointType.BOOL, b"\x01", True),
        DataPoint(2, DataPointType.VALUE, b"\x00\x00\x04\xd2", 1234),
        DataPoint(7, DataPointType.STRING, b"v1.2", "v1.2"),
        DataPoint(9, DataPointType.RAW, b"\xca\xfe", b"\xca\xfe"),
    ]
    again = decode_datapoints(encode_datapoints(dps, lb), length_bytes=lb)
    assert [(d.id, d.type, d.raw, d.value) for d in again] == [
        (d.id, d.type, d.raw, d.value) for d in dps
    ]


def test_encode_value_roundtrips_each_type():
    for t, v in [
        (DataPointType.BOOL, True),
        (DataPointType.VALUE, -12345),
        (DataPointType.ENUM, 4),
        (DataPointType.STRING, "hello"),
        (DataPointType.RAW, b"\x00\xff"),
        (DataPointType.BITMAP, b"\x0f"),
    ]:
        assert decode_value(t, encode_value(t, v)) == v


@pytest.mark.parametrize("lb", [1, 2])
def test_truncated_stream_raises(lb):
    # dp claims 4 value bytes but only 2 present
    bad = bytes.fromhex("0102") + (4).to_bytes(lb, "big") + bytes.fromhex("0000")
    with pytest.raises(ValueError):
        decode_datapoints(bad, length_bytes=lb)


@pytest.mark.parametrize("lb", [1, 2])
def test_invalid_type_byte_raises(lb):
    bad = bytes.fromhex("0106") + (1).to_bytes(lb, "big") + b"\x00"  # type 6 > BITMAP
    with pytest.raises(ValueError):
        decode_datapoints(bad, length_bytes=lb)


@pytest.mark.parametrize("lb", [1, 2])
def test_trailing_partial_header_ignored(lb):
    # one valid DP + a stray byte too short to be a header; stops cleanly
    stream = encode_datapoints([DataPoint(1, DataPointType.BOOL, b"\x01", True)], lb)
    dps = decode_datapoints(stream + b"\xff", length_bytes=lb)
    assert len(dps) == 1


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("dp_dump_*.json")) if FIXTURES.exists() else [])
def test_real_fixtures_roundtrip(fixture):
    """Captured real DP streams must decode and re-encode identically."""
    data = json.loads(Path(fixture).read_text())
    lb = data.get("dp_length_bytes", 2)  # v4 default
    stream = bytes.fromhex(data["dp_stream_hex"])
    dps = decode_datapoints(stream, length_bytes=lb)
    assert encode_datapoints(dps, length_bytes=lb) == stream
    assert len(dps) == len(data["datapoints"])
