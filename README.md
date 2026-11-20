# WoW_fish_YOLO

WoW_fish_YOLO is a bot for World of Warcraft utilizing a pre-trained YOLO model. This project is developed in Python
with Ultralytics and has been trained on a dataset of 2800 screenshots from different regions of the game in the
Cataclysm version.

This is a fork of [Hester60/WoW_fish_YOLO](https://github.com/Hester60/WoW_fish_YOLO) with stability and safety
fixes. See [Changes in this fork](#changes-in-this-fork).

> Automating gameplay is against Blizzard's terms of service and can get an account closed. Use at your own risk.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer (64-bit)
- A good CPU (or a GPU with CUDA: install a CUDA build of torch and set `DEVICE` in `bot.py`)
- About 2 GB of disk

## Setup

1. Clone the repository:

```
git clone https://github.com/SilverFuel/WoW_fish_YOLO.git
cd WoW_fish_YOLO
```

2. Create a virtual environment and install the required packages:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

1. Ensure World of Warcraft is open. The bot looks for the game client's window, titled "World of Warcraft".
   Windowed and windowed-fullscreen both work, and the window can be moved while the bot runs.
2. Enable auto-loot in the game settings.
3. The bot has been trained in first-person view. For optimal results:
    - Switch to first-person view.
    - Hide the user interface (use ALT + Z or ALT + W depending on your game configuration).

The setup should look like this:

![Exemple](example.png)

## Usage

To run the bot, execute:

```
python bot.py
```

It asks for the key bound to your fishing spell and, optionally, a lure key and how long the lure lasts. Use key
names such as `f`, `1`, `f5`, `space` or `num1`; a name the bot cannot press is refused and asked again.

| Control | Effect |
|---|---|
| `F8` | Pause / resume |
| `F9` | Stop |
| `CTRL+C` in the console | Stop |
| Mouse into a screen corner | Stop (pyautogui fail-safe) |

The bot only sends keys and clicks while the game window is in front. If you switch to another application it
waits, and carries on when you come back to the game. `F8` and `F9` are reserved, so do not bind them to fishing
or the lure; they can be changed at the top of `bot.py`.

## Tests

The fishing loop is tested against a stand-in for the game, so the tests run on any operating system:

```
pip install pytest colorama pyfiglet
pytest test_bot.py
```

## Changes in this fork

- The bot no longer crashes after 333 casts. The cast loop called itself and ran into Python's recursion limit;
  it is now a plain loop.
- `F8` pauses and `F9` stops the bot from inside the game. Before, the only way out was CTRL+C in the console.
- Keys and clicks are never sent to another application, and the bot no longer pulls the game back to the front
  on every cast.
- The game window is identified by its exact title and its process, so a browser tab or folder with the same
  name is not picked up.
- The captured area is the game's drawing area, read on every frame. Maximized, windowed and moved windows work,
  and the title bar and borders are no longer part of the screenshot.
- Key names and the lure duration are validated instead of failing silently or crashing.
- `requirements.txt` is UTF-8 and lists the direct dependencies only, so current, patched versions of torch and
  the rest are installed.

## Improvements

- Training: The bot reliably finds the fish 99% of the time in my setup, but there is room for improvement. For example, additional training with screenshots from different regions could enhance accuracy.
- Model size: `best.pt` is a YOLOv8m checkpoint that still contains its optimizer state (99 MB). A nano model exported to ONNX would be a few MB and several times faster on CPU.
