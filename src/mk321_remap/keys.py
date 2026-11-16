"""Key names, trigger names and the US-layout table used for typing text."""

from __future__ import annotations

from typing import NamedTuple, Union

from evdev import ecodes


class KeyNameError(ValueError):
    """Raised when a key or trigger name cannot be resolved."""


# Friendly aliases -> evdev name without the KEY_ prefix.
ALIASES = {
    "CTRL": "LEFTCTRL",
    "CONTROL": "LEFTCTRL",
    "LCTRL": "LEFTCTRL",
    "RCTRL": "RIGHTCTRL",
    "SHIFT": "LEFTSHIFT",
    "LSHIFT": "LEFTSHIFT",
    "RSHIFT": "RIGHTSHIFT",
    "ALT": "LEFTALT",
    "LALT": "LEFTALT",
    "RALT": "RIGHTALT",
    "ALTGR": "RIGHTALT",
    "SUPER": "LEFTMETA",
    "META": "LEFTMETA",
    "WIN": "LEFTMETA",
    "CMD": "LEFTMETA",
    "RETURN": "ENTER",
    "ESCAPE": "ESC",
    "DEL": "DELETE",
    "INS": "INSERT",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "VOLUP": "VOLUMEUP",
    "VOLDOWN": "VOLUMEDOWN",
    "PLAY": "PLAYPAUSE",
    "NEXT": "NEXTSONG",
    "PREV": "PREVIOUSSONG",
    "PREVIOUS": "PREVIOUSSONG",
}

KeyName = Union[str, int]


def key_code(name: KeyName) -> int:
    """Resolve a key name such as ``ctrl``, ``a``, ``KEY_F13`` or ``BTN_LEFT``."""
    if isinstance(name, bool):
        raise KeyNameError(f"invalid key name {name!r}")
    if isinstance(name, int):
        return name
    raw = str(name).strip()
    if not raw:
        raise KeyNameError("empty key name")
    if raw.isdigit() and len(raw) > 1:
        return int(raw)  # raw evdev code, e.g. "183"
    upper = raw.upper().replace(" ", "")
    if upper.startswith(("KEY_", "BTN_")):
        candidates = [upper]
    else:
        upper = ALIASES.get(upper, upper)
        candidates = [f"KEY_{upper}", f"BTN_{upper}"]
    for candidate in candidates:
        code = ecodes.ecodes.get(candidate)
        if isinstance(code, int):
            return code
    raise KeyNameError(
        f"unknown key name {raw!r} (use evdev names like KEY_F13, or run "
        "`mk321-remap listen` to see what the keypad sends)"
    )


def parse_combo(spec: KeyName | list[KeyName]) -> tuple[int, ...]:
    """Parse ``"ctrl+shift+t"`` (or a list of names) into key codes."""
    if isinstance(spec, (list, tuple)):
        parts = list(spec)
    elif isinstance(spec, int) and not isinstance(spec, bool):
        parts = [spec]
    else:
        parts = [p for p in str(spec).split("+") if p.strip()]
    if not parts:
        raise KeyNameError(f"empty key combo {spec!r}")
    return tuple(key_code(p) for p in parts)


# Range markers that share a code with a real key (e.g. KEY_MIN_INTERESTING == KEY_MUTE).
_MARKER_NAMES = {
    "KEY_MIN_INTERESTING", "BTN_MISC", "BTN_MOUSE", "BTN_JOYSTICK",
    "BTN_GAMEPAD", "BTN_DIGI", "BTN_WHEEL", "BTN_TRIGGER_HAPPY",
}


def key_name(code: int) -> str:
    """Return the most useful evdev name for a key code."""
    name = ecodes.KEY.get(code) or ecodes.BTN.get(code)
    if isinstance(name, (list, tuple)):
        real = [n for n in name if n not in _MARKER_NAMES]
        name = (real or list(name))[0]
    return name or str(code)


class Trigger(NamedTuple):
    """An input on the keypad: a key, or one direction of a wheel/knob."""

    type: int
    code: int
    direction: int = 0  # +1 / -1 for relative axes, 0 for keys


REL_TRIGGERS = {
    "REL_WHEEL_UP": Trigger(ecodes.EV_REL, ecodes.REL_WHEEL, 1),
    "REL_WHEEL_DOWN": Trigger(ecodes.EV_REL, ecodes.REL_WHEEL, -1),
    "REL_HWHEEL_RIGHT": Trigger(ecodes.EV_REL, ecodes.REL_HWHEEL, 1),
    "REL_HWHEEL_LEFT": Trigger(ecodes.EV_REL, ecodes.REL_HWHEEL, -1),
}
_REL_NAMES = {t: n for n, t in REL_TRIGGERS.items()}

# High-resolution wheel axes are folded into their classic counterparts.
HIRES_BASE = {
    ecodes.REL_WHEEL_HI_RES: ecodes.REL_WHEEL,
    ecodes.REL_HWHEEL_HI_RES: ecodes.REL_HWHEEL,
}


def parse_trigger(name: KeyName) -> Trigger:
    if isinstance(name, str) and name.strip().upper() in REL_TRIGGERS:
        return REL_TRIGGERS[name.strip().upper()]
    return Trigger(ecodes.EV_KEY, key_code(name))


def trigger_name(trigger: Trigger) -> str:
    if trigger.type == ecodes.EV_KEY:
        return key_name(trigger.code)
    if trigger in _REL_NAMES:
        return _REL_NAMES[trigger]
    axis = ecodes.REL.get(trigger.code, str(trigger.code))
    return f"{axis}{'+' if trigger.direction > 0 else '-'}"


def _build_us_layout() -> dict[str, tuple[int, bool]]:
    k = ecodes
    table: dict[str, tuple[int, bool]] = {}
    for ch in "abcdefghijklmnopqrstuvwxyz":
        code = getattr(k, f"KEY_{ch.upper()}")
        table[ch] = (code, False)
        table[ch.upper()] = (code, True)
    for ch in "0123456789":
        table[ch] = (getattr(k, f"KEY_{ch}"), False)
    plain = {
        " ": k.KEY_SPACE, "\n": k.KEY_ENTER, "\t": k.KEY_TAB,
        "-": k.KEY_MINUS, "=": k.KEY_EQUAL, "[": k.KEY_LEFTBRACE,
        "]": k.KEY_RIGHTBRACE, "\\": k.KEY_BACKSLASH, ";": k.KEY_SEMICOLON,
        "'": k.KEY_APOSTROPHE, "`": k.KEY_GRAVE, ",": k.KEY_COMMA,
        ".": k.KEY_DOT, "/": k.KEY_SLASH,
    }
    shifted = {
        "!": k.KEY_1, "@": k.KEY_2, "#": k.KEY_3, "$": k.KEY_4, "%": k.KEY_5,
        "^": k.KEY_6, "&": k.KEY_7, "*": k.KEY_8, "(": k.KEY_9, ")": k.KEY_0,
        "_": k.KEY_MINUS, "+": k.KEY_EQUAL, "{": k.KEY_LEFTBRACE,
        "}": k.KEY_RIGHTBRACE, "|": k.KEY_BACKSLASH, ":": k.KEY_SEMICOLON,
        '"': k.KEY_APOSTROPHE, "~": k.KEY_GRAVE, "<": k.KEY_COMMA,
        ">": k.KEY_DOT, "?": k.KEY_SLASH,
    }
    table.update({ch: (code, False) for ch, code in plain.items()})
    table.update({ch: (code, True) for ch, code in shifted.items()})
    return table


US_LAYOUT = _build_us_layout()
