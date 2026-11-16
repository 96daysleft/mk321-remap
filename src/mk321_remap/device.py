"""Finding, grabbing and reading the keypad's input nodes."""

from __future__ import annotations

import errno
import logging
import select
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import evdev
from evdev import InputDevice, InputEvent, ecodes

log = logging.getLogger(__name__)


class DeviceGone(Exception):
    """The keypad was unplugged while we were reading it."""


def _is_remappable(dev: InputDevice) -> bool:
    """True for nodes that carry keys or relative motion.

    The MK321 also exposes absolute-pointer nodes (touch/digitizer style);
    those are left alone.
    """
    caps = dev.capabilities()
    keys = caps.get(ecodes.EV_KEY, [])
    has_keys = any(c < ecodes.BTN_MISC or c >= ecodes.KEY_OK for c in keys)
    has_buttons = any(ecodes.BTN_MOUSE <= c < ecodes.BTN_JOYSTICK for c in keys)
    return has_keys or has_buttons or ecodes.EV_REL in caps


def find_devices(vendor: int, product: int) -> list[InputDevice]:
    found = []
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        if (
            dev.info.vendor == vendor
            and dev.info.product == product
            and _is_remappable(dev)
        ):
            found.append(dev)
        else:
            dev.close()
    return found


def present_in_sysfs(vendor: int, product: int) -> list[str]:
    """Event nodes for the device, readable or not (for permission hints)."""
    nodes = []
    for node in sorted(Path("/sys/class/input").glob("event*")):
        try:
            v = int((node / "device/id/vendor").read_text(), 16)
            p = int((node / "device/id/product").read_text(), 16)
        except (OSError, ValueError):
            continue
        if (v, p) == (vendor, product):
            nodes.append(f"/dev/input/{node.name}")
    return nodes


def all_devices() -> list[tuple[str, int, int, str]]:
    rows = []
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        rows.append((dev.path, dev.info.vendor, dev.info.product, dev.name))
        dev.close()
    return sorted(rows, key=lambda r: int(r[0].rsplit("event", 1)[-1]))


@contextmanager
def grabbed(devices: list[InputDevice]) -> Iterator[list[InputDevice]]:
    taken = []
    try:
        for dev in devices:
            try:
                dev.grab()
            except OSError as exc:
                if exc.errno == errno.EBUSY:
                    raise RuntimeError(
                        f"{dev.path} is already grabbed by another program "
                        "(is mk321-remap already running?)"
                    ) from exc
                raise
            taken.append(dev)
        yield devices
    finally:
        for dev in taken:
            try:
                dev.ungrab()
            except OSError:
                pass
        for dev in devices:
            dev.close()


def read_events(
    devices: list[InputDevice], stop: threading.Event, poll: float = 0.5
) -> Iterator[InputEvent]:
    """Yield events from all nodes until ``stop`` is set or the device goes away."""
    by_fd = {dev.fd: dev for dev in devices}
    while not stop.is_set():
        try:
            ready, _, _ = select.select(list(by_fd), [], [], poll)
        except InterruptedError:
            continue
        for fd in ready:
            try:
                yield from by_fd[fd].read()
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno in (errno.ENODEV, errno.EIO):
                    raise DeviceGone(by_fd[fd].path) from exc
                raise
