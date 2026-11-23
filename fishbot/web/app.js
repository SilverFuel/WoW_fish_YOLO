'use strict';

// All text from the app, the log and the assistant is inserted with textContent, never as HTML.

const token = document.querySelector('meta[name="fishbot-token"]').content;
const $ = (id) => document.getElementById(id);

// What the big line at the top says, and the sentence under it.
const STATUS = {
  idle: ['Ready', 'Open the game, then press Start fishing.'],
  starting: ['Getting ready…', ''],
  waiting: ['Waiting for the game', 'Click on the game so it is the window in front. Nothing is pressed until it is.'],
  waitingForMouse: ['Waiting for the mouse', 'Let go of the mouse for a moment. It carries on once the mouse is still.'],
  fishing: ['Fishing', 'Watching for a bite.'],
  test: ['Test cast', 'One cast, then it stops and this page comes back.'],
  practice: ['Practice', 'Watching only. Cast in the game yourself. Nothing is pressed or clicked.'],
  paused: ['Paused', 'Press Resume when you are ready.'],
  stopped: ['Stopping…', ''],
};
const WATCH_NAMES = { full: 'the whole game', center75: 'the middle', center50: 'a small middle' };
const SPOT_NAMES = { both: 'both ways', movement: 'by movement', look: 'by its look' };
const LIVE_PICTURE_MS = 1400;
const MAX_LOG_LINES = 200;
const CHAT_MESSAGES_SENT = 12;
const CHAT_MESSAGE_CHARS = 4000;

let state = null;
let cursor = 0;
let lastLogId = 0;
let lastLogLine = '';
let listening = null;
let startProblems = [];
let pictureTag = '';
let pictureUrl = null;
let pictureAt = 0;
let closed = false;
let clicksShown = '';
let hintShown = false;
let hintMouse = true;
// The three set-up steps. Which ones are finished is remembered by this browser.
const GUIDE_STORE = 'wow-fish-yolo.setup';
const guide = { look: false, cast: false };
let reopened = null;      // a finished step the person asked to do again: 'look' or 'cast'
let castProblem = '';     // why the last test cast could not start
let castPictureId = null; // the click whose picture is shown as the test cast's result
const clickPictures = new Map(); // click id -> object URL of its picture
const chat = [];

async function api(path, body) {
  const options = { headers: { 'X-Fishbot-Token': token } };
  if (body !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    // an empty or non-JSON answer; the status code below decides
  }
  if (!response.ok) {
    throw new Error(data.error || `Something went wrong (${response.status}).`);
  }
  return data;
}

// ----- small helpers -----

function keyLabel(name) {
  if (name === 'space') return 'Space';
  if (name === 'tab') return 'Tab';
  if (/^num\d$/.test(name)) return `Num ${name.slice(3)}`;
  return name.toUpperCase();
}

function clock(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

function timeOfDay(seconds) {
  return new Date(seconds * 1000).toLocaleTimeString([], { hour12: false });
}

function settingText(name, value) {
  if (typeof value === 'boolean') return value ? 'on' : 'off';
  if (name === 'confidence') return `${Math.round(value * 100)}%`;
  if (name === 'scan_area') return WATCH_NAMES[value] || value;
  if (name === 'spot_bites_by') return SPOT_NAMES[value] || value;
  if (name.endsWith('_key') || name.endsWith('_hotkey')) return value ? keyLabel(value) : 'not chosen';
  return String(value);
}

function listOf(texts) {
  return texts.map((text) => {
    const item = document.createElement('li');
    item.textContent = text;
    return item;
  });
}

// ----- drawing the page -----

function setUp(first) {
  $('demo-banner').hidden = first.platform.system !== 'demo';
  // The pretend game has no keyboard or mouse of its own to listen to.
  $('hint').hidden = first.platform.system === 'demo';
  $('hint-demo').hidden = first.platform.system !== 'demo';
  $('version').textContent = `Version ${first.version}`;
  $('platform-notes').replaceChildren(...listOf(first.platform.notes));
  $('platform-notes').hidden = first.platform.notes.length === 0;

  for (const select of document.querySelectorAll('[data-hotkeys]')) {
    for (const name of first.hotkeys) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = keyLabel(name);
      select.append(option);
    }
  }
}

function showSettings(settings) {
  for (const element of document.querySelectorAll('[data-setting]')) {
    if (element === document.activeElement) continue; // do not fight what the person is typing
    const value = settings[element.dataset.setting];
    if (element.type === 'checkbox') element.checked = value;
    else if (element.type === 'radio') element.checked = element.value === value;
    else if ('percent' in element.dataset) element.value = Math.round(value * 100);
    else element.value = value;
  }

  for (const button of document.querySelectorAll('[data-key-setting]')) {
    if (listening && listening.button === button) continue;
    const key = settings[button.dataset.keySetting];
    button.textContent = key ? keyLabel(key) : 'Choose a key';
    button.classList.toggle('unset', !key);
  }

  $('lure-options').hidden = !settings.lure_enabled;
  $('assistant-body').hidden = !settings.assistant_enabled;
  // A running session keeps the keys it started with, so the hint does not change under it.
  if (!state.running || !hintShown) {
    $('hint-pause').textContent = keyLabel(settings.pause_hotkey);
    $('hint-stop').textContent = keyLabel(settings.stop_hotkey);
    hintMouse = settings.pause_on_mouse_move;
    hintShown = true;
  }
  // In practice the mouse is yours throughout, so moving it pauses nothing.
  $('hint-mouse').hidden = !hintMouse || (state.running && state.practice);
}

function showStatus() {
  const running = state.running;
  const waitingForMouse = state.state === 'waiting' && state.waiting_for === 'mouse';
  const testing = state.test && state.state === 'fishing';
  const [title, hint] = (waitingForMouse ? STATUS.waitingForMouse : testing ? STATUS.test : STATUS[state.state]) || STATUS.idle;
  const stoppedItself = !running && state.stopped_by_safeguard;
  let detail = hint;
  // While it fishes, say what just happened: the last cast's outcome is what people want to know.
  if (state.state === 'fishing' && !testing && lastLogLine) detail = lastLogLine;
  if (state.state === 'idle') {
    // A plain "Stopped." after you pressed Stop says nothing new; what to do next is more useful.
    if (state.message && state.message !== 'Stopped.') detail = state.message;
    else if (!state.settings.fishing_key) detail = 'Three quick steps below, then press Start fishing.';
    else if (!guide.look || !guide.cast) detail = 'Finish the steps below, then press Start fishing.';
  }

  // When it stops itself the page says so in the title, rather than a calm "Ready".
  const shownTitle = stoppedItself ? 'Stopped' : title;
  if (stoppedItself && detail.startsWith('Stopped: ')) {
    detail = detail.charAt(9).toUpperCase() + detail.slice(10); // the heading already says Stopped
  }
  $('status-title').textContent = shownTitle;
  $('status-detail').textContent = detail;
  $('status-dot').className = `dot ${stoppedItself ? 'stopped-itself' : state.state}`;
  $('recovery').hidden = !stoppedItself;
  $('recovery-clicks').hidden = (state.clicks || []).length === 0;
  document.title = `${shownTitle} – WoW Fish YOLO`;

  $('start').hidden = running;
  $('practice-line').hidden = running;
  $('pause').hidden = !running;
  $('pause').textContent = state.state === 'paused' ? 'Resume' : 'Pause';
  $('stop').hidden = !running;

  const problem = $('start-problem');
  problem.textContent = running ? '' : startProblems.join(' ');
  problem.hidden = problem.textContent === '';

  // Settings apply when a session starts, so they are locked while one runs.
  $('setup').disabled = running;
  $('setup-locked').hidden = !running || state.test; // during a test cast the step itself says what is happening
  $('more-settings').disabled = running;
  $('more-locked').hidden = !running;
  $('live-block').hidden = !running;

  const stats = state.stats;
  $('stat-looted-label').textContent = state.practice ? 'Would have clicked' : 'Caught';
  $('stat-looted').textContent = state.practice ? stats.practice_clicks : stats.looted;
  $('stat-missed').textContent = state.practice ? '–' : stats.missed; // practice cannot tell when you cast
  $('stat-time').textContent = clock(stats.elapsed_seconds);
}

function addToLog(entries) {
  const list = $('log');
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 30;

  for (const entry of entries) {
    if (entry.id <= lastLogId) continue; // two refreshes can overlap and carry the same lines
    lastLogId = entry.id;
    lastLogLine = entry.message;
    const item = document.createElement('li');
    item.className = entry.level;
    const time = document.createElement('time');
    time.textContent = timeOfDay(entry.time);
    const text = document.createElement('span');
    text.textContent = entry.message;
    item.append(time, text);
    list.append(item);
  }
  while (list.children.length > MAX_LOG_LINES) list.firstElementChild.remove();
  if (atBottom) list.scrollTop = list.scrollHeight;
}

async function loadPicture() {
  pictureAt = Date.now();
  try {
    const response = await fetch('/api/preview.jpg', { headers: { 'X-Fishbot-Token': token } });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    $('preview').src = url;
    if (pictureUrl) URL.revokeObjectURL(pictureUrl);
    pictureUrl = url;
  } catch (error) {
    // the next refresh tries again
  }
}

async function clickPicture(id) {
  if (!clickPictures.has(id)) {
    const response = await fetch(`/api/click.jpg?id=${id}`, { headers: { 'X-Fishbot-Token': token } });
    if (!response.ok) return null;
    clickPictures.set(id, URL.createObjectURL(await response.blob()));
  }
  return clickPictures.get(id);
}

function clickCaption(click) {
  const what = click.practice ? 'Would have clicked here' : 'Clicked here';
  return `${what} at ${timeOfDay(click.time)}. It was ${Math.round(click.score * 100)}% sure this was a bite.`;
}

async function showClicks(clicks) {
  const shown = clicks.map((click) => click.id).join(',');
  if (shown === clicksShown) return;
  clicksShown = shown;

  $('clicks-block').hidden = clicks.length === 0;
  $('clicks-count').textContent = clicks.length ? `(${clicks.length})` : '';

  const items = [];
  for (const click of clicks) {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'click';
    const image = document.createElement('img');
    image.alt = clickCaption(click);
    const url = await clickPicture(click.id);
    if (url) image.src = url;
    const label = document.createElement('span');
    label.textContent = `${timeOfDay(click.time)}${click.practice ? ' · practice' : ''}`;
    button.append(image, label);
    button.addEventListener('click', () => {
      $('click-picture').src = image.src;
      $('click-caption').textContent = clickCaption(click);
      $('click-dialog').showModal();
    });
    item.append(button);
    items.push(item);
  }
  if (shown !== clicksShown) return; // a newer list arrived while the pictures loaded
  $('clicks').replaceChildren(...items);

  // Let go of pictures the app no longer keeps.
  const kept = new Set(clicks.map((click) => click.id));
  for (const [id, url] of clickPictures) {
    if (!kept.has(id)) {
      URL.revokeObjectURL(url);
      clickPictures.delete(id);
    }
  }
}

function show(next) {
  const first = state === null;
  state = next;
  if (first) setUp(next);

  showSettings(next.settings);
  addToLog(next.log); // first, so the main card can say what just happened
  cursor = Math.max(cursor, next.log_cursor);
  showStatus();
  showGuide();
  showClicks(next.clicks);

  // The picture under "What it sees" follows a running session.
  if (next.running && next.preview.startsWith('live-') && next.preview !== pictureTag
      && Date.now() - pictureAt >= LIVE_PICTURE_MS) {
    pictureTag = next.preview;
    loadPicture();
  }
}

// ----- the three set-up steps -----

function loadGuide() {
  try {
    const saved = JSON.parse(localStorage.getItem(GUIDE_STORE)) || {};
    guide.look = saved.look === true;
    guide.cast = saved.cast === true;
  } catch (error) {
    // without storage the steps simply show again next time
  }
}

function saveGuide() {
  try {
    localStorage.setItem(GUIDE_STORE, JSON.stringify(guide));
  } catch (error) {
    // see loadGuide
  }
}

function showGuide() {
  const done = { key: Boolean(state.settings.fishing_key), look: guide.look, cast: guide.cast };
  const steps = ['key', 'look', 'cast'];
  const next = steps.find((name) => !done[name]) || null;

  for (const name of steps) {
    const open = name === next || name === reopened;
    const item = $(`step-${name}`);
    item.classList.toggle('done', done[name] && !open);
    item.classList.toggle('later', !done[name] && !open);
    const body = $(`${name}-body`);
    if (body) body.hidden = !open;
    const again = item.querySelector('[data-reopen]');
    if (again) again.hidden = !done[name] || open;
  }
  $('guide-done').hidden = next !== null || reopened !== null;
  showTestCast();
}

function showTestCast() {
  const testing = state.running && state.test;
  $('test-cast').textContent = testing ? 'Casting…' : 'Do one test cast';

  let text = castProblem;
  let clicked = null;
  if (testing) {
    text = 'Watch the game. It casts once and clicks the bobber when it sees a bite. This page comes back by itself.';
  } else if (!state.running && state.test && !castProblem) {
    if (state.test_result === 'caught') {
      clicked = state.clicks.find((click) => !click.practice) || null;
    } else if (state.test_result === 'no_bite') {
      // The app's own sentence says how close it came, which tells you what to change.
      const why = state.message.replace('The test cast saw no bite.', '').trim();
      text = `It did not see a bite on that cast. ${why} Check that your fishing key is right and that the game looks like the picture in step 2, then try again.`.replace('  ', ' ');
    } else if (state.test_result === 'stopped') {
      text = state.message === 'Stopped.' ? 'The test cast was stopped before it finished.' : state.message;
    }
  }

  const message = $('cast-message');
  message.textContent = text;
  message.hidden = text === '';
  message.classList.toggle('bad', Boolean(castProblem));
  $('cast-result').hidden = clicked === null;
  if (clicked !== null && clicked.id !== castPictureId) {
    castPictureId = clicked.id;
    $('cast-help').hidden = true;
    clickPicture(clicked.id).then((url) => {
      if (url && castPictureId === clicked.id) $('cast-picture').src = url;
    });
  }
}

function finishStep(name) {
  guide[name] = true;
  if (reopened === name) reopened = null;
  saveGuide();
  showGuide();
}

async function refresh() {
  if (closed) return;
  try {
    show(await api(`/api/state?since=${cursor}`));
    $('offline').hidden = true;
  } catch (error) {
    $('offline').hidden = false;
  }
}

// ----- changing settings -----

function setError(name, message) {
  const target = document.querySelector(`[data-error-for="${name}"]`);
  if (target) target.textContent = message ? `${message.charAt(0).toUpperCase()}${message.slice(1)}.` : '';
}

async function save(changes) {
  startProblems = [];
  try {
    const result = await api('/api/settings', changes);
    for (const name of Object.keys(changes)) setError(name, result.errors[name] || '');
    await refresh();
    return result;
  } catch (error) {
    for (const name of Object.keys(changes)) setError(name, error.message);
    return null;
  }
}

function valueOf(element) {
  const name = element.dataset.setting;
  if (element.type === 'checkbox') return element.checked;
  if (typeof state.settings[name] !== 'number') return element.value;
  if (element.value.trim() === '') return '';
  const number = Number(element.value);
  return 'percent' in element.dataset ? number / 100 : number;
}

document.addEventListener('change', (event) => {
  const element = event.target.closest('[data-setting]');
  if (!element || !state) return;
  if (element.type === 'radio' && !element.checked) return;
  save({ [element.dataset.setting]: valueOf(element) });
});

// ----- choosing a key by pressing it -----

const US_POSITIONS = {
  Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']', Backslash: '\\', Semicolon: ';',
  Quote: "'", Comma: ',', Period: '.', Slash: '/', Backquote: '`',
};

function keyName(event) {
  const code = event.code;
  if (/^F([1-9]|1[0-2])$/.test(code)) return code.toLowerCase();
  if (code === 'Space') return 'space';
  if (code === 'Tab') return 'tab';
  if (/^Numpad\d$/.test(code)) return `num${code.slice(6)}`;

  if (state.platform.system === 'macos') {
    // On macOS the bot presses a key by its position, so the key is named by where it sits
    // (as on a US keyboard). Naming it by its character would press the wrong key on other layouts.
    if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
    if (/^Digit\d$/.test(code)) return code.slice(5);
    return US_POSITIONS[code] || null;
  }
  // On Windows the bot looks the character up in the current layout, so the character is the name.
  return event.key && event.key.length === 1 ? event.key.toLowerCase() : null;
}

function stopListening() {
  if (!listening) return;
  listening.button.classList.remove('listening');
  listening = null;
  if (state) showSettings(state.settings);
}

function startListening(button) {
  stopListening();
  listening = { button, name: button.dataset.keySetting };
  setError(listening.name, '');
  button.classList.remove('unset');
  button.classList.add('listening');
  button.textContent = 'Press the key now…';
}

document.addEventListener('keydown', (event) => {
  if (!listening) return;
  event.preventDefault();
  event.stopPropagation();
  if (event.key === 'Escape') return stopListening();
  if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(event.key)) return undefined;

  const field = listening.name;
  const name = keyName(event);
  listening.button.blur(); // otherwise the key's release can click the button again
  stopListening();
  if (!name || !state.keys.includes(name)) {
    return setError(field, 'that key cannot be used. Try a letter or a number');
  }
  return save({ [field]: name });
}, true);

document.addEventListener('pointerdown', (event) => {
  if (listening && !event.target.closest('[data-key-setting]')) stopListening();
});

document.addEventListener('click', (event) => {
  const keyButton = event.target.closest('[data-key-setting]');
  if (keyButton) startListening(keyButton);
});

// ----- the main buttons -----

async function start(practice) {
  startProblems = [];
  const result = await api('/api/start', { practice }).catch((error) => ({ problems: [error.message] }));
  startProblems = result.problems;
  await refresh();
  // Take the person to what is missing, rather than leaving them to look for it.
  if (practice || !startProblems.length) return;
  let missing = null;
  if (!state.settings.fishing_key) missing = 'fishing_key';
  else if (state.settings.lure_enabled && !state.settings.lure_key) missing = 'lure_key';
  if (missing) {
    if (missing === 'lure_key') $('more').open = true;
    const key = document.querySelector(`[data-key-setting="${missing}"]`);
    key.scrollIntoView({ behavior: 'smooth', block: 'center' });
    key.focus();
  }
}

async function testCast() {
  castProblem = '';
  startProblems = [];
  const result = await api('/api/start', { test: true }).catch((error) => ({ problems: [error.message] }));
  castProblem = result.problems.join(' ');
  await refresh();
}

async function act(path, body) {
  try {
    await api(path, body);
  } catch (error) {
    startProblems = [error.message];
  }
  await refresh();
}

$('start').addEventListener('click', () => start(false));
$('practice').addEventListener('click', () => start(true));
$('pause').addEventListener('click', () => act('/api/pause', { paused: state.state !== 'paused' }));
$('stop').addEventListener('click', () => act('/api/stop', {}));

$('quit').addEventListener('click', async () => {
  if (!window.confirm('Quit WoW Fish YOLO? Fishing stops.')) return;
  closed = true;
  await api('/api/quit', {}).catch(() => null);
  $('offline').textContent = 'WoW Fish YOLO has quit. You can close this tab.';
  $('offline').hidden = false;
});

$('check').addEventListener('click', async () => {
  const button = $('check');
  const message = $('check-message');
  const say = (text) => {
    message.textContent = text;
    message.classList.add('bad');
    message.hidden = text === '';
  };

  button.disabled = true;
  button.textContent = 'Checking…';
  say('');
  $('look-result').hidden = true;
  $('look-help').hidden = true;
  try {
    const result = await api('/api/check', {});
    if (result.ok && result.in_front) {
      const response = await fetch('/api/preview.jpg', { headers: { 'X-Fishbot-Token': token } });
      if (!response.ok) throw new Error('The picture could not be loaded. Try again.');
      const picture = $('look-picture');
      if (picture.src) URL.revokeObjectURL(picture.src);
      picture.src = URL.createObjectURL(await response.blob());
      $('look-caption').textContent = result.message;
      $('look-result').hidden = false;
    } else {
      say(result.message);
    }
  } catch (error) {
    say(error.message);
  }
  button.disabled = false;
  button.textContent = 'Check my game';
  await refresh();
});

$('look-yes').addEventListener('click', () => {
  $('look-result').hidden = true;
  finishStep('look');
});
$('look-no').addEventListener('click', () => { $('look-help').hidden = false; });
$('test-cast').addEventListener('click', testCast);
$('cast-yes').addEventListener('click', () => finishStep('cast'));
$('cast-no').addEventListener('click', () => { $('cast-help').hidden = false; });
document.addEventListener('click', (event) => {
  const again = event.target.closest('[data-reopen]');
  if (!again || !state) return;
  reopened = again.dataset.reopen;
  showGuide();
});

// ----- the assistant -----

function chatItem(role, text) {
  const item = document.createElement('li');
  item.className = role;
  item.textContent = text;
  $('chat').append(item);
  $('chat').scrollTop = $('chat').scrollHeight;
  return item;
}

function suggestionBox(answer) {
  const box = document.createElement('div');
  box.className = 'proposal';
  const title = document.createElement('strong');
  title.textContent = 'It suggests these changes';
  const list = document.createElement('ul');

  for (const [name, value] of Object.entries(answer.changes)) {
    const item = document.createElement('li');
    const before = settingText(name, state.settings[name]);
    item.textContent = `${answer.labels[name] || name}: ${before} → ${settingText(name, value)}`;
    list.append(item);
  }
  for (const [name, reason] of Object.entries(answer.rejected)) {
    const item = document.createElement('li');
    item.className = 'rejected';
    item.textContent = `Left out – ${answer.labels[name] || name}: ${reason}`;
    list.append(item);
  }
  box.append(title, list);

  if (Object.keys(answer.changes).length) {
    const buttons = document.createElement('div');
    buttons.className = 'buttons';
    const apply = document.createElement('button');
    apply.type = 'button';
    apply.className = 'button primary small';
    apply.textContent = 'Use these';
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'button small';
    dismiss.textContent = 'No thanks';

    const finish = (text) => {
      const done = document.createElement('span');
      done.className = 'done';
      done.textContent = text;
      buttons.replaceWith(done);
    };
    apply.addEventListener('click', async () => {
      apply.disabled = true;
      const result = await save(answer.changes);
      const failed = result ? Object.keys(result.errors).length : 1;
      finish(failed ? 'Some of them could not be changed.' : state.running ? 'Done. They count from the next start.' : 'Done.');
    });
    dismiss.addEventListener('click', () => finish('Left as it was.'));
    buttons.append(apply, dismiss);
    box.append(buttons);
  }
  return box;
}

async function ask(text) {
  const question = text.trim();
  if (!question || $('chat-send').disabled) return;

  $('suggestions').hidden = true;
  $('chat-send').disabled = true;
  $('chat-input').value = '';
  chat.push({ role: 'user', content: question });
  chatItem('user', question);
  const waiting = chatItem('thinking', 'Thinking… this can take a little while.');

  try {
    const answer = await api('/api/assistant/chat', { messages: chat.slice(-CHAT_MESSAGES_SENT) });
    waiting.remove();
    chat.push({ role: 'assistant', content: answer.reply.slice(0, CHAT_MESSAGE_CHARS) });
    const item = chatItem('assistant', answer.reply);
    if (Object.keys(answer.changes).length || Object.keys(answer.rejected).length) {
      item.append(suggestionBox(answer));
    }
  } catch (error) {
    waiting.remove();
    chat.pop();
    chatItem('failed', error.message);
  }
  $('chat-send').disabled = false;
  $('chat').scrollTop = $('chat').scrollHeight;
}

$('chat-form').addEventListener('submit', (event) => {
  event.preventDefault();
  ask($('chat-input').value);
});

$('chat-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    ask($('chat-input').value);
  }
});

$('suggestions').addEventListener('click', (event) => {
  const button = event.target.closest('.chip-button');
  if (button) ask(button.textContent);
});

$('assistant-test').addEventListener('click', async () => {
  const button = $('assistant-test');
  const result = $('assistant-test-result');
  button.disabled = true;
  result.className = 'quiet';
  result.textContent = 'Checking…';
  try {
    const answer = await api('/api/assistant/test', {});
    result.className = answer.ok ? 'good' : 'bad';
    result.textContent = answer.message;
    $('assistant-models').replaceChildren(...(answer.models || []).map((name) => {
      const option = document.createElement('option');
      option.value = name;
      return option;
    }));
  } catch (error) {
    result.className = 'bad';
    result.textContent = error.message;
  }
  button.disabled = false;
});

// ----- a report to send for help -----

$('report').addEventListener('click', async () => {
  const message = $('report-message');
  try {
    const response = await fetch('/api/report.zip', { headers: { 'X-Fishbot-Token': token } });
    if (!response.ok) throw new Error('The report could not be made. Try again.');
    const now = new Date();
    const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
      + `-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(await response.blob());
    link.download = `wow-fish-yolo-report-${stamp}.zip`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    message.textContent = `Saved as ${link.download}, normally in your Downloads folder. It holds small pictures of the game from `
      + 'the last casts, what it clicked, what it has been doing and your settings.';
  } catch (error) {
    message.textContent = error.message;
  }
  message.hidden = false;
});

// ----- go -----

loadGuide();
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
