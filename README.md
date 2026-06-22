# tuya-eboard

Home Assistant sensors for **Tuya BLE** electric-skateboard ESCs - built first for the
**OMW Hussar / Hobbywing HW7009**, structured to work with any Tuya BLE board. It's the
only HA integration with **Tuya BLE v4 / 0xFD50** support.

The board is only reachable over Bluetooth when it's powered on and in range (the start
and end of a ride), so this is a **connect-on-demand snapshot** integration, not live
telemetry: it reads when the board is awake, shows last-known values with a `last_seen`
timestamp, and derives per-ride stats from successive reads. The board stays **strictly
read-only**.

## Install (HACS)

1. In HACS → ⋮ → **Custom repositories**, add this repo with category **Integration**.
2. Install **Tuya E-Board**, then restart Home Assistant.

## Add your board

1. Power the board on (remote awake) and bring it within Bluetooth range of Home
   Assistant. HA auto-discovers it over Bluetooth.
2. **Log in with your Tuya IoT cloud credentials and pick your board** - the local key is
   pulled automatically. See the official
   [Tuya integration docs](https://www.home-assistant.io/integrations/tuya/) for creating
   a project and getting the Access ID / Secret.

Manual key entry is available as an advanced fallback. Credentials are verified by one
real connect + read before the entry is created, and a rotated key (after re-pairing the
board) is refreshed automatically via reauth.

**Entities:** battery %, voltage, odometer, last trip distance/time, speed mode, cruise,
BLE lock, `In range`, and `last seen`. "Last seen 2h ago" is normal, not an error - the
board is asleep most of the time.

## Blueprints

Board-specific logic lives in the integration; what you *do* with it lives in blueprints
you import once and own. The integration fires a `tuya_eboard_ride_completed` event (with
distance, battery used, and voltage drop already computed) whenever the odometer advances
between two reads, so the blueprints stay simple.

| Blueprint | What it does | Import |
|-----------|--------------|--------|
| **Ride journal** | Logbook entry (+ optional push) after every ride | [![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjmdevita%2Ftuya_eboard%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fride_journal.yaml) |
| **Service milestone** | Maintenance reminder every N miles/km of odometer | [![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjmdevita%2Ftuya_eboard%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fservice_milestone.yaml) |

These aren't installed by HACS (a custom integration can't auto-populate your blueprint
list). Click the badge, or go to **Settings → Automations & Scenes → Blueprints → Import
Blueprint** and paste the blueprint's GitHub URL, then create an automation from it.

## How it works

A passive Bluetooth scan notices the board advertise; the integration connects on demand,
reads the Tuya datapoints, and disconnects. The *process* (BLE transport, Tuya handshake +
crypto, DP framing) is shared code; the per-board *mapping* (which DP is voltage vs
odometer, scales, enums) is data - one YAML file per `product_id`. So onboarding a new
board adds a map file, not code. Protocol generation is auto-detected: **v4 / 0xFD50** is
verified (HW7009/Hussar); **v3 / 0xA201** exists but is beta/untested.

## Developing

Architecture, the per-board mapping workflow, the dev CLI, and the write-safety model are
in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Licensed under the **GNU GPL v3.0** - see [`LICENSE`](LICENSE).

It vendors the Tuya BLE transport from
[PlusPlus-ua/ha_tuya_ble](https://github.com/PlusPlus-ua/ha_tuya_ble) (**MIT**, © 2023
PlusPlus-ua), patched here for Tuya BLE v4 / 0xFD50. That MIT notice is preserved in
[`tuya_eboard_ble/_vendor/tuya_ble/LICENSE`](custom_components/tuya_eboard/tuya_eboard_ble/_vendor/tuya_ble/LICENSE).
MIT is GPL-compatible, so the combined work is distributed under GPL v3.0 while the
vendored portion retains its MIT license.
