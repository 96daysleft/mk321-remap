# mk321-remap

Remap the buttons and knob of the **PCsensor MK321** mini macro keyboard on Linux. No Windows,
no ElfKey, no firmware flashing.

PCsensor's configuration tool (ElfKey) only runs on Windows and macOS. This tool leaves the
keypad's firmware alone and remaps it in software instead. It takes exclusive control of the
keypad's input nodes (your other keyboards aren't affected) and turns its key presses into
whatever you configure:

- **key combos**: `ctrl+shift+t`, held down for as long as you hold the button
- **shell commands**: `notify-send hi`, `playerctl play-pause`, `obs-cmd …`
- **typed text**: snippets, signatures, commands
- **macros**: a sequence of the above, with delays

It works on X11 and Wayland because it uses evdev/uinput, below the display server.

## Supported hardware

| Device | USB id | Status |
|--------|--------|--------|
| PCsensor MK321U (3 keys + knob, USB) | `3553:c010` | tested |
| Other PCsensor "DIY keyboard" / MK424 / MK623 / foot pedals | `3553:xxxx` | should work, set `device:` in the config |
| Any other keyboard or macropad | any | works, set `device:` to its USB id |

Run `mk321-remap list` to see the USB ids of your input devices. If you get it working on
another model, please open a PR adding it to this table.

## Install

Requires Python 3.9+ and a systemd-based desktop.

```bash
git clone https://github.com/96daysleft/mk321-remap.git
cd mk321-remap
./install.sh
```

The installer:

1. installs the `mk321-remap` command (with `pipx` if you have it, otherwise into a private venv),
2. installs a **udev rule** (asks for sudo) that gives your desktop session access to the keypad
   and to `/dev/uinput`, so the tool doesn't need root or the `input` group,
3. copies [`config.example.yaml`](config.example.yaml) to `~/.config/mk321-remap/config.yaml`,
4. enables a **systemd user service** that starts with your desktop session.

**Unplug and replug the keypad** after the first install so the udev rule applies.

Options: `--no-udev`, `--no-service`, `--udev-only`, `--uninstall`.

## Configure

Find out what each button sends:

```console
$ mk321-remap listen
Listening on /dev/input/event10, /dev/input/event11, /dev/input/event13 - press keys, Ctrl+C to quit.

KEY_1                  pressed
KEY_1                  released
KEY_VOLUMEUP           pressed
KEY_VOLUMEUP           released
```

Then map those names in `~/.config/mk321-remap/config.yaml`:

```yaml
device:
  vendor: "3553"
  product: "c010"

passthrough: true   # unmapped keys behave normally

mappings:
  KEY_1: ctrl+c                 # shorthand for a key combo
  KEY_2: ctrl+v

  KEY_3:
    command: playerctl play-pause

  KEY_VOLUMEUP: volumeup
  KEY_VOLUMEDOWN: volumedown

  KEY_MUTE:                     # macro: steps run in order
    - keys: super
    - sleep: 0.3
    - type: "terminal"
    - keys: enter
```

Then apply it:

```bash
mk321-remap check                       # validate
systemctl --user restart mk321-remap    # apply
journalctl --user -u mk321-remap -f     # logs
```

### Config reference

| Key | Meaning |
|-----|---------|
| `device.vendor`, `device.product` | USB id in hex, as strings (`"3553"`) or YAML hex (`0x3553`). Default `3553:c010`. |
| `passthrough` | `true` (default): unmapped keys from the keypad work as normal. `false`: they are swallowed. |
| `mappings` | Trigger → action. |

**Triggers** are the names `mk321-remap listen` prints: evdev key names such as `KEY_1`,
`KEY_VOLUMEUP` or `BTN_LEFT`. If your knob is set up as a scroll wheel, use `REL_WHEEL_UP`,
`REL_WHEEL_DOWN`, `REL_HWHEEL_LEFT` or `REL_HWHEEL_RIGHT`.

**Actions** are either a single step or a list of steps:

| Step | Example | Notes |
|------|---------|-------|
| `keys` | `keys: ctrl+alt+t` or just `ctrl+alt+t` | On its own, it is **held** while the button is held. Inside a list, it is tapped. |
| `type` | `type: "Hello!\n"` | US keyboard layout, printable ASCII plus `\n` and `\t`. |
| `command` | `command: notify-send hi` | Runs through `/bin/sh` in the background, with the service's environment. |
| `sleep` | `sleep: 0.25` | Seconds. |

Key names are case-insensitive. They can be evdev names (`KEY_F13`), the same names without the
prefix (`f13`, `a`, `1`, `volumeup`), or aliases: `ctrl`, `shift`, `alt`, `altgr`, `super`/`meta`/`win`,
`enter`/`return`, `esc`, `del`, `pgup`, `pgdn`, `play`, `next`, `prev`. The full list of key names
is in [`linux/input-event-codes.h`](https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h).

Tip: map buttons to unused keys like `f13`–`f24` and bind those in your desktop's keyboard
shortcut settings or in an app.

## Commands

```
mk321-remap run      # run the remapper (what the service does)
mk321-remap listen   # print names of keys as you press them
mk321-remap list     # list input devices with USB ids (* = MK321)
mk321-remap check    # validate the config
  -c, --config PATH  # default: ~/.config/mk321-remap/config.yaml
  -v, --verbose
```

## Troubleshooting

- **"plugged in but this user cannot read it"**: the udev rule isn't active yet. Run
  `./install.sh --udev-only`, then unplug and replug the keypad. Alternatively, add yourself to
  the `input` group (`sudo usermod -aG input $USER`) and log in again.
- **Commands can't open windows or show notifications**: the user service needs your session's
  environment. Most desktops import it automatically. If yours doesn't, add
  `systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS`
  to your session startup.
- **Service doesn't start at login**: some window managers don't start
  `graphical-session.target`. Change `WantedBy=` in
  `~/.config/systemd/user/mk321-remap.service` to `default.target`, then run
  `systemctl --user reenable mk321-remap`.
- **"already grabbed by another program"**: another instance (or another remapper such as keyd
  or input-remapper) has the keypad. Stop it first.

## How it works

1. Finds the keypad's `/dev/input/event*` nodes by USB id. It skips the absolute-pointer nodes
   the MK321 also exposes.
2. Grabs them with `EVIOCGRAB`, so their events no longer reach the desktop.
3. Creates a virtual keyboard and mouse with `/dev/uinput` and sends the mapped (or passed-through)
   events through it.
4. Releases any held keys and waits for the keypad if it is unplugged.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check . && pytest
```

## License

MIT
