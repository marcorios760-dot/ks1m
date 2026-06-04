# tram_calc.py — Bed Tramming Calculator for KS1M / Rinkhals

Reads `PROBE_ACCURACY` output from the `TRAM_BED` Klipper macro and tells you exactly how many turns (and in which direction) to rotate each bed screw to level the bed.

---

## Requirements

- Python 3.10 or newer (uses `list[dict]` type hint syntax)
- No external dependencies

---

## Setup

### 1. Add the macro to Klipper

Paste the following into your printer config (e.g. `printer.cfg` or a dedicated `macros.cfg`):

```ini
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
```

Probe positions correspond to:

| Corner        | X   | Y   |
|---------------|-----|-----|
| Front-Left    | 30  | 30  |
| Front-Right   | 320 | 30  |
| Rear-Center   | 175 | 320 |

---

## Usage

### Run the macro

In Mainsail / Fluidd / Octoprint console, run:

```
TRAM_BED
```

Wait for all three `PROBE_ACCURACY` blocks to finish.

### Copy the console output

Select and copy **everything** printed after you triggered `TRAM_BED` — you need the lines that contain `PROBE_ACCURACY at X:...` and `average X.XXXX`.

### Run the script

```bash
# Default: T8 lead screws (Kobra S1 Max / KS1M)
python3 tram_calc.py

# M4 bed adjustment screws
python3 tram_calc.py M4

# Custom pitch in mm/turn
python3 tram_calc.py 8
```

Paste the copied console output at the prompt, then press **Ctrl+D** (Linux/macOS) or **Ctrl+Z + Enter** (Windows).

### Supported pitch presets

| Argument | Type        | mm / turn |
|----------|-------------|-----------|
| `T8`     | Lead screw  | 8.0       |
| `T4`     | Lead screw  | 4.0       |
| `T2`     | Lead screw  | 2.0       |
| `M3`     | Bed screw   | 0.5       |
| `M4`     | Bed screw   | 0.7       |
| `M5`     | Bed screw   | 0.8       |
| `M6`     | Bed screw   | 1.0       |

You can also pass any numeric value directly (e.g. `python3 tram_calc.py 1.25`).

---

## Example output

```
=================================================================
  BED TRAM RESULTS (T8, 8.0 mm/turn)
=================================================================
  Corner 1 · Front-Left          z = 2.1234 mm ← do not touch
  Corner 2 · Front-Right         z = 2.0814 mm diff = +0.0420 mm → turn CW 00:19 (0.042 mm) ◄
  Corner 3 · Rear-Center         z = 2.1280 mm diff = -0.0046 mm → OK

  Worst deviation: 0.0420 mm

=================================================================

  CW  = clockwise → raises that corner
  CCW = counter-clockwise → lowers that corner
  HH:MM = turns:minutes, e.g. 00:30 = half a turn, 01:00 = one full turn
```

**Corner 1 is always the reference** — do not adjust it. Adjust the remaining corners per the instructions.

A deviation ≤ 0.05 mm is shown as `OK` and requires no action.

---

## Tips

- Run the macro with the bed and nozzle at printing temperature for the most accurate results.
- After adjusting all screws, re-run `TRAM_BED` and the script to verify.
- The HH:MM notation mirrors Klipper's bed-screws adjust helper: `00:30` = half a turn, `01:15` = one and a quarter turns.
