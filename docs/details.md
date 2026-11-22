# Details

For the curious. You do not need any of this to use it.

## How it works

A small vision model looks at a picture of the game window a few times a second. When it sees the bobber splash,
the bot right-clicks it, and the game's Auto Loot does the rest. Then it casts again with your fishing key. The
model was trained by the original author on 2800 screenshots from the Cataclysm version of the game, in
first-person view with the interface hidden, which is why the page asks you to set the game up that way.

The page is served by the bot itself, on your own computer only (`127.0.0.1`). Nothing is sent to the internet.

## Without the page

Use the Python that the starter set up, in place of `python` below: `.venv\Scripts\python` on Windows,
`.venv/bin/python` on a Mac.

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
on your computer. The settings file is `%APPDATA%\WoWFishYOLO\settings.json` on Windows and
`~/Library/Application Support/WoWFishYOLO/settings.json` on a Mac.

## What has and has not been tested

Checked for every change, on machines provided by GitHub. If any of these fails, the change is marked as failed:

- **The starter**, on Windows, a Mac with an Apple chip and an Intel Mac. `tools/check_launcher.py` runs the
  starter file from a command line with the pretend game: the one-time set-up, the page coming up, a second
  start finding the first, and Quit. With a pretend Python it also checks what the starter says when there is
  no Python, or only one that is too new.
- **The parts that touch your system**, on the same three. `tools/desktop_probe.py` runs the bot's own code
  against a test window: finding the window, bringing it to the front, taking its picture, seeing the splash,
  pressing a key and right-clicking, and a whole cast with the real fishing loop. It also checks that moving
  the mouse pauses it, and that the front is handed back to the window you were in. It gets one more try if it fails, because a shared machine's desktop is sometimes slow.
- **The page**, on Linux. `tools/check_page.py` opens it in a real browser against the pretend game and uses it
  the way a person would: about 60 checks.
- **The test suite**, about 260 tests, on Windows, Mac and Linux, with Python 3.11 and 3.13.

Checked once, by hand: the ONNX model gives the same answers as the original PyTorch model (scores within
0.00002).

Not tested:

- **The game itself.** It cannot run on a build machine, so every check uses a test window or the pretend game.
  Do the three set-up steps on the page first, then a short run while you watch.
- **Double-clicking a downloaded copy.** The checks run the starter from a command line. The warnings Windows
  and macOS show for downloaded files, and the browser opening by itself, are not covered.
- **Python 3.12 and 3.14.** The parts this needs are published for them, but the tests run on 3.11 and 3.13.
- **A real language model.** The assistant is tested against a stand-in that speaks the same language.
- **The junk macro** in [Help](help.md#keeping-your-bags-clear-optional), which needs the game.
- **How accurate the smaller watch areas are**, because no real splash screenshots come with this repository.

Two things the Mac tests found are worth knowing. When a program presses a function key, macOS treats the next
letter as an `fn` shortcut, so function keys are not offered for fishing or the lure there. And in one early run
on an Apple Silicon Mac the splash scored 0.77 during the cast, just under the 0.80 needed, where it scored 0.90
moments before; later runs passed and the cause was not found.

## Running the checks yourself

With the Python that the starter set up (`.venv\Scripts\python` on Windows, `.venv/bin/python` on a Mac):

```
python -m pip install pytest
python -m pytest tests                 the test suite
python tools/check_launcher.py         the starter
python tools/check_page.py             the page; needs Node.js with Playwright
```

### The self-test for your own computer

`python tools/desktop_probe.py` names the part that is not working when it cannot see, press or click on your
system. Save your work first and leave the keyboard and mouse alone: for about half a minute it presses keys,
right-clicks, and opens and then closes Notepad (Windows) or TextEdit (Mac). If TextEdit is already open it
leaves it alone and skips that check.

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
| `tools/` | The checks described above, the self-test, and scripts that rebuild the model from the original `best.pt` |

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
