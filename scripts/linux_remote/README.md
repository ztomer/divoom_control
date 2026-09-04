# Linux remote validation (`scripts/linux_remote/`)

Repeatable validation of the native Rust daemon (`divoomd`) on a real Linux host —
the cross-platform (Tier C) check this macOS dev box can't do directly.

## Host

- Default target: `ztomer@192.168.0.33` (Ubuntu 26.04, amd64, kernel 7.x, BlueZ 5.85).
- Access is **key-based** (the box authorizes the dev's SSH key for `ztomer`); no
  password in any script. Override the target with `DIVOOM_LINUX_HOST`.
- `sudo` (for provisioning apt deps) needs a password — pass it via the `SUDO_PASS`
  env var to `run.sh --provision` (never committed).

## Usage

```bash
# one-time (installs rustup + apt build deps): build-essential pkg-config
# libdbus-1-dev libssl-dev
SUDO_PASS=… scripts/linux_remote/run.sh --provision

# every run: rsync the working tree and build+test on the host
scripts/linux_remote/run.sh
```

`run.sh` (local driver) rsyncs the tree, then runs `test_host.sh` on the box:
cargo test `--no-default-features` (core) + `cargo test` (ble/BlueZ) + builds the
libdivoom `.so` + starts the daemon and runs `scan.py` (BLE scan, and a
connect→brightness round-trip if a Divoom device is in range).

## Findings (2026-06-29)

| Check | Result |
|---|---|
| `cargo test --no-default-features` | **70/70 PASS** on Linux |
| `cargo test` (ble, BlueZ backend) | **70/70 PASS** on Linux (first time the btleplug build is *tested*, not just compiled, on Linux) |
| `libdivoom_compact.so` | builds via `cc` on Linux |
| BLE **scan** | **works** — reliably finds in-range devices (Pixoo / Timoo / Tivoo-Max) |
| BLE **connect** | **does NOT work** (see below) |

### The Linux BLE connect problem

These Divoom devices are **dual-mode**: they advertise the classic **SPP profile**
(UUID `00001101-…`, class `0x000408xx`) alongside BLE GATT. CoreBluetooth (macOS)
connects over LE/GATT cleanly. BlueZ routes `Connect()` to **BR/EDR** and fails:

- `org.bluez.Error.BREDR.ProfileUnavailable` — "No more profiles to connect to"
  (reproducible with raw `bluetoothctl connect` — **not** our code), or
- D-Bus `Timeout waiting for reply`.

Notably, `bluetoothctl` shows the device reaching `Connected: yes` /
`ServicesResolved: yes` *before* the profile error — i.e. the LE link briefly comes
up. Candidate directions for a future, properly-verified fix (each needs real
BlueZ work, not a one-liner):

1. Force the LE transport (BlueZ `Device1` has no per-connect transport flag;
   options: pre-set the device, adapter LE-only via `btmgmt`, or a custom D-Bus
   `ConnectProfile`/GATT-only path).
2. Pair/trust the device first (`Paired: no` currently).
3. Patch/upgrade btleplug's BlueZ connect to tolerate `ProfileUnavailable` when the
   GATT link is up (a speculative tolerance was tried and reverted — it moved the
   error to a D-Bus timeout, so it isn't sufficient alone).

Until then: **Linux is validated for build + all hardware-free tests + BLE scan;
real-device control on Linux is an open item.** macOS remains the verified
hardware path.
