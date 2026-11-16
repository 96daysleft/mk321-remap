"""Translate keypad events into actions on a virtual uinput device."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from evdev import InputEvent, UInput, ecodes

from .config import Action, Config, Step
from .keys import HIRES_BASE, US_LAYOUT, Trigger

log = logging.getLogger(__name__)


def _virtual_key_codes() -> list[int]:
    """Keyboard keys and mouse buttons, minus joystick/tablet ranges.

    Advertising joystick or touch buttons would make libinput classify the
    virtual device as something other than a keyboard + mouse.
    """
    skip = [
        range(0x100, 0x110),  # BTN_MISC / BTN_0..9
        range(0x118, 0x160),  # joystick, gamepad, digitizer, wheel
        range(0x2C0, 0x300),  # BTN_TRIGGER_HAPPY
    ]
    codes = set(ecodes.KEY) | set(ecodes.BTN)
    return sorted(
        c for c in codes
        if 0 < c < ecodes.KEY_MAX and not any(c in r for r in skip)
    )


class Emitter:
    """Thread-safe wrapper around the virtual output device."""

    def __init__(self, ui: UInput | None = None, type_delay: float = 0.004):
        self.ui = ui or UInput(
            {
                ecodes.EV_KEY: _virtual_key_codes(),
                ecodes.EV_REL: [
                    ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL,
                    ecodes.REL_WHEEL_HI_RES, ecodes.REL_HWHEEL_HI_RES,
                ],
            },
            name="mk321-remap virtual keyboard",
        )
        self.type_delay = type_delay
        self._lock = threading.RLock()
        self._down: set[int] = set()

    def write(self, etype: int, code: int, value: int) -> None:
        with self._lock:
            if etype == ecodes.EV_KEY:
                if value:
                    self._down.add(code)
                else:
                    self._down.discard(code)
            self.ui.write(etype, code, value)

    def syn(self) -> None:
        with self._lock:
            self.ui.syn()

    def press(self, codes: tuple[int, ...]) -> None:
        with self._lock:
            for code in codes:
                self.write(ecodes.EV_KEY, code, 1)
            self.syn()

    def release(self, codes: tuple[int, ...]) -> None:
        with self._lock:
            for code in reversed(codes):
                self.write(ecodes.EV_KEY, code, 0)
            self.syn()

    def tap(self, codes: tuple[int, ...]) -> None:
        with self._lock:
            self.press(codes)
            self.release(codes)

    def type_text(self, text: str) -> None:
        for ch in text:
            code, shift = US_LAYOUT[ch]
            self.tap((ecodes.KEY_LEFTSHIFT, code) if shift else (code,))
            if self.type_delay:
                time.sleep(self.type_delay)

    def release_all(self) -> None:
        with self._lock:
            for code in sorted(self._down):
                self.ui.write(ecodes.EV_KEY, code, 0)
            self._down.clear()
            self.ui.syn()

    def close(self) -> None:
        self.release_all()
        self.ui.close()


def run_shell(command: str) -> None:
    log.info("running: %s", command)
    subprocess.Popen(  # noqa: S602 - running user-configured commands is the point
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        start_new_session=True,
    )


class Remapper:
    """Feeds raw keypad events through the configured mappings."""

    def __init__(
        self,
        config: Config,
        emitter: Emitter,
        run_command: Callable[[str], None] = run_shell,
        background: bool = True,
    ):
        self.config = config
        self.emitter = emitter
        self.run_command = run_command
        self._pool = ThreadPoolExecutor(max_workers=1) if background else None
        self._held: dict[int, Action] = {}
        self._dirty = False

    # -- actions ---------------------------------------------------------

    def _run_steps(self, steps: tuple[Step, ...]) -> None:
        for step in steps:
            try:
                if step.kind == "keys":
                    self.emitter.tap(step.keys)
                elif step.kind == "type":
                    self.emitter.type_text(step.text)
                elif step.kind == "command":
                    self.run_command(step.command)
                elif step.kind == "sleep":
                    time.sleep(step.seconds)
            except Exception:  # keep the daemon alive on a bad step
                log.exception("step %s failed", step)

    def _fire(self, action: Action) -> None:
        if self._pool is None:
            self._run_steps(action.steps)
        else:
            self._pool.submit(self._run_steps, action.steps)

    # -- event handling --------------------------------------------------

    def _passthrough(self, event: InputEvent) -> None:
        if self.config.passthrough:
            self.emitter.write(event.type, event.code, event.value)
            self._dirty = True

    def handle(self, event: InputEvent) -> None:
        if event.type == ecodes.EV_KEY:
            self._handle_key(event)
        elif event.type == ecodes.EV_REL:
            self._handle_rel(event)
        elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
            if self._dirty:
                self.emitter.syn()
                self._dirty = False
        # EV_MSC (scan codes), EV_ABS etc. are dropped.

    def _handle_key(self, event: InputEvent) -> None:
        action = self.config.mappings.get(Trigger(ecodes.EV_KEY, event.code))
        if action is None:
            self._passthrough(event)
            return
        if event.value == 1:
            if action.holdable:
                self._held[event.code] = action
                self.emitter.press(action.steps[0].keys)
            else:
                self._fire(action)
        elif event.value == 0:
            held = self._held.pop(event.code, None)
            if held is not None:
                self.emitter.release(held.steps[0].keys)
        # value 2 (autorepeat) is ignored; the desktop does its own repeat.

    def _handle_rel(self, event: InputEvent) -> None:
        if event.value == 0:
            return
        direction = 1 if event.value > 0 else -1
        base = HIRES_BASE.get(event.code, event.code)
        action = self.config.mappings.get(Trigger(ecodes.EV_REL, base, direction))
        if action is None:
            self._passthrough(event)
            return
        if base != event.code:
            return  # hi-res duplicate of a mapped wheel event
        for _ in range(abs(event.value)):
            self._fire(action)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
        self._held.clear()
        self.emitter.release_all()
