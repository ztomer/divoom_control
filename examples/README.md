# examples/ — `divoom_lib` end-to-end usage

These scripts show the public API of `divoom_lib` from outside the
package. They are intentionally short so you can copy them into your
own project and adapt them. Every script supports `--mac` to target a
specific device; if omitted, the first Divoom device discovered over
BLE is used.

| Script | What it does |
|---|---|
| `discover_and_connect.py` | Scan, connect, print capabilities, disconnect. The smallest working example. |
| `push_static_image.py`   | Resize a PNG/JPG to the device's panel_resolution and push it. |
| `push_animated_gif.py`   | Decode a GIF frame-by-frame, push as 0x8B animation. |
| `set_radio.py`           | Tune FM radio (Tivoo / Tivoo Max / Timoo / Ditoo only). |
| `set_alarm.py`           | Set a single alarm that fires every day at HH:MM. |
| `auto_connect.py`        | Long-lived watcher: connect to a known device whenever it appears in range. |

### What's *not* in here

A weather / temperature example was planned for R13 §2 but couldn't be
written honestly: `divoom_lib/system/temp_weather.py` defines a
`TempWeatherCommand` class (the 0x5F command) but it is **not wired to
the Divoom facade** — `divoom.weather` doesn't exist as an attribute.
Adding it is a 3-line follow-up (mirror the `Music`/`Radio` wiring in
`divoom.py:106-107`) and is tracked in the R13 §2 close-out. The
`Capabilities.has_weather` flag exists in the table but the public
method to call is missing.

A `divoom-control` CLI lives at `divoom_lib/cli.py` and is the
scriptable counterpart to these examples. After installing the
package, run `divoom-control --help` for a single-command interface to
all of the above.

## Companion CLI

For cron / menubar / shell pipeline use, the CLI is much terser than
these Python scripts:

    divoom-control scan
    divoom-control pair --mac AA:BB:CC:DD:EE:FF --type TivooMax
    divoom-control set-volume 8
    divoom-control set-brightness 70
    divoom-control set-radio 87.5
    divoom-control set-alarm 07:30
    divoom-control push-image ~/Pictures/avatar.png
    divoom-control push-gif   ~/Pictures/loading.gif
    divoom-control capabilities --json | jq
    divoom-control identify            # raw manufacturer_data for fingerprinting

`divoom-control pair` is the recommended way to teach the lib which
device sits at a given MAC address — the lib then remembers it
forever in `~/.config/divoom-control/devices.json`, and the
capabilities lookup never has to fall back to the baseline.
