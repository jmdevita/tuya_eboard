"""tuya-eboard CLI — iterate the DP map straight against the board, no HA involved.

    python tools/cli.py dump                 # one connect, print all DPs
    python tools/cli.py dump --save captures # also freeze a fixture
    python tools/cli.py watch --interval 30  # re-dump on an interval

Reads credentials from ./devices.json (tinytuya wizard output).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# The library is vendored inside the integration; put it on the path so this dev
# script can import it (same pattern as the other tools/).
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "custom_components" / "tuya_eboard"),
)
from tuya_eboard_ble.credentials import load_credentials  # noqa: E402
from tuya_eboard_ble.device import TuyaEboardDevice, discover_board  # noqa: E402
from tuya_eboard_ble.protocol import DataPoint, encode_datapoints  # noqa: E402


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _print_dps(dps: list[DataPoint]) -> None:
    if not dps:
        print("  (no datapoints reported — board may need a moment, or try a "
              "longer --settle)")
        return
    print(f"  {'id':>3}  {'type':<7}  {'value':<24}  raw")
    print(f"  {'-'*3}  {'-'*7}  {'-'*24}  {'-'*16}")
    for dp in dps:
        val = repr(dp.value)
        if len(val) > 24:
            val = val[:21] + "..."
        print(f"  {dp.id:>3}  {dp.type.name:<7}  {val:<24}  {dp.raw.hex()}")


def _save_fixture(
    dps: list[DataPoint], outdir: Path, device_id: str, label: str | None = None
) -> Path:
    """Freeze the DP stream as a Phase-0 fixture for protocol round-trip tests."""
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = _ts().replace(":", "").replace("-", "")
    tag = f"_{label}" if label else ""
    path = outdir / f"dp_dump_{device_id}{tag}_{stamp}.json"
    payload = {
        "captured_at": _ts(),
        "device_id": device_id,
        "label": label,
        "dp_length_bytes": 2,  # Tuya BLE v4 wire format
        "dp_stream_hex": encode_datapoints(dps, length_bytes=2).hex(),
        "datapoints": [
            {"id": d.id, "type": d.type.name, "value": _jsonable(d.value),
             "raw": d.raw.hex()}
            for d in dps
        ],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def _jsonable(value: object) -> object:
    return value.hex() if isinstance(value, (bytes, bytearray)) else value


async def _connect(args) -> TuyaEboardDevice:
    creds = load_credentials(getattr(args, "device_id", None))
    print(f"[{_ts()}] discovering {creds.product_name or creds.product_id} ...")
    ble_device, adv = await discover_board(creds, mac=args.mac, timeout=args.timeout)
    print(f"[{_ts()}] found {ble_device.address} (rssi={adv.rssi})")
    return TuyaEboardDevice(creds, ble_device, adv, read_only=True)


async def cmd_dump(args) -> None:
    dev = await _connect(args)
    print(f"[{_ts()}] connecting + reading DPs (settle {args.settle}s) ...")
    dps = await dev.read_all_dps(settle=args.settle)
    print(f"[{_ts()}] {len(dps)} datapoint(s):")
    _print_dps(dps)
    if args.save:
        path = _save_fixture(dps, Path(args.save), dev.inner.device_id,
                             getattr(args, "label", None))
        print(f"[{_ts()}] fixture saved -> {path}")


async def cmd_watch(args) -> None:
    while True:
        try:
            dev = await _connect(args)
            dps = await dev.read_all_dps(settle=args.settle)
            print(f"[{_ts()}] {len(dps)} datapoint(s):")
            _print_dps(dps)
            if args.save:
                path = _save_fixture(dps, Path(args.save), dev.inner.device_id,
                                     getattr(args, "label", None))
                print(f"[{_ts()}] fixture saved -> {path}")
        except Exception as exc:  # keep the loop alive across transient BLE errors
            print(f"[{_ts()}] error: {exc!r}")
        print(f"[{_ts()}] sleeping {args.interval}s ...\n")
        await asyncio.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    # Shared options live on a parent parser so they work in EITHER position,
    # e.g. both `tuya-eboard dump --settle 6` and `tuya-eboard --settle 6 dump`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--device-id", help="device id (if devices.json has several)")
    common.add_argument("--mac", default=None,
                        help="board MAC to match (Linux only; ignored on macOS). "
                             "If omitted, matches by Tuya BLE service UUID.")
    common.add_argument("--timeout", type=float, default=15.0, help="scan timeout (s)")
    common.add_argument("--settle", type=float, default=4.0,
                        help="seconds to collect proactive DP reports after connect")
    common.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    p = argparse.ArgumentParser(prog="tuya-eboard", description=__doc__, parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dump", parents=[common], help="one connect, print all DPs")
    d.add_argument("--save", metavar="DIR", help="also freeze a fixture into DIR")
    d.add_argument("--label", help="state tag saved with the capture "
                   "(e.g. 'after-ride', 'after-charge', 'eco-mode')")
    d.set_defaults(func=cmd_dump)

    w = sub.add_parser("watch", parents=[common], help="re-dump on an interval")
    w.add_argument("--interval", type=float, default=60.0, help="seconds between dumps")
    w.add_argument("--save", metavar="DIR", help="freeze a fixture each interval")
    w.add_argument("--label", help="state tag saved with each capture")
    w.set_defaults(func=cmd_watch)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
