# mk321-remap

Program and remap the buttons of the **PCsensor MK321** mini macro keyboard on Linux, with no
Windows and no ElfKey.

PCsensor's configuration tool (ElfKey) only runs on Windows and macOS. This tool gives you two
ways to change what the buttons do on Linux:

1. **Store keys on the keypad itself** (`mk321-remap hw`), like ElfKey does. The settings live
   in the keypad's memory and work on any computer, with nothing installed.
2. **Remap in software** (`mk321-remap run`). This can do much more than the keypad can store,
   but it only works while it's running.

### Store keys on the keypad

```console
$ mk321-remap hw read
model: MK321U_V2.0
  layer 1 button 1: f22
  layer 1 button 2: f23
  layer 1 button 3: f24

$ mk321-remap hw set 1 ctrl+c
layer 1 button 1: f22 -> leftctrl+c
```

Each button stores modifiers plus one key: `ctrl+shift+t`, `super+l`, `f13`, `volumeup`.
There are 3 layers (`--layer 2`, `--layer 3`, or `hw read --all-layers`). Every write is
read back and checked. The protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md).
Media keys, mouse actions, text strings and macros aren't supported on the keypad yet; the
software remapper can do those.

### Remap in software

The remapper takes exclusive control of the keypad's input nodes (your other keyboards aren't
affected) and turns its key presses into whatever you configure:

- **key combos**: `ctrl+shift+t`, held down for as long as you hold the button
- **shell commands**: `notify-send hi`, `playerctl play-pause`, `obs-cmd …`
- **typed text**: snippets, signatures, commands
- **macros**: a sequence of the above, with delays

It works on X11 and Wayland because it uses evdev/uinput, below the display server.

## Supported hardware

| Device | USB id | Status |
|--------|--------|--------|
| PCsensor MK321U, firmware `MK321U_V2.0` (3 keys, USB + Bluetooth) | `3553:c010` | tested: `hw` and remapper. Buttons send `F22`/`F23`/`F24` out of the box |
| Other PCsensor "DIY keyboard" / MK424 / MK623 / foot pedals | `3553:xxxx` | remapper should work (set `device:`); `hw` untested, try `hw --product <id> info` |
| Any other keyboard or macropad | any | remapper works, set `device:` to its USB id |

To program the keypad with `hw`, it must be connected by **USB cable** (not Bluetooth).

Run `mk321-remap list` to see the USB ids of your input devices. If you get it working on
another model, please open a PR adding it to this table.

## Install

Requires Python 3.10+ and a systemd-based desktop.

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

KEY_F22                pressed
KEY_F22                released
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
  KEY_F22: ctrl+c               # shorthand for a key combo
  KEY_F23: ctrl+v

  KEY_F24:
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
mk321-remap hw info                 # keypad model / firmware
mk321-remap hw read [--all-layers]  # keys stored on the keypad
mk321-remap hw set BUTTON COMBO [--layer N]   # store a key on the keypad
  -c, --config PATH  # default: ~/.config/mk321-remap/config.yaml
  -v, --verbose
```

## Troubleshooting

- **`hw` says the keypad is not found**: it must be on a USB cable, and not passed through to a VM.
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
