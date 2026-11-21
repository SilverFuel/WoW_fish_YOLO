# Help

Short answers for when something is not working. The page itself tells you most of this at the moment you
need it.

## It will not start

**Windows says it protected your PC.** Choose **More info**, then **Run anyway**.

**My Mac will not open the starter.** Right-click `Start on Mac.command` and choose **Open**. If that does not
offer to open it, go to System Settings > Privacy & Security, scroll down, and press **Open Anyway**.

**It says it needs Python.** Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/).
On Windows, tick **Add python.exe to PATH** in the installer. Then double-click the starter again.

**Setting up does not finish.** Check your internet connection and try again. If it still fails and you have a
brand new version of Python, install Python 3.13 instead: the newest version is sometimes too new for the parts
this needs.

**The page did not open.** The text window shows its address, normally `http://127.0.0.1:8765/`. Type that into
your browser.

## On a Mac

The first time you press Start, your Mac has to allow two things. Both are under System Settings > Privacy &
Security, and you give them to **Terminal**, because that is what runs the starter. Then start again.

- **Screen Recording**, so it can see the game.
- **Accessibility**, so it can press your fishing key and click.

The page tells you which one is missing.

A few things are different on a Mac:

- Pick a letter or a number for fishing, not an F-key.
- On a Mac laptop, hold `fn` when you press `F8` or `F9`. If they still do nothing, allow **Input Monitoring**
  for Terminal as well. Moving the mouse and the buttons on the page always work.
- Keys are named by where they sit on a US keyboard.

## On Windows

- Run the game in **Windowed** or **Windowed (Fullscreen)** mode.
- If you start the game as administrator, start this the same way: right-click `Start on Windows.bat` and
  choose **Run as administrator**. Otherwise Windows will not let it press keys in the game.

## While fishing

**It says it is waiting for the game.** Click on the game so it is the window in front.

**It never clicks.** Press **Take a look** on the page. You should see your game, zoomed all the way in, with no
buttons or bars. If it still misses bites, open **More options** and lower **How sure it must be** a little.

**It paused and I did not touch the mouse.** Open **More options** and switch off **Let go when I move the
mouse**.

**It stopped with "no fish".** Usually your bags are full or the fishing key is wrong.

**It makes my computer slow.** Open **More options** and choose **Watch the middle**. The bobber then has to
land in the middle of the screen; **Take a look** shows the area as a blue box.

**Nothing happens at all when it presses keys.** There is a self-test that names the part that is not working.
It takes over the keyboard and mouse for a few seconds:

```
python tools/desktop_probe.py
```

Run it with the Python inside the folder: `.venv\Scripts\python` on Windows, `.venv/bin/python` on a Mac.

## The assistant (optional)

The page can include a helper you can ask questions in plain words, such as "fishing is on 1, my lure is on 2 and
lasts 10 minutes". It runs on your own computer and is switched off unless you turn it on. You do not need it.

1. Install [Ollama](https://ollama.com) and get a model: `ollama pull qwen3:8b` (about 5 GB).
2. On the page, open **More options**, switch the assistant on, and press **Check the connection**.

LM Studio works too: use `http://localhost:1234/v1` and the name of the model you loaded. A smaller model such
as `qwen3:4b` answers faster on a modest computer.

What it can and cannot do:

- It sees your settings, the numbers on the page, and the last lines of **What it has been doing**. It cannot see
  your screen.
- It can only suggest. Nothing changes until you press **Use these**.
- It has no part in the fishing itself.
- Nothing is sent anywhere except the address you set.
