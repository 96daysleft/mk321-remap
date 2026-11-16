"""Read and write the key settings stored on the keypad itself.

Protocol notes (from a USB capture of PCsensor's ElfKey talking to an
MK321U_V2.0, 3553:c010) are in docs/PROTOCOL.md. In short, every packet is
a 9-byte HID output report on interface 1: report id 0x01 + 8 bytes.

    command packets:  01 | 01 <op> ...
    data packets:     01 | 08 <type> <modifiers> <keycode> 00 00 00 00
"""

from __future__ import annotations

import os
import select
import time
from dataclasses import dataclass
from pathlib import Path

from evdev import ecodes

from .keys import KeyNameError, key_code, key_name

REPORT_ID = 0x01
CONFIG_INTERFACE = "input1"
PACKET_DELAY = 0.03  # ElfKey waits ~20 ms between packets

OP_WRITE_KEY = 0x81
OP_READ_KEY = 0x82
OP_IDENTIFY = 0x83
OP_COMMIT = 0xD1

TYPE_KEY = 0x01
TYPE_KEY_SET = 0x81  # what ElfKey writes; 0x01 is the factory value for unused layers

BUTTONS = 3
LAYERS = 3

# Modifier bits (same layout as a HID boot keyboard report).
MODIFIER_BITS = {
    ecodes.KEY_LEFTCTRL: 0x01, ecodes.KEY_LEFTSHIFT: 0x02,
    ecodes.KEY_LEFTALT: 0x04, ecodes.KEY_LEFTMETA: 0x08,
    ecodes.KEY_RIGHTCTRL: 0x10, ecodes.KEY_RIGHTSHIFT: 0x20,
    ecodes.KEY_RIGHTALT: 0x40, ecodes.KEY_RIGHTMETA: 0x80,
}


def _build_hid_table() -> dict[int, int]:
    """evdev key code -> USB HID keyboard usage."""
    k = ecodes
    table = {getattr(k, f"KEY_{c}"): 0x04 + i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
    table.update({getattr(k, f"KEY_{n}"): 0x1E + n - 1 for n in range(1, 10)})
    table.update({getattr(k, f"KEY_F{n}"): 0x3A + n - 1 for n in range(1, 13)})
    table.update({getattr(k, f"KEY_F{n}"): 0x68 + n - 13 for n in range(13, 25)})
    table.update({getattr(k, f"KEY_KP{n}"): 0x59 + n - 1 for n in range(1, 10)})
    table.update({
        k.KEY_0: 0x27, k.KEY_ENTER: 0x28, k.KEY_ESC: 0x29, k.KEY_BACKSPACE: 0x2A,
        k.KEY_TAB: 0x2B, k.KEY_SPACE: 0x2C, k.KEY_MINUS: 0x2D, k.KEY_EQUAL: 0x2E,
        k.KEY_LEFTBRACE: 0x2F, k.KEY_RIGHTBRACE: 0x30, k.KEY_BACKSLASH: 0x31,
        k.KEY_SEMICOLON: 0x33, k.KEY_APOSTROPHE: 0x34, k.KEY_GRAVE: 0x35,
        k.KEY_COMMA: 0x36, k.KEY_DOT: 0x37, k.KEY_SLASH: 0x38, k.KEY_CAPSLOCK: 0x39,
        k.KEY_SYSRQ: 0x46, k.KEY_SCROLLLOCK: 0x47, k.KEY_PAUSE: 0x48,
        k.KEY_INSERT: 0x49, k.KEY_HOME: 0x4A, k.KEY_PAGEUP: 0x4B, k.KEY_DELETE: 0x4C,
        k.KEY_END: 0x4D, k.KEY_PAGEDOWN: 0x4E, k.KEY_RIGHT: 0x4F, k.KEY_LEFT: 0x50,
        k.KEY_DOWN: 0x51, k.KEY_UP: 0x52, k.KEY_NUMLOCK: 0x53, k.KEY_KPSLASH: 0x54,
        k.KEY_KPASTERISK: 0x55, k.KEY_KPMINUS: 0x56, k.KEY_KPPLUS: 0x57,
        k.KEY_KPENTER: 0x58, k.KEY_KP0: 0x62, k.KEY_KPDOT: 0x63, k.KEY_102ND: 0x64,
        k.KEY_COMPOSE: 0x65, k.KEY_POWER: 0x66, k.KEY_KPEQUAL: 0x67,
        k.KEY_MUTE: 0x7F, k.KEY_VOLUMEUP: 0x80, k.KEY_VOLUMEDOWN: 0x81,
    })
    return table


EVDEV_TO_HID = _build_hid_table()
HID_TO_EVDEV = {hid: ev for ev, hid in EVDEV_TO_HID.items()}


class HardwareError(RuntimeError):
    pass


def slot(button: int, layer: int = 1) -> int:
    if not 1 <= button <= BUTTONS:
        raise HardwareError(f"button must be 1-{BUTTONS}")
    if not 1 <= layer <= LAYERS:
        raise HardwareError(f"layer must be 1-{LAYERS}")
    return (layer - 1) * 0x10 + button


@dataclass(frozen=True)
class KeySetting:
    type: int
    modifiers: int
    keycode: int

    @classmethod
    def from_combo(cls, combo: str) -> KeySetting:
        modifiers, keycode = 0, 0
        for part in (p.strip() for p in combo.split("+") if p.strip()):
            try:
                code = key_code(part)
            except KeyNameError as exc:
                raise HardwareError(str(exc)) from exc
            if code in MODIFIER_BITS:
                modifiers |= MODIFIER_BITS[code]
            elif code in EVDEV_TO_HID:
                if keycode:
                    raise HardwareError(f"{combo!r}: the keypad stores only one non-modifier key")
                keycode = EVDEV_TO_HID[code]
            else:
                raise HardwareError(
                    f"{part!r} can't be stored on the keypad (media/consumer keys are not "
                    "supported yet); use the software remapper for it"
                )
        if not modifiers and not keycode:
            raise HardwareError(f"empty combo {combo!r}")
        return cls(TYPE_KEY_SET, modifiers, keycode)

    def describe(self) -> str:
        if self.type not in (TYPE_KEY, TYPE_KEY_SET):
            return (f"unknown type 0x{self.type:02x} "
                    f"(mods 0x{self.modifiers:02x}, key 0x{self.keycode:02x})")

        def short(ev: int) -> str:
            return key_name(ev).removeprefix("KEY_").lower()

        names = [short(ev) for ev, bit in MODIFIER_BITS.items() if self.modifiers & bit]
        if self.keycode:
            ev = HID_TO_EVDEV.get(self.keycode)
            names.append(short(ev) if ev is not None else f"hid:0x{self.keycode:02x}")
        return "+".join(names) or "nothing"


def find_config_hidraw(vendor: int, product: int) -> str:
    want = f"{vendor:08X}:{product:08X}"
    for node in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        try:
            uevent = (node / "device/uevent").read_text()
        except OSError:
            continue
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        if fields.get("HID_ID", "").upper().endswith(want) and fields.get(
            "HID_PHYS", ""
        ).endswith(CONFIG_INTERFACE):
            return f"/dev/{node.name}"
    raise HardwareError(
        f"keypad {vendor:04x}:{product:04x} not found (unplugged, or attached to a VM?)"
    )


class Keypad:
    def __init__(self, path: str):
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR)
        except PermissionError as exc:
            raise HardwareError(
                f"cannot open {path}: install the udev rule (./install.sh --udev-only) "
                "and replug the keypad"
            ) from exc
        self._drain(0.05)

    @classmethod
    def open(cls, vendor: int, product: int) -> Keypad:
        return cls(find_config_hidraw(vendor, product))

    def close(self) -> None:
        os.close(self.fd)

    def __enter__(self) -> Keypad:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- transport -------------------------------------------------------

    def _write(self, payload: bytes) -> None:
        os.write(self.fd, bytes([REPORT_ID]) + payload.ljust(8, b"\0")[:8])
        time.sleep(PACKET_DELAY)

    def _drain(self, timeout: float) -> list[bytes]:
        packets = []
        while select.select([self.fd], [], [], timeout)[0]:
            pkt = os.read(self.fd, 64)
            packets.append(pkt[1:] if pkt[:1] == bytes([REPORT_ID]) else pkt)
            timeout = 0.05
        return packets

    def _command(self, op: int, *args: int, timeout: float = 0.5) -> list[bytes]:
        self._write(bytes([0x01, op, *args]))
        return self._drain(timeout)

    # -- operations ------------------------------------------------------

    def identify(self) -> str:
        replies = self._command(OP_IDENTIFY, 0x08)
        return b"".join(replies).split(b"\0", 1)[0].decode("ascii", "replace")

    def read_key(self, button: int, layer: int = 1) -> KeySetting:
        replies = self._command(OP_READ_KEY, 0x08, slot(button, layer))
        if not replies or len(replies[0]) < 4:
            raise HardwareError(f"no reply reading button {button} layer {layer}")
        data = replies[0]
        return KeySetting(data[1], data[2], data[3])

    def write_key(self, button: int, setting: KeySetting, layer: int = 1) -> KeySetting:
        """Store a key on the keypad, the same way ElfKey does, and read it back."""
        self._write(bytes([0x01, OP_WRITE_KEY, 0x08, slot(button, layer)]))
        self._write(bytes([0x08, setting.type, setting.modifiers, setting.keycode]))
        self._drain(0.1)
        stored = self.read_key(button, layer)
        self._command(OP_COMMIT)
        if (stored.modifiers, stored.keycode) != (setting.modifiers, setting.keycode):
            raise HardwareError(
                f"button {button} layer {layer}: wrote {setting.describe()} "
                f"but keypad reports {stored.describe()}"
            )
        return stored
