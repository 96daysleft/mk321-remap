"""Command-line entry point: run / listen / list / check."""

from __future__ import annotations

import argparse
import logging
import signal
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
    devices = _wait_for_devices(vendor, product, stop, once=True)
    if not devices:
        if not present_in_sysfs(vendor, product):
            log.error("device %04x:%04x not found (see `mk321-remap list`)", vendor, product)
        return 1
    print(f"Listening on {', '.join(d.path for d in devices)} - press keys, Ctrl+C to quit.")
    print("Use the names on the left as keys under `mappings:` in your config.\n")
    try:
        with grabbed(devices):
            for event in read_events(devices, stop):
                line = _describe(event, cfg)
                if line:
                    print(line, flush=True)
    except DeviceGone:
        print("device unplugged")
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    return 0


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

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    handlers = {"run": cmd_run, "listen": cmd_listen, "list": cmd_list, "check": cmd_check}
    return handlers[args.command or "run"](args)


if __name__ == "__main__":
    sys.exit(main())
