# tuya-eboard - a Tuya BLE e-board client for Home Assistant

A connect-on-demand client for **Tuya BLE** electric-skateboard ESCs, built first
for the **OMW Hussar / Hobbywing HW7009** but structured to work with **any Tuya
BLE board**. It's a **snapshot + delta** integration, *not* live telemetry: the
board is only reachable over BLE when powered on and parked in range, so we
connect, read datapoints, disconnect, and derive per-ride stats from successive
snapshots.

## The core idea: process = code, mapping = data

The single most important design point:

- **The process is the same for every Tuya board** - BLE transport, the Tuya
  handshake + session crypto, DP framing, pulling the cloud data model, the
  dump→classify→correlate flow, and the write-safety gate. This is **shared code,
  written once.**
- **The DP mapping varies per board** - *which* DP is voltage vs odometer vs a
  config value, the scales, the enum meanings. This is **data, one file per
  product**, not code.

```
ENGINE (shared code)                 MAPS (data, per product_id)
  transport / session / framing        dpmaps/qdbj2py2.yaml   ← OMW Hussar
  cloud data-model pull (getdps)       dpmaps/<other_pid>.yaml ← next board
  dump / classify / correlate          ...
  write-safety gate
```

Onboarding a new board adds a **YAML map file, not new code**. Boards sharing the
same Hobbywing/Tuya firmware may even share a `product_id` and reuse a map as-is.

> **Scope, honestly:** "same process" holds for **Tuya** BLE devices. The cloud
> data model is pulled the same way for any of them, but its output is per-product
> and often omits vendor-custom DPs (so those still need hands-on correlation).
> Non-Tuya boards are a different problem entirely.

## How a board gets mapped

1. **Cloud data model first (deterministic).** `getdps(product_id)` returns each
   declared DP's `code` / `type` / `unit` / `scale`. This labels the standard DPs
   with zero guessing and is authoritative for what it describes. (`pull_schema.py`)
2. **Correlation for the rest.** Vendor-custom DPs the cloud omits (e.g. the
   Hussar's 101–120 ride-tuning block) are decoded by changing one real-world
   variable at a time and diffing snapshots (`tools/correlate.py`).
3. **Record** confirmed DPs into the product's `dpmaps/<product_id>.yaml`.
4. **Writes stay gated** until a config DP is confirmed *and* given a safe range.

## Layout

```
custom_components/tuya_eboard/    the HACS integration (config flow, coordinator, entities)
  tuya_eboard_ble/                the board-agnostic library - the "engine":
    _vendor/tuya_ble/   borrowed Tuya BLE protocol (handshake, session key, AES),
                        locally patched for Tuya BLE v4 / 0xFD50 (see below)
    credentials.py      load device id/local_key/uuid from tinytuya devices.json
    protocol.py         pure DP codec (v3 + v4 length widths) - unit-tested
    device.py           discover_board(), read_all_dps(), write_dp() + safety gate
    dpmaps/             per-product DP maps, selected by product_id (the "data")
      qdbj2py2.yaml       OMW Hussar / HW7009
tools/
  cli.py              dev CLI: dump|watch (capture DP fixtures from a board)
  pull_schema.py      pull the Tuya cloud data model (DP codes/units/scales)
  correlate.py        diff two DP dumps to map ids -> meaning
  scan.py gatt.py diag.py   BLE bring-up + diagnostics (reusable per board)
tests/                pure protocol round-trip tests (no hardware)
```

The library lives **inside** the integration (it ships with the HACS install). Tests
import it as `tuya_eboard_ble` via a root `conftest.py` that puts
`custom_components/tuya_eboard/` on the path.

## Protocol generations (v4 stable · v3 beta)

The engine **auto-detects the protocol generation** from the advertised service
and selects the right GATT characteristics + device-info handshake payload
(`detect_generation` in `_vendor/tuya_ble/const.py`):

| Gen | Service | Chars | device-info | DP length | Status |
|-----|---------|-------|-------------|-----------|--------|
| **v4** | `0xFD50` | `…07d0` | `[0x00,0xF3]` | 2 bytes | verified (HW7009/Hussar) |
| **v3** | `0xA201` | `0x2b10/0x2b11` | empty | 1 byte | **beta - untested** |

> **v3 is beta.** The code paths exist (v3 is what upstream `ha_tuya_ble` targets,
> and our additions are additive), but we have **not** verified them against real
> v2/v3 hardware. Connecting to a v3 board logs a beta warning. v2 may have further
> quirks (security flags, session-key derivation) and is unverified.

The per-board **mapping** layer is already data (`dpmaps/`), so "board-agnostic"
now means: same engine, generation auto-selected, one YAML per product.

## Home Assistant integration (HACS)

A custom integration lives in [`custom_components/tuya_eboard/`](custom_components/tuya_eboard/)
- a standalone, HACS-installable component (the only HA project with **Tuya BLE v4 / 0xFD50**
support).

- **Install:** add this repo as a HACS *custom repository* (category: Integration), install,
  restart HA.
- **Add the board:** power it on (remote awake, in range) → HA auto-discovers it over Bluetooth
  → **log in with your Tuya IoT cloud credentials and pick your board** - the local key is pulled
  automatically (see the official [Tuya integration docs](https://www.home-assistant.io/integrations/tuya/)
  for creating a project + getting the Access ID/Secret). Manual key entry is available as an
  advanced fallback. Credentials are verified by one real connect+read before the entry is
  created, and a rotated key (after re-pairing) is refreshed automatically via reauth.
- **What you get:** read-only `sensor`/`binary_sensor` entities - battery %, voltage, odometer,
  trip distance/time, speed mode, cruise, BLE lock, `present`, and `last_seen`.

It's **connect-on-demand**: the board is only reachable when on + remote awake, so HA reads
opportunistically (advertisement-triggered) and shows last-known values with a `last_seen`
timestamp. "Last seen 2 h ago" is normal, not an error. The board stays **strictly read-only**.

## Setup (library / dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt
# one-time cloud fetch -> writes devices.json (local key) + can write DP mappings
python -m tinytuya wizard      # answer Y to "Download DP Name mappings"
```

`devices.json` / `tinytuya.json` (secrets) are gitignored - never commit them.

## Use (board powered on, in range, phone app closed)

```bash
python tools/scan.py                             # confirm BLE reachability (0xFD50)
python tools/pull_schema.py                      # pull cloud DP codes/units/scales
python tools/cli.py dump --save captures --label baseline
python tools/cli.py dump --save captures --label after-charge
python tools/correlate.py captures/A.json captures/B.json   # diff to map custom DPs
```

## Safety

**The integration is effectively read-only today.** DP *sending* is not yet
implemented for Tuya BLE v4 (the vendored protocol only sends v3 frames, with a
1-byte length that's wrong for v4), so `write_dp()` raises `NotImplementedError`
on v4 rather than emit a malformed frame to a motor controller.

Even once v4 sending is added, writes stay gated by several independent checks:
`read_only=True` by default, the DP must be on `WRITE_ALLOWLIST` in `device.py`
(empty until a config DP is confirmed *and* given a `safe_range`), and the value
must be in range. A motor ESC is not a light bulb; the official app is always the
recovery path.

## Status

- [x] Credentials + cloud data model (`getdps`) for the Hussar
- [x] Tuya BLE **v4** transport/handshake working (vendored + patched)
- [x] Pure DP codec + tests, CLI, connect-on-demand, write-safety gate
- [x] Hussar DP map: standard DPs confirmed (voltage, odometer, battery %, mode…)
- [x] Per-product registry layout + loader (`dpmaps/<product_id>.yaml`)
- [x] Auto-detect protocol generation (v4 stable; v3 beta/untested)
- [x] HACS integration: config flow, advertisement-triggered coordinator, read-only sensors
- [ ] Load-test the integration on real HA hardware / Bluetooth proxy
- [ ] Decode the custom 101–120 config block via correlation
- [ ] Verify v3 against real hardware (promote out of beta)

## Tests

```bash
python -m pytest -q        # pure, no hardware
```

## License

This project is licensed under the **GNU GPL v3.0** - see [`LICENSE`](LICENSE).

It vendors the Tuya BLE transport from
[PlusPlus-ua/ha_tuya_ble](https://github.com/PlusPlus-ua/ha_tuya_ble) (**MIT**,
© 2023 PlusPlus-ua), patched here for Tuya BLE v4 / 0xFD50. That MIT notice is
preserved in
[`custom_components/tuya_eboard/tuya_eboard_ble/_vendor/tuya_ble/LICENSE`](custom_components/tuya_eboard/tuya_eboard_ble/_vendor/tuya_ble/LICENSE).
MIT is GPL-compatible, so
the combined work is distributed under GPL v3.0 while that vendored portion retains
its MIT license.
