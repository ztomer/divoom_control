# examples/ — the retired direct-to-device library, standalone

`divoom_legacy/` is the Python library that used to be the product:
the `Divoom` facade, its BLE / LAN / Bluetooth-Classic transports, the
display / system / media / scheduling / tools command groups and the
Python encoders — 77 modules retired from `divoom_lib` on 2026-09-14
because nothing the shipped product imports reaches them (the `divoomd`
daemon owns every one of those capabilities now). They live here so the
scripts below keep running and the protocol knowledge stays executable.

It depends on the retained `divoom_lib` core (framing, models, transport
interface, auth, the native library) and on nothing else in the repo;
nothing in the repo depends on it, and `tests/test_no_direct_facade_in_production.py`
fails the moment production imports it.

Run from the repo root (`examples/` is put on `sys.path` by running a script
from it; `divoom_lib` comes from the checkout or the installed package):

    python3 examples/discover_and_connect.py
    python3 -m pytest examples/tests -q            # its own suite (1400+ tests)

Every script supports `--mac` to target a specific device; if omitted, the
first Divoom device discovered over BLE is used. Stop `divoomd` first — the
device is single-owner and the daemon holds the connection while it runs.

| Script | What it does |
|---|---|
| `discover_and_connect.py` | Scan, connect, print capabilities, disconnect. The smallest working example. |
| `push_static_image.py`   | Resize a PNG/JPG to the device's panel_resolution and push it. |
| `push_animated_gif.py`   | Decode a GIF frame-by-frame, push as 0x8B animation. |
| `set_radio.py`           | Tune FM radio (Tivoo / Tivoo Max / Timoo / Ditoo only). |
| `set_alarm.py`           | Set a single alarm that fires every day at HH:MM. |
| `set_weather.py`        | Set temperature + icon on the weather channel (`--temperature`, `--weather`). |
| `auto_connect.py`        | Long-lived watcher: connect to a known device whenever it appears in range. |

### Weather

`set_weather.py` drives `divoom.weather.set(temperature, weather_type)`
(the 0x5F command, wired on the `Divoom` facade). Weather types: clear,
cloudy, thunderstorm, rain, snow, fog.

The product's `divoom-control` CLI (`divoom_lib/cli.py`) is a daemon client,
not a user of this library; it is the scriptable counterpart to these examples. After installing the
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
