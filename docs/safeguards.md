# How it keeps you safe

It presses keys and clicks in a game it cannot really understand. So it only acts when that is safe, it only
clicks what plausibly is a bite, and it stops and says why as soon as things stop looking like fishing.

## What it does about each risk

| What could go wrong | What it does |
|---|---|
| Keys or clicks land in another program | It only presses and clicks while the game is the window in front. Otherwise it waits. |
| You need the mouse back | Move it clearly and it pauses at once, before its next key press or click. A hand just resting on the mouse does not count. `F8` pauses and `F9` stops, as do the buttons on the page and pushing the mouse into a corner of the screen. |
| It mistakes something else for a bite | It ignores anything in the first second after casting, at the edge of the game window, or the wrong size for a splash. If the game window moved, it skips the click. |
| It keeps clicking the same wrong thing | It stops when 3 "bites" in a row come within 2 seconds of casting, or when 4 of its last 8 clicks land on the very same spot. A real bobber does neither. |
| Something keeps interrupting the cast | It stops after 8 casts in 20 seconds instead of hammering the key. |
| Nothing bites any more (wrong key, a window opened, a fight) | It stops after 5 casts in a row with no bite. |
| A loading screen or a disconnect | It stops after a few seconds of black screen. |
| It is left running, or the bags fill up | You can set a limit on time or on catches under **More options**. |
| It fails | It stops and says so on the page. The page keeps working. |

**It never tries to fix things by pressing more keys.** In the game, `Esc` closes an open window but opens the
menu when nothing is open, so a blind attempt to recover could make things worse. When in doubt it stops,
presses nothing further, and leaves the game to you.

## When it stops by itself

The page says why and shows what to do:

1. Look at the game. If a window popped up, close it with `Esc`.
2. If it clicked anything, open **What it clicked**. It keeps the last six clicks, each with the picture it was
   looking at and a box around what it clicked.
3. Press **Practice first** before fishing again. In practice it only watches: you cast yourself, and it shows
   each spot where it sees a bite, without pressing or clicking anything. It is also the safest first run.
   Practice cannot know when you cast, so it shows every bite it sees; a real run is stricter and also ignores
   bites that come too soon after a cast.

## What it cannot do

- It cannot see what a click actually hit. It stops on the patterns in the table above: bites that come too
  soon, or that keep landing on the very same spot. Something that looks like a bite, shows up more than two
  seconds after each cast and moves around would keep being clicked and counted as caught. **What it clicked**
  is how you would notice, so look at it after your first runs.
- By its look, it cannot tell your bobber from someone else's: where other people fish in view, it can click
  their bite instead of yours. By movement it watches only the bobber it found after your cast, which keeps
  theirs out unless one lands in the same moment as yours.
- Spotting a bite by movement has only been tried against a simulation, not the game. Until it has proved
  itself for you, look at **What it clicked** after your first casts.
- It cannot see your bags, or whether a fish reached them. With full bags, or with Auto Loot switched off, it
  keeps casting and clicking, but nothing is kept, and **Caught** keeps counting, because it counts a catch when
  it clicks the bobber. Make room first and set a limit
  on catches or time. The game can throw away junk for you with a macro: see [Help](help.md#keeping-your-bags-clear-optional).
- If you leave the chat box open in the game, its key presses are typed into it.
- On Windows, bringing the game to the front, and bringing the page back after a check or a test cast, may
  tap `Alt`. Practice does not do even that.
- All of this is tested against a pretend game and a test window, not the game itself. Do a short run while
  you watch before you trust it.
