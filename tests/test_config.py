from pathlib import Path

import pytest
import yaml
from evdev import ecodes

from mk321_remap.config import ConfigError, load_config, parse_config
from mk321_remap.keys import Trigger

KEY = ecodes.EV_KEY


def test_defaults():
    cfg = parse_config(None)
    assert (cfg.vendor, cfg.product) == (0x3553, 0xC010)
    assert cfg.passthrough is True
    assert cfg.mappings == {}


def test_example_config_is_valid():
    example = Path(__file__).parent.parent / "config.example.yaml"
    cfg = load_config(example)
    assert cfg.mappings


def test_shorthand_and_steps():
    cfg = parse_config(
        {
            "device": {"vendor": "1189", "product": 0x8890},
            "passthrough": False,
            "mappings": {
                "KEY_1": "ctrl+c",
                "a": {"command": "true"},
                "REL_WHEEL_UP": [{"keys": "alt+tab"}, {"sleep": 0.1}, {"type": "Hi!"}],
            },
        }
    )
    assert (cfg.vendor, cfg.product) == (0x1189, 0x8890)
    assert cfg.passthrough is False
    one = cfg.mappings[Trigger(KEY, ecodes.KEY_1)]
    assert one.holdable and one.steps[0].keys == (ecodes.KEY_LEFTCTRL, ecodes.KEY_C)
    assert cfg.mappings[Trigger(KEY, ecodes.KEY_A)].steps[0].command == "true"
    wheel = cfg.mappings[Trigger(ecodes.EV_REL, ecodes.REL_WHEEL, 1)]
    assert [s.kind for s in wheel.steps] == ["keys", "sleep", "type"]
    assert not wheel.holdable


def test_yaml_hex_ids():
    cfg = parse_config(yaml.safe_load("device: {vendor: 0x3553, product: c010}"))
    assert (cfg.vendor, cfg.product) == (0x3553, 0xC010)


@pytest.mark.parametrize(
    "data, message",
    [
        ({"bogus": 1}, "unknown top-level"),
        ({"device": {"vendor": "zz"}}, "hex USB id"),
        ({"passthrough": "yes"}, "passthrough"),
        ({"mappings": {"KEY_NOPE": "a"}}, "unknown key name"),
        ({"mappings": {"KEY_1": "ctrl+nope"}}, "unknown key name"),
        ({"mappings": {"KEY_1": {"type": "café"}}}, "cannot type"),
        ({"mappings": {"KEY_1": {"sleep": -1}}}, "negative"),
        ({"mappings": {"KEY_1": {"keys": "a", "type": "b"}}}, "exactly one"),
        ({"mappings": {"KEY_1": {"launch": "x"}}}, "unknown step"),
        ({"mappings": {"KEY_1": []}}, "empty step list"),
        ({"mappings": {"a": "b", "KEY_A": "c"}}, "duplicates"),
    ],
)
def test_errors(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")
