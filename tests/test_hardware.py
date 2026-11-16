"""Packets must match what ElfKey sent in the USB capture (docs/PROTOCOL.md)."""
import pytest

from mk321_remap import hardware
from mk321_remap.hardware import HardwareError, Keypad, KeySetting, slot


class FakeKeypad(Keypad):
    def __init__(self, replies):
        self.path = "fake"
        self.sent = []
        self.replies = replies  # payload (after report id) -> list of reply payloads
        self._pending = []

    def _write(self, payload):
        packet = bytes([hardware.REPORT_ID]) + payload.ljust(8, b"\0")[:8]
        self.sent.append(packet.hex(" "))
        self._pending = list(self.replies.get(payload.ljust(8, b"\0")[:8], []))

    def _drain(self, timeout):
        out, self._pending = self._pending, []
        return out

    def close(self):
        pass


def b(hexstr):
    return bytes.fromhex(hexstr)


def test_slots():
    assert slot(1) == 0x01 and slot(3) == 0x03
    assert slot(1, layer=2) == 0x11 and slot(3, layer=3) == 0x23
    with pytest.raises(HardwareError):
        slot(4)


def test_identify_concatenates_replies():
    pad = FakeKeypad({b("01 83 08 00 00 00 00 00"): [b("4d 4b 33 32 31 55 5f 56"),
                                                        b("32 2e 30 00 00 00 00 00")]})
    assert pad.identify() == "MK321U_V2.0"
    assert pad.sent == ["01 01 83 08 00 00 00 00 00"]


def test_read_key_decodes_f22():
    pad = FakeKeypad({b("01 82 08 01 00 00 00 00"): [b("08 81 00 71 00 00 00 00")]})
    setting = pad.read_key(1)
    assert setting == KeySetting(0x81, 0, 0x71)
    assert setting.describe() == "f22"


def test_write_key_matches_capture():
    pad = FakeKeypad({
        b("01 82 08 01 00 00 00 00"): [b("08 81 00 3a 00 00 00 00")],
        b("01 d1 00 00 00 00 00 00"): [b("d1 00 00 00 00 00 00 00")],
    })
    pad.write_key(1, KeySetting.from_combo("f1"))
    assert pad.sent == [
        "01 01 81 08 01 00 00 00 00",  # select button 1 for writing
        "01 08 81 00 3a 00 00 00 00",  # key type, no modifiers, HID F1
        "01 01 82 08 01 00 00 00 00",  # read back
        "01 01 d1 00 00 00 00 00 00",  # commit
    ]


def test_write_key_detects_mismatch():
    pad = FakeKeypad({b("01 82 08 02 00 00 00 00"): [b("08 81 00 3b 00 00 00 00")]})
    with pytest.raises(HardwareError, match="keypad reports"):
        pad.write_key(2, KeySetting.from_combo("ctrl+c"))


@pytest.mark.parametrize(
    "combo, mods, key",
    [("ctrl+c", 0x01, 0x06), ("ctrl+shift+t", 0x03, 0x17), ("super+l", 0x08, 0x0F),
     ("f24", 0, 0x73), ("rctrl+ralt", 0x50, 0), ("enter", 0, 0x28), ("volumeup", 0, 0x80)],
)
def test_from_combo(combo, mods, key):
    s = KeySetting.from_combo(combo)
    assert (s.type, s.modifiers, s.keycode) == (0x81, mods, key)
    assert KeySetting.from_combo(s.describe()) == s  # describe() round-trips


@pytest.mark.parametrize("combo", ["a+b", "playpause", "nope", "+"])
def test_from_combo_rejects(combo):
    with pytest.raises(HardwareError):
        KeySetting.from_combo(combo)
