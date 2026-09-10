# OffPeakClock

A tiny always-on-top Windows widget that shows whether [DeepSeek API](https://api-docs.deepseek.com/quick_start/pricing) pricing is currently **PEAK** or **OFF-PEAK**, with a live countdown to the next switch.

![OffPeakClock](docs/screenshot.png)

## Schedule

DeepSeek off-peak rates are half of peak rates:

| Period   | Hours (UTC)                    | Days           |
| -------- | ------------------------------ | -------------- |
| Peak     | 01:00-04:00 and 06:00-10:00    | Monday-Friday  |
| Off-peak | all other hours                | including all weekend |

The clock shows current UTC and local time, and the countdown shows the next switch in your local time.

## Features

- Live PEAK / OFF-PEAK indicator (red / green)
- Countdown to the next rate switch, in local time
- Always-on-top; drag anywhere to reposition
- Right-click menu: Always on top, Start with Windows, Quit
- Single-instance guard - launching it again does nothing
- Remembers position and settings in `offpeak_clock.json` next to the executable

## Download

Grab `OffPeakClock.exe` from the [latest release](https://github.com/JerkyJesse/deepseek-offpeak-clock/releases/latest) and run it. Windows 10/11, no installer, no dependencies.

## Usage

- **Drag** the widget with the left mouse button to move it.
- **Right-click** for the menu (always on top, start with Windows, quit).
- **Esc** or **Alt+F4** quits when the widget has focus.

## Run from source

```
python offpeak_clock.py
```

Requires Python 3.8+ with tkinter (Windows).

## Tests

```
python -m unittest -v test_offpeak_clock
```

The suite covers the rate schedule boundaries, a minute-by-minute brute-force check of the next-switch calculation across a full weekend, formatting, window-position clamping, and config loading.

## Build

```
pip install pyinstaller
pyinstaller --noconfirm OffPeakClock.spec
```

Produces `dist/OffPeakClock.exe` (single file).

## License

[MIT](LICENSE)
