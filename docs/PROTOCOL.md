# PCsensor MK321U configuration protocol

These notes come from a USB capture of PCsensor's ElfKey (Windows) reading and writing an
**MK321U_V2.0** (`3553:c010`, "DIY keyboard"). Anything marked *unknown* was seen in the
capture but its meaning hasn't been confirmed.

## Transport

- USB interface **1** (HID). It has an interrupt OUT endpoint `0x02` and an IN endpoint `0x82`.
  On Linux it is the `hidraw` node whose `HID_PHYS` ends in `input1`.
- Every packet is **9 bytes**: report id `0x01` followed by 8 bytes of payload. Short
  payloads are padded with zeros.
- ElfKey waits about 20 ms between packets.
- Two kinds of payload:
  - **command**: `01 <op> <args…>`. The leading `0x01` is required. Without it the keypad
    ignores the packet.
  - **data**: `08 <type> <modifiers> <keycode> 00 00 00 00`

This is the same idea as the protocol in [rgerganov/footswitch](https://github.com/rgerganov/footswitch)
and [prasslee/mk321bt-keypad](https://github.com/prasslee/mk321bt-keypad), except the MK321U needs
the extra `0x01` in front of each command.

## Commands

| Payload sent | Reply | Meaning |
|---|---|---|
| `01 83 08` | two packets of ASCII, e.g. `MK321U_V` `2.0` | identify model and firmware |
| `01 82 08 <slot>` | `08 <type> <mods> <key> 00…` | read the key stored in a slot |
| `01 81 08 <slot>`, then a data packet | none | write a slot |
| `01 d1` | `d1 00…` | sent after every write and at startup. Probably commit/save (*unknown*). |
| `01 d3` | `d3 01 00…` | *unknown*, probably the active layer |
| `01 c1 00 <n>` for n = 1..8 | `ff ff ff ff ff ff ff ff` | *unknown*. Read at startup, all `ff` on a stock keypad (empty macro slots?) |

ElfKey's write sequence for one button:

```
01 | 01 81 08 01 00 00 00 00     select slot 1 for writing
01 | 08 81 00 3a 00 00 00 00     key type 0x81, no modifiers, HID usage 0x3a (F1)
01 | 01 82 08 01 00 00 00 00     read it back  ->  08 81 00 3a ...
01 | 01 d1 00 00 00 00 00 00     commit (?)    ->  d1 ...
```

## Slots

| Layer | Button 1 | Button 2 | Button 3 | Factory value |
|---|---|---|---|---|
| 1 | `01` | `02` | `03` | F22, F23, F24 |
| 2 | `11` | `12` | `13` | d, e, f |
| 3 | `21` | `22` | `23` | g, h, i |

How you switch layers on the keypad hasn't been confirmed yet.

## Data packet

| Byte | Meaning |
|---|---|
| 0 | length, always `08` |
| 1 | type: `0x81` = key (written by ElfKey), `0x01` = key (factory default on unused layers) |
| 2 | modifier bits: `01` LCtrl, `02` LShift, `04` LAlt, `08` LWin, `10` RCtrl, `20` RShift, `40` RAlt, `80` RWin |
| 3 | USB HID keyboard usage (`0x04` = a, `0x3a` = F1, `0x68–0x73` = F13–F24) |
| 4–7 | `00` |

Mouse actions, media keys, text strings and macros aren't captured yet. Captures of ElfKey
setting those would let `mk321-remap hw` support them. See below.

## Contributing a capture

1. On Windows, install Wireshark with USBPcap. Or capture from a Linux host with `usbmon`
   while the keypad is passed through to a VM.
2. Start the capture, open ElfKey, and set **one** thing at a time, writing down what and when.
3. Share **only the keypad's packets**. Filter on its device address first: a full USB
   capture can include anything typed on other keyboards.
