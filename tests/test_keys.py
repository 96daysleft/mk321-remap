import pytest
from evdev import ecodes

from mk321_remap.keys import (
    US_LAYOUT,
    KeyNameError,
    Trigger,
    key_code,
    key_name,
    parse_combo,
    parse_trigger,
    trigger_name,
)


@pytest.mark.parametrize(
    "name, code",
    [
        ("a", ecodes.KEY_A),
        ("KEY_A", ecodes.KEY_A),
        ("ctrl", ecodes.KEY_LEFTCTRL),
        ("Super", ecodes.KEY_LEFTMETA),
        ("f13", ecodes.KEY_F13),
        ("1", ecodes.KEY_1),
        ("volumeup", ecodes.KEY_VOLUMEUP),
        ("BTN_LEFT", ecodes.BTN_LEFT),
        ("left", ecodes.KEY_LEFT),
        ("183", 183),
        (30, 30),
    ],
)
def test_key_code(name, code):
    assert key_code(name) == code


@pytest.mark.parametrize("name", ["", "nope", "KEY_NOPE", True])
def test_key_code_rejects(name):
    with pytest.raises(KeyNameError):
        key_code(name)


def test_parse_combo():
    assert parse_combo("ctrl+shift+t") == (ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_T)
    assert parse_combo(["alt", "tab"]) == (ecodes.KEY_LEFTALT, ecodes.KEY_TAB)
    with pytest.raises(KeyNameError):
        parse_combo("+")


def test_triggers_round_trip():
    for name in ["KEY_1", "KEY_VOLUMEUP", "REL_WHEEL_UP", "REL_WHEEL_DOWN", "REL_HWHEEL_LEFT"]:
        assert trigger_name(parse_trigger(name)) == name
    assert parse_trigger("rel_wheel_up") == Trigger(ecodes.EV_REL, ecodes.REL_WHEEL, 1)


def test_key_name_handles_aliased_codes():
    assert key_name(ecodes.KEY_A) == "KEY_A"
    assert key_name(ecodes.KEY_MUTE) == "KEY_MUTE"
    assert key_name(ecodes.BTN_LEFT) == "BTN_LEFT"
    assert isinstance(key_name(ecodes.KEY_COFFEE), str)


def test_us_layout():
    assert US_LAYOUT["a"] == (ecodes.KEY_A, False)
    assert US_LAYOUT["A"] == (ecodes.KEY_A, True)
    assert US_LAYOUT["?"] == (ecodes.KEY_SLASH, True)
    assert all(chr(c) in US_LAYOUT for c in range(32, 127))
