# WoW_fish_YOLO

WoW_fish_YOLO is a fishing bot for World of Warcraft. It watches the game window with a small YOLO vision model and
loots when it sees the bobber splash. The model was trained on 2800 screenshots from different regions of the game
in the Cataclysm version.

This is a fork of [Hester60/WoW_fish_YOLO](https://github.com/Hester60/WoW_fish_YOLO). It adds a control page in
your browser, runs on Windows and macOS, and needs far less memory and disk. See
[Changes in this fork](#changes-in-this-fork).

> Automating gameplay is against Blizzard's terms of service and can get an account closed. Use at your own risk.

## Requirements

- Windows 10 or 11, or a recent macOS (14 or newer recommended)
- Python 3.11 or newer (64-bit)
- About 350 MB of disk

## Start

**Windows:** double-click `start.bat`.

**macOS:** double-click `start.command`. If macOS refuses to open it, right-click it and choose Open, or run
`bash start.command` in Terminal.

The first run creates a private Python environment in `.venv` and installs the requirements, which takes a few
minutes. After that the control page opens in your browser. Leave the console window open while you fish.

To set it up by hand instead:

```
python -m venv .venv
.venv\Scripts\activate          (macOS: source .venv/bin/activate)
pip install -r requirements.txt
python bot.py
```

## In the game

1. Turn on **Auto Loot** in the game's settings.
2. Run the game in Windowed or Windowed (Fullscreen) mode.
3. The model was trained in first-person view with the interface hidden. For good results:
    - Zoom in to first-person view and face open water.
    - Hide the interface (ALT + Z or ALT + W depending on your game configuration).

The setup should look like this:

![Exemple](example.png)

## The control page

![The control page](docs/control-page.png)

*The control page, shown here in demo mode with the simulated game.*

1. Click the **Fishing key** button and press the key your Fishing spell is bound to.
2. Press **Check now**. The game comes to the front for a moment and a picture of what the bot sees appears on the
   page. The bobber should be inside the outlined area.
3. Press **Start fishing**.

| Control | Effect |
|---|---|
| `F8` in the game | Pause / resume |
| `F9` in the game | Stop |
| Pause and Stop on the page | The same |
| Mouse into a screen corner | Stop (pyautogui fail-safe) |

The bot only sends keys and clicks while the game is the window in front. If you switch to another application it
waits, and carries on when you come back to the game. `F8` and `F9` can be changed under Advanced.

Settings are saved as you change them and can be changed while the bot is stopped:

| Setting | What it does |
|---|---|
| Fishing key, lure key, lure duration | The keys to press. The lure is re-applied when it runs out. |
| Area to scan | Whole window, or only the middle 75% or 50%. A smaller area needs much less CPU. |
| Looks per second | How often it checks for the splash. 4 to 6 is plenty. |
| CPU threads | Threads used by the detector. |
| Practice mode | Watch only: the bot shows what it would click and sends nothing. |
| Pause when I move the mouse | Take the mouse and the bot lets go until you resume. On by default. |
| Time limit, missed casts | Stop after a number of minutes, or after several casts in a row that catch nothing (5 by default). |
| Cast time, confidence | Under Advanced. The defaults are the tested values. |

## Safeguards, and what to do when something goes wrong

The bot presses keys and clicks in a game it cannot really understand, so it is built to act only when it is safe,
to click only what plausibly is a bite, and to stop and say why as soon as things stop looking like fishing.

| What can go wrong | What the bot does about it |
|---|---|
| Keys or clicks reach another program | It only sends input while the game is in front and has the keyboard. Otherwise it waits. |
| You need the mouse back | Move it and the bot pauses at once, before its next key press or click. Pressing the pause key right after that keeps it paused instead of resuming. `F8` pauses, `F9` stops, as do the buttons on the page and moving the mouse into a screen corner. |
| It mistakes something else for a bite | Before every click: nothing is accepted in the first second after casting, at the edge of the window, or of the wrong size for a splash. If the game window moved after the splash was seen, the click is dropped. |
| It keeps clicking the same wrong thing | It stops when 3 "bites" in a row come within 2 seconds of casting, or when 4 of the last 8 catches are on exactly the same spot, even with real catches in between. A real bobber does neither. |
| Something keeps cutting the cast short | It stops after 8 recasts in 20 seconds instead of hammering the key. |
| Nothing is caught any more (full bags, wrong key, a window opened, combat) | It stops after 5 misses in a row. |
| Loading screen or disconnect | It stops after a few seconds of black screen. |
| It is left running | An optional time limit stops it. |
| The bot itself fails | It stops, reports the error on the page, and the page keeps working. |

**It never tries to repair things by pressing more keys.** In the game, Esc closes an open window but opens the
menu when nothing is open, so a blind "recovery" key press can make things worse. When in doubt the bot stops,
sends nothing further, and leaves the game to you.

When the bot stops itself, the page says why and shows what to do:

1. Look at the game. If a window opened or something got targeted, close or clear it with Esc.
2. Open **Recent clicks**. It keeps the last six clicks with the picture the bot acted on and the box it clicked,
   so you can see what it took for a splash.
3. Fix the cause, then run **Practice mode** before fishing again. In practice mode the bot only watches: you
   cast yourself, and it reports each spot it would have clicked without pressing or clicking anything. It is
   also the safest way to do a first run.

What the safeguards cannot do: the bot cannot see what a click actually hit, so one wrong click can still happen
before a pattern shows; at worst two or three before it stops. Bringing the game to the front when you press Start
may tap ALT on Windows; practice mode does not do even that. Keys go to the chat box if you leave one open.
And like the rest of the bot, the safeguards are tested against a simulated game and a test window, not the game
itself. If "Pause when I move the mouse" triggers when you did not touch the mouse, switch it off under Safety.

### macOS permissions

macOS has to allow two things, under System Settings > Privacy & Security. Grant them to the application you start
the bot from (Terminal, for example), then start the bot again. The bot checks both when you press Start and tells
you which one is missing.

- **Screen Recording**, so the bot can see the game. Without it the bot sees your desktop picture instead.
- **Accessibility**, so it can press keys and click, and can tell whether the game has the keyboard.

If `F8`/`F9` do nothing, also allow **Input Monitoring**; the buttons on the page work either way.

Two things differ from Windows. Keys are named by their position on a US keyboard, because that is how the bot
presses them. And function keys cannot be used for fishing or the lure: when a program presses one, macOS acts as
if fn stayed held, and fn plus a letter is a system shortcut (fn+F is full screen, fn+E the emoji picker).

### If it does not react

```
python tools/desktop_probe.py
```

This opens a small test window and checks each step with the bot's own code: finding the window, bringing it to the
front, capturing it, detecting the splash, pressing a key and right-clicking. The first check that fails names the
part that is not working on your system. It takes over the keyboard and mouse for a few seconds.

## Using less CPU and memory

Detection runs on ONNX Runtime, not PyTorch, and the bot looks a few times a second instead of as fast as it can.
Measured on a 4-core Linux machine against the original version:

| | Original | This fork |
|---|---|---|
| Memory | about 1025 MB | about 300 MB |
| CPU while waiting for a bite | about 3.0 cores | about 1.3 cores (whole window), 0.9 (middle 75%), 0.5 (middle 50%) |
| Loading the model | 8 s | 0.3 s |
| One look at the whole window | 234 ms on 4 cores | about 240 ms on 2 cores |
| Install size | 1.8 GB (per the original README) | about 320 MB |
| Model file | 99 MB | 50 MB |

That machine has a slow server CPU; a desktop CPU does each look faster, which lowers the CPU share further
because the bot only looks five times a second.

To lower CPU use further, choose a smaller **Area to scan**, fewer **Looks per second** or fewer **CPU threads**.
A smaller area keeps the bobber at the size the model was trained on, but the bobber has to land inside it, so use
**Check now** to confirm.

## Assistant (optional)

The page has an assistant that runs on a language model on your own computer. It can explain settings, help with
problems and suggest setting changes from a plain description such as "fishing is on 1, my lure is on 2 and lasts
10 minutes". It is off by default.

1. Install [Ollama](https://ollama.com) and download a model: `ollama pull qwen3:8b` (about 5 GB).
2. On the page, switch the assistant on and press **Test connection**.

Any server with an OpenAI-compatible API works: for LM Studio use `http://localhost:1234/v1` and the name of the
model you loaded. Smaller models such as `qwen3:4b` answer faster on a modest computer.

What it does and does not do:

- It receives your settings, the session's numbers and the last lines of the activity log. It cannot see the screen.
- It can only suggest. Suggestions go through the same checks as the form and nothing changes until you press Apply.
- It is not involved in fishing. A language model is far too slow and heavy to watch the screen several times a
  second, so detection stays with the small vision model.
- Nothing is sent anywhere except the server address you set.

## Without the page

```
python bot.py --console --fishing-key f        fish from the console, stop with CTRL+C
python bot.py --demo                            try the page against a simulated game
python bot.py --help                            all options
```

Demo mode sends no keys or clicks and does not capture your screen. Its "splash" is a synthetic picture made to
trigger the detector, not a real screenshot.

## Tests

```
pip install pytest
pytest tests
```

The tests use a simulated game and the real model, so they run on any system. `.github/workflows/tests.yml` runs
them on Windows, macOS and Linux for every push, and also runs the desktop probe on real Windows and macOS
machines as a report.

## What has and has not been verified

The desktop probe (`tools/desktop_probe.py`) runs the bot's own system code against a test window on real machines
provided by GitHub. In the latest run:

| Machine | Result |
|---|---|
| Windows | 17 of 17 checks |
| Mac, Intel | 19 of 19 checks |
| Mac, Apple Silicon | 19 of 19 checks |

On each of them that includes a whole cast with the real fishing loop: the window is found, brought to the front
from behind another program, captured, the splash is detected, the key is pressed and the right-click lands on the
splash. It also includes the hand-over: when the mouse is moved during a cast, the bot pauses and sends no click,
while its own mouse movement does not make it pause. The mouse pointer is not part of what the bot sees on any of
the three.

Also verified:

- The ONNX model gives the same results as the original PyTorch model (scores within 0.00002).
- The control page, driven in a real browser against the simulated game.
- The test suite, on Windows, macOS and Linux.

Not verified:

- **The game itself.** Every check above uses a test window or a simulated game, because the game cannot run on a
  build machine. Do a short supervised run first and use **Check now**.
- **A real language model.** The assistant is tested against a stand-in server that speaks the same API.
- **Accuracy with the smaller scan areas**, because no real splash screenshots ship with the repository.

Two things the probe found on the Macs are worth knowing. A function key pressed by a program makes macOS treat
the next letter as an fn shortcut; with F5 followed by "f" the test window switched to full screen every time, on
both Macs. That is why function keys are not offered for fishing or the lure there. And in one earlier run on the
Apple Silicon Mac the splash scored 0.77 during the cast, just under the 0.80 needed, where it scored 0.90 moments
before; the following run passed and the cause was not found. The probe now records what it saw just before the
cast, so a repeat can be diagnosed.

## Project layout

| Path | Contents |
|---|---|
| `bot.py` | Entry point |
| `fishbot/engine.py` | The fishing loop |
| `fishbot/detector.py`, `fishbot/vision.py` | Detection and screen capture |
| `fishbot/platforms/` | The Windows, macOS and demo parts |
| `fishbot/service.py`, `fishbot/server.py`, `fishbot/web/` | The control page |
| `fishbot/assistant.py` | The local-LLM assistant |
| `models/splash.onnx` | The detection model |
| `tools/desktop_probe.py` | Checks the system-specific parts against a real window |
| `tools/` (others) | Scripts that rebuild the model and the demo picture from the original `best.pt` |

`best.pt`, the original PyTorch checkpoint, is no longer in the repository; it is in the upstream one.
`tools/export_onnx.py` converts it and checks the result against it.

## Changes in this fork

- Runs on Windows and macOS, with a control page in the browser.
- Detection uses ONNX Runtime: about a third of the memory, under a fifth of the install size and less than half
  the CPU. Optional smaller scan areas cut the work per look by up to four times.
- The bot no longer crashes after 333 casts. The cast loop called itself and ran into Python's recursion limit.
- `F8` pauses and `F9` stops the bot from inside the game. Before, the only way out was CTRL+C in the console.
- Keys and clicks are never sent to another application, and the bot no longer pulls the game back to the front on
  every cast.
- The game window is identified by its exact title and its process, and the captured area is read on every look,
  so maximized, windowed and moved windows work.
- It can stop by itself after a time limit or after several casts in a row that catch nothing.
- Settings are validated and saved between runs.
- An optional assistant that runs on a local language model.

## Improvements

- Training: The bot reliably finds the fish 99% of the time in the original author's setup, but there is room for
  improvement. For example, additional training with screenshots from different regions could enhance accuracy.
- Model size: a nano-sized model trained on the same data would be a few MB and several times faster still.
- Packaging: a single downloadable app per system, so Python does not have to be installed.
