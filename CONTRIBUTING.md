# Contributing / developer guide

Internals, the per-board mapping workflow, and the dev CLI. For install/usage see the
[README](README.md).

## Design: process = code, mapping = data

The process is identical for every Tuya board (BLE transport, the Tuya handshake +
session crypto, DP framing, pulling the cloud data model, the dump → classify → correlate
flow, the write-safety gate) and is written once as **shared code**. What *varies* per
board is the DP mapping (which DP is voltage vs odometer, the scales, the enum meanings),
so that lives as **data, one YAML file per `product_id`** in `dpmaps/`.

```
ENGINE (shared code)                 MAPS (data, per product_id)
  transport / session / framing        dpmaps/qdbj2py2.yaml    <- OMW Hussar
  cloud data-model pull (getdps)       dpmaps/<other_pid>.yaml <- next board
  dump / classify / correlate          ...
  write-safety gate
```

Onboarding a new board adds a YAML map file, not new code. Boards sharing the same
Hobbywing/Tuya firmware may share a `product_id` and reuse a map as-is.

> "Same process" holds for **Tuya** BLE devices. The cloud data model is pulled the same
> way for any of them, but its output is per-product and often omits vendor-custom DPs
> (those still need hands-on correlation). Non-Tuya boards are a different problem.

## How a board gets mapped

1. **Cloud data model first (deterministic).** `getdps(product_id)` returns each declared
   DP's `code` / `type` / `unit` / `scale`. This labels the standard DPs with zero
   guessing. (`tools/pull_schema.py`)
2. **Correlation for the rest.** Vendor-custom DPs the cloud omits (e.g. the Hussar's
   101-120 ride-tuning block) are decoded by changing one real-world variable at a time
   and diffing snapshots (`tools/correlate.py`).
3. **Record** confirmed DPs into `dpmaps/<product_id>.yaml`.
4. **Writes stay gated** until a config DP is confirmed *and* given a safe range.

## Layout

```
custom_components/tuya_eboard/    the HACS integration (config flow, coordinator, entities)
  tuya_eboard_ble/                the board-agnostic library - the "engine":
    _vendor/tuya_ble/   borrowed Tuya BLE protocol (handshake, session key, AES),
                        locally patched for Tuya BLE v4 / 0xFD50
    credentials.py      load device id/local_key/uuid from tinytuya devices.json
    protocol.py         pure DP codec (v3 + v4 length widths) - unit-tested
    device.py           discover_board(), read_all_dps(), write_dp() + safety gate
    dpmaps/             per-product DP maps, selected by product_id (the "data")
tools/
  cli.py              dev CLI: dump|watch (capture DP fixtures from a board)
  pull_schema.py      pull the Tuya cloud data model (DP codes/units/scales)
  correlate.py        diff two DP dumps to map ids -> meaning
  scan.py gatt.py diag.py   BLE bring-up + diagnostics
tests/                pure protocol round-trip tests (no hardware)
```

The library ships **inside** the integration. Tests import it as `tuya_eboard_ble` via a
root `conftest.py` that puts `custom_components/tuya_eboard/` on the path.

## Protocol generations (v4 stable · v3 beta)

The engine auto-detects the protocol generation from the advertised service and selects
the right GATT characteristics + device-info handshake (`detect_generation` in
`_vendor/tuya_ble/const.py`):

| Gen | Service | Chars | device-info | DP length | Status |
|-----|---------|-------|-------------|-----------|--------|
| **v4** | `0xFD50` | `…07d0` | `[0x00,0xF3]` | 2 bytes | verified (HW7009/Hussar) |
| **v3** | `0xA201` | `0x2b10/0x2b11` | empty | 1 byte | **beta - untested** |

v3 code paths exist (it's what upstream `ha_tuya_ble` targets, and our additions are
additive) but are **not** verified against real v2/v3 hardware - connecting logs a beta
warning. v2 may have further quirks (security flags, session-key derivation).

## Dev setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt
# one-time cloud fetch -> writes devices.json (local key) + DP mappings
python -m tinytuya wizard      # answer Y to "Download DP Name mappings"
```

`devices.json` / `tinytuya.json` (secrets) are gitignored - never commit them.

## Capturing from a board (powered on, in range, phone app closed)

```bash
python tools/scan.py                             # confirm BLE reachability (0xFD50)
python tools/pull_schema.py                      # pull cloud DP codes/units/scales
python tools/cli.py dump --save captures --label baseline
python tools/cli.py dump --save captures --label after-charge
python tools/correlate.py captures/A.json captures/B.json   # diff to map custom DPs
```

## Tests

```bash
python -m pytest -q        # pure, no hardware
```

## Safety model

DP *sending* is not yet implemented for Tuya BLE v4 (the vendored protocol only sends v3
frames, with a 1-byte length that's wrong for v4), so `write_dp()` raises
`NotImplementedError` on v4 rather than emit a malformed frame to a motor controller.

Even once v4 sending is added, writes stay gated by independent checks: `read_only=True`
by default, the DP must be on `WRITE_ALLOWLIST` in `device.py` (empty until a config DP is
confirmed *and* given a `safe_range`), and the value must be in range. A motor ESC is not
a light bulb; the official app is always the recovery path.

## Status

- [x] Credentials + cloud data model (`getdps`) for the Hussar
- [x] Tuya BLE **v4** transport/handshake working (vendored + patched)
- [x] Pure DP codec + tests, CLI, connect-on-demand, write-safety gate
- [x] Hussar DP map: standard DPs confirmed (voltage, odometer, battery %, mode…)
- [x] Per-product registry layout + loader (`dpmaps/<product_id>.yaml`)
- [x] Auto-detect protocol generation (v4 stable; v3 beta/untested)
- [x] HACS integration: config flow, advertisement-triggered coordinator, read-only sensors
- [ ] Load-test the integration on real HA hardware / Bluetooth proxy
- [ ] Decode the custom 101-120 config block via correlation
- [ ] Verify v3 against real hardware (promote out of beta)
