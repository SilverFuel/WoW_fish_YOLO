# Details

For the curious. You do not need any of this to use it.

## How it works

A small vision model looks at a picture of the game window a few times a second. When it sees the bobber splash,
the bot right-clicks it, and the game's Auto Loot does the rest. Then it casts again with your fishing key. The
model was trained by the original author on 2800 screenshots from the Cataclysm version of the game, in
first-person view with the interface hidden, which is why the page asks you to set the game up that way.

The page is served by the bot itself, on your own computer only (`127.0.0.1`). Nothing is sent to the internet.

## Without the page

```
python bot.py --console --fishing-key f       fish from the text window; CTRL+C stops
python bot.py --console --practice            only watch
python bot.py --demo                          the page with a pretend game
python bot.py --help                          everything else
```

The pretend game presses nothing, clicks nothing and does not look at your screen. Its "splash" is a made-up
picture that triggers the model, not a real screenshot.

## How light it is

It uses ONNX Runtime instead of PyTorch, and looks five times a second instead of as fast as it can. Measured on
a 4-core Linux machine against the original version:

| | Original | This fork |
|---|---|---|
| Memory | about 1025 MB | about 300 MB |
| Processor while waiting for a bite | about 3.0 cores | about 1.3 cores (whole game), 0.9 (the middle), 0.5 (a small middle) |
| Loading the model | 8 s | 0.3 s |
| Install size | 1.8 GB (per the original README) | about 320 MB |
| Model file | 99 MB | 50 MB |

That machine has a slow server processor; a desktop does each look faster.

Two settings are no longer on the page because almost nobody needs them: looks per second (5) and processor
threads (2). They are still in the settings file, and the assistant can change them if you ask it to go easier
on your computer.

## What has and has not been tested

On real Windows and Mac machines provided by GitHub, for every change:

- **The starter.** `tools/check_launcher.py` starts the app the way you do, including the one-time set-up, waits
  for the page, starts it a second time, and quits.
- **The parts that touch your system.** `tools/desktop_probe.py` runs the bot's own code against a test window:
  finding the window, bringing it to the front, taking its picture, seeing the splash, pressing a key and
  right-clicking, and a whole cast with the real fishing loop. It also checks that moving the mouse pauses it.
- **The test suite**, about 250 tests, on Windows, Mac and Linux.

Also checked: the page in a real browser against the pretend game, and that the ONNX model gives the same answers
as the original PyTorch model (scores within 0.00002).

Not tested:

- **The game itself.** It cannot run on a build machine, so every check uses a test window or the pretend game.
  Do a short run while you watch, and use **Practice first** and **Take a look**.
- **A real language model.** The assistant is tested against a stand-in that speaks the same language.
- **How accurate the smaller watch areas are**, because no real splash screenshots come with this repository.

Two things the Mac tests found are worth knowing. When a program presses a function key, macOS treats the next
letter as an `fn` shortcut, so function keys are not offered for fishing or the lure there. And in one early run
on an Apple Silicon Mac the splash scored 0.77 during the cast, just under the 0.80 needed, where it scored 0.90
moments before; later runs passed and the cause was not found.

## Running the tests yourself

```
pip install pytest
pytest tests
```

## What is where

| Path | What it is |
|---|---|
| `Start on Windows.bat`, `Start on Mac.command` | The starters |
| `bot.py` | Where it begins |
| `fishbot/engine.py` | The fishing loop and its safeguards |
| `fishbot/detector.py`, `fishbot/vision.py` | Seeing the splash |
| `fishbot/platforms/` | The Windows, Mac and pretend-game parts |
| `fishbot/service.py`, `fishbot/server.py`, `fishbot/web/` | The page |
| `fishbot/assistant.py` | The optional assistant |
| `models/splash.onnx` | The vision model |
| `tools/` | The self-tests, and scripts that rebuild the model from the original `best.pt` |

## What changed from the original

- It runs on Windows and Mac, from a page in your browser, with two starters you double-click.
- About a third of the memory, under a fifth of the install size and less than half the processor use.
- It no longer crashes after 333 casts.
- `F8` pauses and `F9` stops from inside the game. Before, the only way out was CTRL+C in the text window.
- It never presses keys or clicks in another program, and no longer pulls the game to the front on every cast.
- Maximized, windowed and moved game windows all work.
- It stops by itself when things go wrong, and shows you what it clicked. See [How it keeps you safe](safeguards.md).
- Your choices are checked and remembered between runs.
- An optional assistant that runs on your own computer.

## Ideas for later

- A single download per system, so Python does not have to be installed first.
- More training pictures from other regions and game versions.
- A smaller model trained on the same data would be a few MB and several times faster.
