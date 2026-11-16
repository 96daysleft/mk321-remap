#!/usr/bin/env python3
"""Read-only probe of the MK321's configuration interface.

Sends the PCsensor "query key N" command (0x82, as used by the footswitch
tool for 3553:b001) to the keypad's vendor HID interface and prints the raw
replies. It never sends write commands (0x80 / 0x81), so it cannot change
the keypad's stored configuration.

Usage: python3 tools/hid_probe.py [--keys 6] [--pad]
"""

from __future__ import annotations

import argparse
import os
import select
import sys
from pathlib import Path

VENDOR, PRODUCT = 0x3553, 0xC010
CONFIG_INTERFACE = "input1"


def find_hidraw() -> str:
    for node in sorted(Path("/sys/class/hidraw").iterdir()):
        uevent = (node / "device/uevent").read_text()
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        hid_id = fields.get("HID_ID", "")
        if hid_id.upper().endswith(f"{VENDOR:08X}:{PRODUCT:08X}") and fields.get(
            "HID_PHYS", ""
        ).endswith(CONFIG_INTERFACE):
            return f"/dev/{node.name}"
    sys.exit(f"no hidraw node for {VENDOR:04x}:{PRODUCT:04x} {CONFIG_INTERFACE}")


def read_all(fd: int, timeout: float) -> list[bytes]:
    replies = []
    while True:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return replies
        replies.append(os.read(fd, 64))
        timeout = 0.15  # drain any follow-up packets quickly


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keys", type=int, default=6, help="how many key slots to query")
    ap.add_argument("--pad", action="store_true",
                    help="send 9 bytes (report id + 8) instead of 8")
    args = ap.parse_args()

    path = find_hidraw()
    print(f"config interface: {path}")
    try:
        fd = os.open(path, os.O_RDWR)
    except PermissionError:
        sys.exit(f"cannot open {path}: install the udev rule (./install.sh --udev-only) "
                 "and replug the keypad")
    try:
        stale = read_all(fd, 0.1)
        for pkt in stale:
            print(f"  (stale) {pkt.hex(' ')}")
        for key in range(1, args.keys + 1):
            query = bytes([0x01, 0x82, 0x08, key, 0, 0, 0, 0]) + (b"\0" if args.pad else b"")
            os.write(fd, query)
            replies = read_all(fd, 1.0)
            print(f"key {key}: sent {query.hex(' ')}")
            if not replies:
                print("    no reply")
            for pkt in replies:
                print(f"    got  {pkt.hex(' ')}")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
