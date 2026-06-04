#!/usr/bin/env python3
"""
Bed tramming calculator for KS1M / Rinkhals.

Usage:
  python3 tram_calc.py        → T8 lead screws (default, Kobra S1 Max)
  python3 tram_calc.py M4     → M4 bed adjustment screws
  python3 tram_calc.py 8      → 8 mm/turn (custom)

Paste the full PROBE_ACCURACY output from TRAM_BED macro, then press Ctrl+D.

Pitch reference — bed screws: M3=0.5  M4=0.7  M5=0.8  M6=1.0 mm/turn
               — lead screws: T8=8.0  T4=4.0  T2=2.0  mm/turn

Macro:
[gcode_macro TRAM_BED]
description: Probe 3 lead screw positions (3 samples each) to guide manual bed leveling
gcode:
  G28
  SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=60
  SET_HEATER_TEMPERATURE HEATER=extruder TARGET=140
  M190 S60
  M109 S140
  G1 Z10 F600
  G1 X30 Y30 F6000
  PROBE_ACCURACY SAMPLES=3
  G1 Z10 F600
  G1 X320 Y30 F6000
  PROBE_ACCURACY SAMPLES=3
  G1 Z10 F600
  G1 X175 Y320 F6000
  PROBE_ACCURACY SAMPLES=3
  G1 Z10 F600
  G1 X175 Y175 F6000
"""

import re
import sys
import math

NAMED_PITCH = {
    "M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0,
    "T8": 8.0, "T4": 4.0, "T2": 2.0,
}

DEFAULT_PITCH_NAME = "T8"

CORNER_LABELS = {
    (30,  30):  "Front-Left",
    (320, 30):  "Front-Right",
    (175, 320): "Rear-Center",
}


def strip_line(line: str) -> str:
    line = re.sub(r"^\d{2}:\d{2}:\d{2}\s*", "", line)
    line = re.sub(r"^\$\s*", "", line)
    return line.strip()


def corner_label(x: float, y: float) -> str:
    """Round to nearest 5 mm to tolerate small float differences"""
    key = (round(x / 5) * 5, round(y / 5) * 5)
    return CORNER_LABELS.get(key, f"X{x:.0f} Y{y:.0f}")


def parse_output(text: str) -> list[dict]:
    """Return list of {name, x, y, avg} dicts in parse order."""
    corners = []
    for line in text.splitlines():
        line = strip_line(line)
        if not line:
            continue
        pa_match = re.search(r"PROBE_ACCURACY at X:([\d.]+)\s+Y:([\d.]+)", line)
        if pa_match:
            x, y = float(pa_match.group(1)), float(pa_match.group(2))
            corners.append({"name": corner_label(x, y), "x": x, "y": y, "avg": None})
            continue
        avg_match = re.search(r"average\s+([-\d.]+)", line)
        if avg_match and corners and corners[-1]["avg"] is None:
            corners[-1]["avg"] = float(avg_match.group(1))
    return [c for c in corners if c["avg"] is not None]


def turns_to_hhmm(turns: float) -> str:
    """Convert fractional turns to HH:MM (turns:clock-minutes) Klipper style."""
    full = math.trunc(turns)
    minutes = round((turns - full) * 60)
    if minutes == 60:
        full += 1
        minutes = 0
    return f"{full:02d}:{minutes:02d}"


def calculate(corners: list[dict], pitch: float, pitch_label: str) -> None:
    ref = corners[0]
    sep = "=" * 65

    lines = [
        "",
        sep,
        f"  BED TRAM RESULTS ({pitch_label}, {pitch} mm/turn)",
        sep,
        f"  Corner 1 · {ref['name']:20s} z = {ref['avg']:.4f} mm ← do not touch",
    ]

    worst = 0.0
    for i, c in enumerate(corners[1:], start=2):
        diff = ref["avg"] - c["avg"]
        turns = diff / pitch
        direction = "CW" if diff >= 0 else "CCW"
        hhmm = turns_to_hhmm(abs(turns))
        if abs(diff) <= 0.05:
            status, flag = "OK", ""
        else:
            status = f"turn {direction} {hhmm} ({abs(diff):.3f} mm)"
            flag = " ◄"
        lines.append(
            f"  Corner {i} · {c['name']:20s} z = {c['avg']:.4f} mm"
            f" diff = {diff:+.4f} mm → {status}{flag}"
        )
        worst = max(worst, abs(diff))

    lines += [
        "",
        f"  Worst deviation: {worst:.4f} mm",
        "",
        sep,
        "",
        "  CW = clockwise → raises that corner",
        "  CCW = counter-clockwise → lowers that corner",
        "  HH:MM = turns:minutes, e.g. 00:30 = half a turn, 01:00 = one full turn",
    ]

    print("\n".join(lines))


def main() -> None:
    pitch = NAMED_PITCH[DEFAULT_PITCH_NAME]
    pitch_label = DEFAULT_PITCH_NAME

    for arg in sys.argv[1:]:
        arg_up = arg.upper()
        if arg_up in NAMED_PITCH:
            pitch, pitch_label = NAMED_PITCH[arg_up], arg_up
        else:
            try:
                pitch = float(arg)
                pitch_label = f"{pitch} mm/turn"
            except ValueError:
                pass

    print(
        f"Pitch: {pitch_label} ({pitch} mm/turn)\n"
        "Paste the PROBE_ACCURACY output, then press Ctrl+D (or Ctrl+Z + Enter on Windows):\n"
    )

    try:
        text = sys.stdin.read()
    except KeyboardInterrupt:
        sys.exit(0)

    corners = parse_output(text)
    if len(corners) < 2:
        print(
            "ERROR: Could not find at least 2 corners with probe averages.\n"
            "Make sure you paste the full console output from TRAM_BED,\n"
            "including the 'PROBE_ACCURACY at X:...' and 'average X.XXXX' lines."
        )
        sys.exit(1)

    calculate(corners, pitch, pitch_label)


if __name__ == "__main__":
    main()
