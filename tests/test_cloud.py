"""Cloud onboarding helpers — pure logic, no Home Assistant, no network.

Imports the module by its short name via conftest's sys.path shim. The Tuya cloud call
itself (async_list_devices) isn't exercised here; these cover the device normalization
and MAC matching that decide which board a cloud account maps to.
"""

import cloud


def _dev(**kw):
    base = dict(
        id="d1", name="7009", local_key="k", mac="DC:23:52:9C:B8:15",
        uuid="u", category="hbc", product_id="qdbj2py2",
    )
    base.update(kw)
    return cloud.CloudDevice(**base)


def test_match_by_mac_ignores_formatting():
    devs = [_dev(mac="DC:23:52:9C:B8:15")]
    assert [d.id for d in cloud.match_by_mac(devs, "dc23529cb815")] == ["d1"]
    assert [d.id for d in cloud.match_by_mac(devs, "DC:23:52:9C:B8:15")] == ["d1"]


def test_match_by_mac_no_match():
    devs = [_dev(mac="DC:23:52:9C:B8:15")]
    assert cloud.match_by_mac(devs, "AA:BB:CC:DD:EE:FF") == []


def test_match_by_mac_empty_or_missing():
    assert cloud.match_by_mac([_dev()], "") == []          # macOS hides the MAC
    assert cloud.match_by_mac([_dev(mac="")], "dc23529cb815") == []  # device has no MAC


def test_match_by_mac_multiple():
    devs = [_dev(id="a", mac="DC:23:52:9C:B8:15"), _dev(id="b", mac="11:22:33:44:55:66")]
    assert [d.id for d in cloud.match_by_mac(devs, "dc-23-52-9c-b8-15")] == ["a"]


def test_to_device_maps_and_trims():
    raw = {
        "id": "d1", "name": "  7009  ", "key": "localkey",
        "mac": "DC:23:52", "uuid": "uu", "category": "hbc", "product_id": "qdbj2py2",
    }
    d = cloud._to_device(raw)
    assert d.id == "d1"
    assert d.name == "7009"            # trimmed
    assert d.local_key == "localkey"   # 'key' -> local_key
    assert d.uuid == "uu"
    assert d.product_id == "qdbj2py2"


def test_to_device_missing_fields_default_empty():
    d = cloud._to_device({"id": "x"})
    assert d.id == "x"
    assert d.local_key == "" and d.mac == "" and d.uuid == ""
