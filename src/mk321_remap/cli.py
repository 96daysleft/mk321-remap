"""Command-line entry point: run / listen / list / check."""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from evdev import ecodes

from . import __version__
from .config import (
    DEFAULT_PRODUCT,
    DEFAULT_VENDOR,
    Config,
    ConfigError,
    default_config_path,
    load_config,
)
from .device import DeviceGone, all_devices, find_devices, grabbed, present_in_sysfs, read_events
from .keys import HIRES_BASE, Trigger, trigger_name
from .remapper import Emitter, Remapper

log = logging.getLogger("mk321-remap")

PERMISSION_HINT = (
    "The keypad is plugged in ({nodes}) but this user cannot read it.\n"
    "Install the udev rule (./install.sh --udev-only) and replug the keypad,\n"
    "or add yourself to the 'input' group and log in again."
)


def _stop_event() -> threading.Event:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def _wait_for_devices(vendor: int, product: int, stop: threading.Event, once: bool):
    warned = False
    while not stop.is_set():
        devices = find_devices(vendor, product)
        if devices:
            return devices
        if not warned:
            nodes = present_in_sysfs(vendor, product)
            if nodes:
                log.warning(PERMISSION_HINT.format(nodes=", ".join(nodes)))
            else:
                log.info("waiting for device %04x:%04x ...", vendor, product)
            warned = True
        if once:
            return []
        stop.wait(2)
    return []


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    log.info(
        "loaded %d mapping(s) from %s for %04x:%04x",
        len(cfg.mappings), args.config, cfg.vendor, cfg.product,
    )
    stop = _stop_event()
    emitter = Emitter()
    try:
        while not stop.is_set():
            devices = _wait_for_devices(cfg.vendor, cfg.product, stop, once=False)
            if not devices:
                break
            remapper = Remapper(cfg, emitter)
            try:
                with grabbed(devices):
                    log.info("grabbed %s", ", ".join(d.path for d in devices))
                    for event in read_events(devices, stop):
                        remapper.handle(event)
            except DeviceGone:
                log.info("device unplugged; waiting for it to come back")
            finally:
                remapper.close()
            time.sleep(0.5)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        emitter.close()
    return 0


def _describe(event, cfg: Config) -> str | None:
    if event.type == ecodes.EV_KEY:
        state = {0: "released", 1: "pressed", 2: "repeat"}.get(event.value, str(event.value))
        if event.value == 2:
            return None
        trig = Trigger(ecodes.EV_KEY, event.code)
    elif event.type == ecodes.EV_REL and event.value:
        if event.code in HIRES_BASE:
            return None
        trig = Trigger(ecodes.EV_REL, event.code, 1 if event.value > 0 else -1)
        state = f"x{abs(event.value)}"
    else:
        return None
    mapped = "  (mapped)" if trig in cfg.mappings else ""
    return f"{trigger_name(trig):<22} {state}{mapped}"


def cmd_listen(args: argparse.Namespace) -> int:
    cfg = Config()
    if args.config.exists():
        try:
            cfg = load_config(args.config)
        except ConfigError as exc:
            log.warning("ignoring config: %s", exc)
    vendor = args.vendor if args.vendor is not None else cfg.vendor
    product = args.product if args.product is not None else cfg.product
    stop = _stop_event()
    paused = _pause_service()
    try:
        devices = _wait_for_devices(vendor, product, stop, once=True)
        if not devices:
            if not present_in_sysfs(vendor, product):
                log.error("device %04x:%04x not found (see `mk321-remap list`)", vendor, product)
            return 1
        with grabbed(devices):
            print(f"Listening on {', '.join(d.path for d in devices)} - "
                  "press keys, Ctrl+C to quit.")
            print("Use the names on the left as keys under `mappings:` in your config.\n")
            for event in read_events(devices, stop):
                line = _describe(event, cfg)
                if line:
                    print(line, flush=True)
    except DeviceGone:
        print("device unplugged")
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        if paused:
            _resume_service()
    return 0


SERVICE = "mk321-remap.service"


def _systemctl(*args: str) -> bool:
    try:
        return subprocess.run(
            ["systemctl", "--user", *args, SERVICE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
    except FileNotFoundError:
        return False


def _pause_service() -> bool:
    """Stop the background service (it holds the keypad) while listening."""
    if not _systemctl("is-active", "--quiet"):
        return False
    print(f"Pausing {SERVICE} while listening (it will be restarted on exit).")
    return _systemctl("stop")


def _resume_service() -> None:
    if _systemctl("start"):
        print(f"\nRestarted {SERVICE}.")
    else:
        log.warning("could not restart %s; run: systemctl --user start %s", SERVICE, SERVICE)


def cmd_list(args: argparse.Namespace) -> int:
    rows = all_devices()
    if not rows:
        print("No readable input devices (are you in the 'input' group?)")
    for path, vendor, product, name in rows:
        mark = "*" if (vendor, product) == (DEFAULT_VENDOR, DEFAULT_PRODUCT) else " "
        print(f"{mark} {path:<20} {vendor:04x}:{product:04x}  {name}")
    unreadable = present_in_sysfs(DEFAULT_VENDOR, DEFAULT_PRODUCT)
    if unreadable and not any(r[1:3] == (DEFAULT_VENDOR, DEFAULT_PRODUCT) for r in rows):
        print("\n" + PERMISSION_HINT.format(nodes=", ".join(unreadable)))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{args.config}: OK - device {cfg.vendor:04x}:{cfg.product:04x}, "
          f"passthrough={'on' if cfg.passthrough else 'off'}")
    for trig, action in cfg.mappings.items():
        kinds = " -> ".join(s.kind for s in action.steps)
        hold = " (held)" if action.holdable else ""
        print(f"  {trigger_name(trig):<22} {kinds}{hold}")
    return 0


def cmd_hw(args: argparse.Namespace) -> int:
    """Read/write the key settings stored in the keypad's own memory."""
    from .hardware import BUTTONS, LAYERS, HardwareError, Keypad, KeySetting

    vendor = args.vendor if args.vendor is not None else DEFAULT_VENDOR
    product = args.product if args.product is not None else DEFAULT_PRODUCT
    try:
        with Keypad.open(vendor, product) as pad:
            if args.hw_command == "info":
                print(f"{pad.path}: {pad.identify() or 'no identify reply'}")
            elif args.hw_command == "read":
                print(f"model: {pad.identify()}")
                layers = range(1, LAYERS + 1) if args.all_layers else [args.layer]
                for layer in layers:
                    for button in range(1, BUTTONS + 1):
                        setting = pad.read_key(button, layer)
                        print(f"  layer {layer} button {button}: {setting.describe()}")
            elif args.hw_command == "set":
                setting = KeySetting.from_combo(args.combo)
                before = pad.read_key(args.button, args.layer)
                stored = pad.write_key(args.button, setting, args.layer)
                print(f"layer {args.layer} button {args.button}: "
                      f"{before.describe()} -> {stored.describe()}")
    except HardwareError as exc:
        log.error("%s", exc)
        return 1
    return 0


def _hex(value: str) -> int:
    return int(value, 16)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mk321-remap",
        description="Remap the PCsensor MK321 mini keyboard (or any evdev device) on Linux.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", type=Path, default=default_config_path(),
                        help="config file (default: %(default)s)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="run the remapper (default)")
    listen = sub.add_parser("listen", help="show the names of keys as you press them")
    listen.add_argument("--vendor", type=_hex, help="USB vendor id in hex (default from config)")
    listen.add_argument("--product", type=_hex, help="USB product id in hex")
    sub.add_parser("list", help="list input devices and their USB ids")
    sub.add_parser("check", help="validate the config file")

    hw = sub.add_parser("hw", help="read/write the keys stored on the keypad itself (like ElfKey)")
    hw.add_argument("--vendor", type=_hex, help="USB vendor id in hex (default 3553)")
    hw.add_argument("--product", type=_hex, help="USB product id in hex (default c010)")
    hw_sub = hw.add_subparsers(dest="hw_command", required=True)
    hw_sub.add_parser("info", help="show the keypad model/firmware")
    hw_read = hw_sub.add_parser("read", help="show what each button is set to")
    hw_read.add_argument("--layer", type=int, default=1, choices=[1, 2, 3])
    hw_read.add_argument("--all-layers", action="store_true")
    hw_set = hw_sub.add_parser("set", help="store a key combo on a button, e.g. `hw set 1 ctrl+c`")
    hw_set.add_argument("button", type=int, choices=[1, 2, 3])
    hw_set.add_argument("combo", help="modifiers plus at most one key, e.g. ctrl+shift+t, f13")
    hw_set.add_argument("--layer", type=int, default=1, choices=[1, 2, 3])

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    handlers = {"run": cmd_run, "listen": cmd_listen, "list": cmd_list, "check": cmd_check,
                "hw": cmd_hw}
    return handlers[args.command or "run"](args)


if __name__ == "__main__":
    sys.exit(main())
