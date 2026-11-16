from evdev import InputEvent, ecodes

from mk321_remap.config import parse_config
from mk321_remap.remapper import Emitter, Remapper

E = ecodes


class FakeUInput:
    def __init__(self):
        self.events = []

    def write(self, etype, code, value):
        self.events.append((etype, code, value))

    def syn(self):
        self.events.append("syn")

    def close(self):
        pass


def make(mappings, passthrough=True):
    ui = FakeUInput()
    commands = []
    cfg = parse_config({"mappings": mappings, "passthrough": passthrough})
    remapper = Remapper(cfg, Emitter(ui, type_delay=0), commands.append, background=False)
    return remapper, ui, commands


def ev(etype, code, value):
    return InputEvent(0, 0, etype, code, value)


def feed(remapper, *events):
    for e in events:
        remapper.handle(e)
        remapper.handle(ev(E.EV_SYN, E.SYN_REPORT, 0))


def test_combo_is_held_while_key_is_held():
    r, ui, _ = make({"KEY_1": "ctrl+c"})
    feed(r, ev(E.EV_KEY, E.KEY_1, 1))
    assert ui.events == [(E.EV_KEY, E.KEY_LEFTCTRL, 1), (E.EV_KEY, E.KEY_C, 1), "syn"]
    ui.events.clear()
    feed(r, ev(E.EV_KEY, E.KEY_1, 2), ev(E.EV_KEY, E.KEY_1, 0))
    assert ui.events == [(E.EV_KEY, E.KEY_C, 0), (E.EV_KEY, E.KEY_LEFTCTRL, 0), "syn"]


def test_unmapped_keys_pass_through():
    r, ui, _ = make({})
    feed(r, ev(E.EV_MSC, E.MSC_SCAN, 7), ev(E.EV_KEY, E.KEY_B, 1))
    assert ui.events == [(E.EV_KEY, E.KEY_B, 1), "syn"]


def test_passthrough_off_drops_unmapped():
    r, ui, _ = make({}, passthrough=False)
    feed(r, ev(E.EV_KEY, E.KEY_B, 1), ev(E.EV_REL, E.REL_WHEEL, 1))
    assert ui.events == []


def test_macro_runs_on_press_only():
    r, ui, cmds = make({"KEY_2": [{"keys": "a"}, {"command": "echo hi"}, {"type": "B"}]})
    feed(r, ev(E.EV_KEY, E.KEY_2, 1), ev(E.EV_KEY, E.KEY_2, 0))
    assert cmds == ["echo hi"]
    keys = [e for e in ui.events if e != "syn"]
    assert keys == [
        (E.EV_KEY, E.KEY_A, 1), (E.EV_KEY, E.KEY_A, 0),
        (E.EV_KEY, E.KEY_LEFTSHIFT, 1), (E.EV_KEY, E.KEY_B, 1),
        (E.EV_KEY, E.KEY_B, 0), (E.EV_KEY, E.KEY_LEFTSHIFT, 0),
    ]


def test_wheel_mapping_fires_per_detent_and_swallows_hires():
    r, ui, cmds = make({"REL_WHEEL_UP": {"command": "up"}})
    r.handle(ev(E.EV_REL, E.REL_WHEEL, 2))
    r.handle(ev(E.EV_REL, E.REL_WHEEL_HI_RES, 240))
    r.handle(ev(E.EV_SYN, E.SYN_REPORT, 0))
    assert cmds == ["up", "up"]
    assert ui.events == []
    # the other direction is not mapped, so it passes through
    feed(r, ev(E.EV_REL, E.REL_WHEEL, -1))
    assert ui.events == [(E.EV_REL, E.REL_WHEEL, -1), "syn"]


def test_close_releases_stuck_keys():
    r, ui, _ = make({"KEY_1": "shift"})
    feed(r, ev(E.EV_KEY, E.KEY_1, 1), ev(E.EV_KEY, E.KEY_X, 1))
    ui.events.clear()
    r.close()
    assert sorted(e for e in ui.events if e != "syn") == sorted(
        [(E.EV_KEY, E.KEY_LEFTSHIFT, 0), (E.EV_KEY, E.KEY_X, 0)]
    )
