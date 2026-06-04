# tram_calc.py — Bed Tramming Calculator for KS1M / Rinkhals

Reads `PROBE_ACCURACY` output from the `TRAM_BED` Klipper macro and tells you exactly how many turns (and in which direction) to rotate each bed screw to level the bed.

---

## Requirements

- Python 3.10 or newer (uses `list[dict]` type hint syntax)
- No external dependencies

---

## Setup

### 1. Add the macro to Klipper

Paste the following into your printer config printer.custom.conf

```gcode
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

Select and copy **everything** printed after you triggered `TRAM_BED` — you need the lines that contain `PROBE_ACCURACY at X:...` and `average X.XXXX`. For example:
```
$ TRAM_BED
21:39:25 
PROBE_ACCURACY at X:30.000 Y:30.000 Z:10.000 (samples=3 retract=2.000 speed=4.0 lift_speed=4.0)
21:39:33 
probe accuracy results: maximum 0.225000, minimum 0.221667, range 0.003333,average 0.223056, median 0.222500, standard deviation 0.001416
21:39:34 
PROBE_ACCURACY at X:320.000 Y:30.000 Z:10.000 (samples=3 retract=2.000 speed=4.0 lift_speed=4.0)
21:39:44 
probe accuracy results: maximum 0.336667, minimum 0.335000, range 0.001667,average 0.335833, median 0.335000, standard deviation 0.000680
21:39:44 
PROBE_ACCURACY at X:175.000 Y:320.000 Z:10.000 (samples=3 retract=2.000 speed=4.0 lift_speed=4.0)
21:39:56 
probe accuracy results: maximum 0.034167, minimum 0.030000, range 0.004167,average 0.031944, median 0.034167, standard deviation 0.001712
```

### Run the script

```bash
# Default: T8 lead screws (Kobra S1 Max / KS1M)
python3 tram_calc.py

# M4 bed adjustment screws
python3 tram_calc.py M4
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

## Before / After

Running `TRAM_BED` and adjusting the screws per the calculator output reduces bed deviation significantly.

<table>
<tr>
<td align="center"><b>Before</b> — range 2.65 mm</td>
<td align="center"><b>After</b> — range 0.41 mm</td>
</tr>
<tr>
<td><img src="img/Screenshot%202026-06-03%20214108.png" alt="Before tramming"></td>
<td><img src="img/Screenshot%202026-06-03%20225347.png" alt="After tramming"></td>
</tr>
</table>

# How to adjust

## Z-axis Belt Replacement

Full official guide: [Kobra S1 Max – Z-axis Belt Replacement Guide](https://wiki.anycubic.com/en/fdm-3d-printer/kobra-s1-max-combo/z-axis-belt-replacement-guide)

**Tools required:** H2.0 Allen key

### Removal

1. Turn off the printer and disconnect power.
2. Lay the printer on its side to access the bottom.
3. **Secure the pulleys! Image below**.
4. Remove the hook tension spring to fully release belt tension follow official guide: [Kobra S1 Max – Z-axis Belt Replacement Guide](https://wiki.anycubic.com/en/fdm-3d-printer/kobra-s1-max-combo/z-axis-belt-replacement-guide)
5. Move pulleys acording to the script output (be sure about CW, CCW = bed up / bed down)
6. Reasamble
7. After adjusting all screws, re-run `TRAM_BED` and the script to verify.

### Pulley securing tip

When routing the belt around the three bottom pulleys, the pulleys tend to shift and fall out of position. **Secure all three pulleys with a strip of tape before threading the belt** — this keeps them locked in place while you work and makes routing significantly easier. Remove the tape once the belt is fully seated and the tensioner is tightened.
![Three bottom pulleys taped in place](img/printer_belt.png)
