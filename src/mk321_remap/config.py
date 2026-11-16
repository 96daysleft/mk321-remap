"""Load and validate the YAML config."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .keys import US_LAYOUT, KeyNameError, Trigger, parse_combo, parse_trigger, trigger_name

DEFAULT_VENDOR = 0x3553  # PCsensor
DEFAULT_PRODUCT = 0xC010  # MK321U "DIY keyboard"


class ConfigError(ValueError):
    """Raised for invalid configuration."""


@dataclass(frozen=True)
class Step:
    kind: str  # "keys" | "type" | "command" | "sleep"
    keys: tuple[int, ...] = ()
    text: str = ""
    command: str = ""
    seconds: float = 0.0


@dataclass(frozen=True)
class Action:
    steps: tuple[Step, ...]

    @property
    def holdable(self) -> bool:
        """A single key combo is held for as long as the keypad key is held."""
        return len(self.steps) == 1 and self.steps[0].kind == "keys"


@dataclass
class Config:
    vendor: int = DEFAULT_VENDOR
    product: int = DEFAULT_PRODUCT
    passthrough: bool = True
    mappings: dict[Trigger, Action] = field(default_factory=dict)


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mk321-remap" / "config.yaml"


def _parse_id(value: Any, what: str) -> int:
    try:
        number = value if isinstance(value, int) else int(str(value), 16)
    except ValueError as exc:
        raise ConfigError(f"device.{what}: {value!r} is not a hex USB id") from exc
    if not 0 <= number <= 0xFFFF:
        raise ConfigError(f"device.{what}: {value!r} is out of range")
    return number


def _parse_step(raw: Any, where: str) -> Step:
    if isinstance(raw, (str, int)) and not isinstance(raw, bool):
        raw = {"keys": raw}  # shorthand: `KEY_A: ctrl+c`
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ConfigError(
            f"{where}: each step needs exactly one of keys / type / command / sleep"
        )
    ((kind, value),) = raw.items()
    try:
        if kind == "keys":
            return Step("keys", keys=parse_combo(value))
    except KeyNameError as exc:
        raise ConfigError(f"{where}: {exc}") from exc
    if kind == "type":
        text = str(value)
        bad = sorted({ch for ch in text if ch not in US_LAYOUT})
        if bad:
            raise ConfigError(f"{where}: cannot type characters {bad!r} (US layout only)")
        return Step("type", text=text)
    if kind == "command":
        if not str(value).strip():
            raise ConfigError(f"{where}: command is empty")
        return Step("command", command=str(value))
    if kind == "sleep":
        try:
            seconds = float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{where}: sleep must be a number of seconds") from exc
        if seconds < 0:
            raise ConfigError(f"{where}: sleep must not be negative")
        return Step("sleep", seconds=seconds)
    raise ConfigError(f"{where}: unknown step type {kind!r}")


def _parse_action(raw: Any, where: str) -> Action:
    if isinstance(raw, list):
        if not raw:
            raise ConfigError(f"{where}: empty step list")
        steps = tuple(_parse_step(s, f"{where}[{i}]") for i, s in enumerate(raw))
    else:
        steps = (_parse_step(raw, where),)
    return Action(steps)


def parse_config(data: Any) -> Config:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("config must be a mapping")
    unknown = set(data) - {"device", "passthrough", "mappings"}
    if unknown:
        raise ConfigError(f"unknown top-level keys: {', '.join(sorted(map(str, unknown)))}")

    cfg = Config()
    device = data.get("device") or {}
    if not isinstance(device, dict):
        raise ConfigError("device must be a mapping with vendor/product")
    if "vendor" in device:
        cfg.vendor = _parse_id(device["vendor"], "vendor")
    if "product" in device:
        cfg.product = _parse_id(device["product"], "product")

    passthrough = data.get("passthrough", True)
    if not isinstance(passthrough, bool):
        raise ConfigError("passthrough must be true or false")
    cfg.passthrough = passthrough

    mappings = data.get("mappings") or {}
    if not isinstance(mappings, dict):
        raise ConfigError("mappings must be a mapping of trigger -> action")
    for name, raw in mappings.items():
        try:
            trigger = parse_trigger(name)
        except KeyNameError as exc:
            raise ConfigError(f"mappings: {exc}") from exc
        if trigger in cfg.mappings:
            raise ConfigError(f"mappings: {name!r} duplicates {trigger_name(trigger)}")
        cfg.mappings[trigger] = _parse_action(raw, f"mappings.{name}")
    return cfg


def load_config(path: Path) -> Config:
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return parse_config(data)
