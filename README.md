# WoW Fish YOLO

A fishing helper for World of Warcraft. It watches the game for the bobber splash and clicks it for you.
You run it from one simple page in your browser, on Windows or Mac.

> Using a bot is against Blizzard's rules and can get an account closed. Use it at your own risk.

![The page](docs/control-page.png)

## Start in three steps

1. **Get Python 3.13** (it is free) from [python.org](https://www.python.org/downloads/). Choose version
   **3.13**, not the very newest one, which is too new for this. On Windows, tick **Add python.exe to PATH**
   in the installer.
2. **Get this folder.** Press the green **Code** button on this page, choose **Download ZIP**, and unzip it.
3. **Double-click the starter** inside the folder:
   - Windows: `Start on Windows.bat`
   - Mac: `Start on Mac.command`

The first time, it sets itself up. That takes a few minutes. Then the page opens in your browser.
Leave the small text window open while you fish. Double-clicking the starter again just brings the page back.

If your computer will not open the starter, see [Help](docs/help.md).

## On the page

The page walks you through three steps. Each one is a single button:

1. **Pick your fishing key.** Press the key you cast with in the game.
2. **Check your game.** Get the game ready the way the page shows, then press **Check my game**. It shows you
   what it sees, and you say whether that looks right.
3. **Try one cast.** Press **Do one test cast**. It casts once, clicks the bobber, and shows you what it clicked.

Then press **Start fishing**.

You do not have to switch windows yourself: after a check or a test cast, the page comes back to the front on
its own. Using a lure? Switch it on under **More options**. Would you rather it only watched at first?
**Practice first** never presses or clicks.

## The controls

| To do this | Do this |
|---|---|
| Pause | Press `F8` in the game, or just move the mouse |
| Stop | Press `F9` in the game |
| Pause or stop from the page | Use the **Pause** and **Stop** buttons |
| Close it | Press **Quit** on the page |

It only presses keys while the game is the window in front. Switch to something else and it waits for you.

## If it stops by itself

It stops when things no longer look like fishing: nothing bites, the screen goes black, or it keeps clicking
the same spot. The page says why. Then:

1. Look at the game. If a window popped up, close it with `Esc`.
2. If it clicked anything, open **What it clicked** on the page to see what it took for a bite.
3. Press **Practice first** before you fish again.

## More

- [Help](docs/help.md): when something is not working, Mac permissions, the optional assistant
- [How it keeps you safe](docs/safeguards.md): what it checks before it clicks, and what it cannot do
- [Details](docs/details.md): how it works, what has been tested, and what changed from the original

This is a fork of [Hester60/WoW_fish_YOLO](https://github.com/Hester60/WoW_fish_YOLO).
