# How it keeps you safe

It presses keys and clicks in a game it cannot really understand. So it only acts when that is safe, it only
clicks what plausibly is a bite, and it stops and says why as soon as things stop looking like fishing.

## What it does about each risk

| What could go wrong | What it does |
|---|---|
| Keys or clicks land in another program | It only presses and clicks while the game is the window in front. Otherwise it waits. |
| You need the mouse back | Move it and it pauses at once, before its next key press or click. `F8` pauses and `F9` stops, as do the buttons on the page and pushing the mouse into a corner of the screen. |
| It mistakes something else for a bite | It ignores anything in the first second after casting, at the edge of the game window, or the wrong size for a splash. If the game window moved, it skips the click. |
| It keeps clicking the same wrong thing | It stops when 3 "bites" in a row come within 2 seconds of casting, or when 4 of its last 8 clicks land on the very same spot. A real bobber does neither. |
| Something keeps interrupting the cast | It stops after 8 casts in 20 seconds instead of hammering the key. |
| Nothing bites any more (wrong key, a window opened, a fight) | It stops after 5 casts in a row with no fish. |
| A loading screen or a disconnect | It stops after a few seconds of black screen. |
| It is left running | You can set a time limit under **More options**. |
| It fails | It stops and says so on the page. The page keeps working. |

**It never tries to fix things by pressing more keys.** In the game, `Esc` closes an open window but opens the
menu when nothing is open, so a blind attempt to recover could make things worse. When in doubt it stops,
presses nothing further, and leaves the game to you.

## When it stops by itself

The page says why and shows three steps:

1. Look at the game. If a window popped up, close it with `Esc`.
2. Open **What it clicked**. It keeps the last six clicks, each with the picture it was looking at and a box
   around what it clicked.
3. Press **Practice first** before fishing again. In practice it only watches: you cast yourself, and it shows
   each spot it would have clicked without pressing or clicking anything. It is also the safest first run.

## What it cannot do

- It cannot see what a click actually hit. One wrong click can still happen before a pattern shows; at worst
  two or three before it stops.
- It cannot see your bags. When they are full it keeps casting and clicking, but nothing more is kept, and
  **Caught** keeps counting, because it counts a catch when it clicks the bobber. Make room first and set a time
  limit. The game can throw away junk for you with a macro: see [Help](help.md#keeping-your-bags-clear-optional).
- If you leave the chat box open in the game, its key presses are typed into it.
- On Windows, bringing the game to the front when you press Start may tap `Alt`. Practice does not do even that.
- All of this is tested against a pretend game and a test window, not the game itself. Do a short run while
  you watch before you trust it.
