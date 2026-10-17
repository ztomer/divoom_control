#!/usr/bin/env python3
"""derive_panel_features.py -- what the vendor app enables for each model (P4.1).

The daemon's per-model feature table (`divoomd/src/panel_features.rs`) is a
PORT, and a port is only as good as its provenance. This is the provenance: it
RUNS the decompiled vendor app's own `DeviceTypeEnum.setDeviceMode` for every
model and reads back the switches it leaves set -- speaker, SD card,
temperature sensor, Wi-Fi architecture, clock style and pixel class.

Executing the method rather than reading it is the point. `setDeviceMode` is
550 lines of nested if/else with local aliases (`fmModeEnum = SupportFm` set in
one branch and applied in another, a default reset at the top that later
branches partly undo). A hand transcription of it is exactly how
`divoom_lib.models.capabilities` came to assert 18 wrong resolutions; a
transcription the JVM checks cannot drift that way.

How: the method body is lifted verbatim out of `DeviceFunction.java` and
compiled inside a stub of its surroundings -- each `...Enum` class becomes a
real Java enum (constants read from the same file) with a recorded mode, and
`DeviceFunction.j()` returns an object with the same public fields. Nothing of
the vendor app runs except that one method.

The decompiled sources are local-only (`references/` is never published), so
this runs on a machine that has them:

    python3 tools/derive_panel_features.py            # JSON, one row per model
    python3 tools/derive_panel_features.py --rust     # the Rust table rows

`tests/test_panel_features_parity.py` compares its output with the daemon's
table whenever the sources and a JDK are present.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = (REPO / "references" / "apk" / "decompiled_src" / "sources" / "com" / "divoom"
          / "Divoom" / "utils" / "DeviceFunction" / "DeviceFunction.java")

# The switches reported, each as (output key, enum class, the constant that
# means "on"). Only switches whose CONSUMERS in the vendor app were read and
# say what the key claims:
#
#   speaker      MusicEnum: gates the Bluetooth-audio pairing prompt
#                (bluetooth/i.java), the Voice screen and the audio rows of
#                the Bluetooth settings -- the panel is a Bluetooth speaker.
#   sd_card      SdEnum: gates the SD card as a music source (MusicMainFragment)
#                and the SD path of firmware update (HotUpdateHandle).
#   temp_sensor  TempSensorEnum: gates the indoor-temperature reading on the
#                weather screens.
#   wifi         WifiBlueArchEnum.WifiArchMode: the panel is driven over Wi-Fi
#                (MQTT) rather than Bluetooth.
#
# Deliberately NOT reported, because the switch does not mean its name:
# FmModeEnum gates only "FM as the alarm / sleep sound" (AlarmAddFragment,
# SleepMainFragment) -- the FM screen itself is not decided per model -- so it
# is no "has a radio" flag; AlarmEnum has no consumer at all; MicEnum has one,
# inside the TiVi light settings.
FLAGS = (
    ("speaker", "MusicEnum", "SupportMusic"),
    ("sd_card", "SdEnum", "SupportSd"),
    ("temp_sensor", "TempSensorEnum", "TempSensor"),
    ("wifi", "WifiBlueArchEnum", "WifiArchMode"),
)
PIXELS = {"DevicePixel16": 16, "DevicePixel32": 32, "DevicePixel64": 64,
          "DevicePixel128": 128, "DevicePixel256": 256}


def available() -> str | None:
    """Why this cannot run here, or None when it can."""
    if not SOURCE.is_file():
        return f"decompiled sources not present ({SOURCE.relative_to(REPO)})"
    if not (shutil.which("javac") and shutil.which("java")):
        return "no JDK (javac/java) on PATH"
    return None


def _enum_constants(src: str) -> dict[str, list[str]]:
    """Every `public static final class XEnum {` and its constant names."""
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"public static final class (\w+) \{\n((?:\s+\w+\(\d+\)[,;]\n)+)", src):
        out[m.group(1)] = re.findall(r"^\s+(\w+)\(\d+\)", m.group(2), re.M)
    return out


def _method_body(src: str) -> str:
    start = src.index("public static void setDeviceMode(DeviceTypeEnum deviceTypeEnum) {")
    start = src.index("{", start) + 1
    depth = 1
    i = start
    while depth:
        c = src[i]
        depth += c == "{"
        depth -= c == "}"
        i += 1
    return src[start:i - 1]


def _fields(src: str) -> list[str]:
    """DeviceFunction's own instance fields, as declarations for the stub."""
    head = src[: src.index("public static final class")]
    decls = re.findall(r"^\s+(?:public|private) (boolean|int|String) (f\d+\w*)(?: = [^;]+)?;", head, re.M)
    return [f"public {t} {n};" for t, n in decls]


def _java(src: str) -> str:
    enums = _enum_constants(src)
    if "DeviceTypeEnum" not in enums or "FmModeEnum" not in enums:
        raise SystemExit("DeviceFunction.java changed shape: enum classes not found")
    stubs = []
    for name, consts in enums.items():
        if name == "DeviceTypeEnum":
            continue
        stubs.append(
            f"enum {name} {{ {', '.join(consts)};\n"
            f"  static {name} mode = {consts[0]};\n"
            f"  static void setMode({name} e) {{ mode = e; }}\n"
            f"  static void setMode({name} e, int i) {{ mode = e; }}\n"
            f"  static void setClockModeEnum({name} e) {{ mode = e; }}\n"
            f"  static void setBlueMode({name} e) {{ mode = e; }}\n"
            f"  static void setGalleyMode({name} e) {{ mode = e; }}\n"
            f"  static void setNewMode() {{ mode = {name}.values()[{name}.values().length - 1]; }}\n"
            f"  static {name} getMode() {{ return mode; }}\n}}\n")
    flags = ", ".join(f'"{k}", {cls}.mode == {cls}.{on}' for k, cls, on in FLAGS)
    fields = "\n  ".join(_fields(src))
    return f"""
import java.util.*;
public class Harness {{
{''.join(stubs)}
static class DeviceFunction {{
  static int f11383y0 = 40;
  static String f11382x0 = "DeviceFunction";
  static DeviceFunction inst = new DeviceFunction();
  static DeviceFunction j() {{ return inst; }}
  {fields}
}}
static class J {{ static void C(Object o) {{}} static void B(Object o) {{}} }}
static class DesignSendModel {{ static void clearWifiSendMd5() {{}} }}
static class AbstractC0519k {{ static void d(Object a, Object b) {{}} }}
enum DeviceTypeEnum {{ {', '.join(enums['DeviceTypeEnum'])};
  static DeviceTypeEnum device_type;
  static void setDeviceMode(DeviceTypeEnum deviceTypeEnum) {{
{_method_body(src)}
  }}
}}
static String row(Object... kv) {{
  StringBuilder b = new StringBuilder("{{");
  for (int i = 0; i < kv.length; i += 2) {{
    if (i > 0) b.append(",");
    Object v = kv[i + 1];
    b.append('"').append(kv[i]).append("\\":");
    b.append(v instanceof Boolean ? v.toString() : "\\"" + v + "\\"");
  }}
  return b.append("}}").toString();
}}
public static void main(String[] a) {{
  List<String> rows = new ArrayList<>();
  for (DeviceTypeEnum t : DeviceTypeEnum.values()) {{
    DeviceTypeEnum.setDeviceMode(t);
    rows.add(row("model", t.name(), {flags},
                 "clock", ClockModeEnum.mode.name(), "pixels", DevicePixelModelEnum.mode.name()));
  }}
  System.out.println("[" + String.join(",", rows) + "]");
}}
}}
"""


def derive() -> list[dict]:
    """One row per `DeviceTypeEnum` constant, in the APK's order."""
    why = available()
    if why:
        raise SystemExit(why)
    src = SOURCE.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Harness.java"
        path.write_text(_java(src), encoding="utf-8")
        for argv in (["javac", "-nowarn", "-d", tmp, str(path)], ["java", "-cp", tmp, "Harness"]):
            out = subprocess.run(argv, check=False, capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL)
            if out.returncode:
                raise SystemExit(f"{argv[0]} failed:\n{out.stderr[-4000:]}")
    rows = json.loads(out.stdout)
    for r in rows:
        r["pixels"] = PIXELS[r["pixels"]]
    return rows


def rust_rows(rows: list[dict]) -> str:
    """The rows of `panel_features::FEATURES`, flags as `|`-joined consts."""
    lines = []
    for r in rows:
        on = " | ".join(k.upper() for k, _, _ in FLAGS if r[k]) or "NONE"
        lines.append(f'    ("{r["model"]}", {on}, "{r["clock"]}"),')
    return "\n".join(lines)


def main() -> int:
    rows = derive()
    print(rust_rows(rows) if "--rust" in sys.argv[1:] else json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
