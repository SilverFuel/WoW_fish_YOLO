'use strict';

// All text from the app, the log and the assistant is inserted with textContent, never as HTML.

const token = document.querySelector('meta[name="fishbot-token"]').content;
const $ = (id) => document.getElementById(id);

// What the big line at the top says, and the sentence under it.
const STATUS = {
  idle: ['Ready', 'Open the game, then press Start fishing.'],
  starting: ['Getting ready…', ''],
  waiting: ['Waiting for the game', 'Click on the game so it is the window in front. Nothing is pressed until it is.'],
  fishing: ['Fishing', 'Watching for a bite.'],
  practice: ['Practice', 'Watching only. Cast in the game yourself. Nothing is pressed or clicked.'],
  paused: ['Paused', 'Press Resume when you are ready.'],
  stopped: ['Stopping…', ''],
};
const WATCH_NAMES = { full: 'the whole game', center75: 'the middle', center50: 'a small middle' };
const LIVE_PICTURE_MS = 1400;
const MAX_LOG_LINES = 200;
const CHAT_MESSAGES_SENT = 12;
const CHAT_MESSAGE_CHARS = 4000;

let state = null;
let cursor = 0;
let lastLogId = 0;
let listening = null;
let startProblems = [];
let pictureTag = '';
let pictureUrl = null;
let pictureAt = 0;
let closed = false;
let clicksShown = '';
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
  $('hint-pause').textContent = keyLabel(settings.pause_hotkey);
  $('hint-stop').textContent = keyLabel(settings.stop_hotkey);
  $('hint-mouse').hidden = !settings.pause_on_mouse_move;
}

function showStatus() {
  const running = state.running;
  const [title, hint] = STATUS[state.state] || STATUS.idle;
  const stoppedItself = !running && state.stopped_by_safeguard;
  let detail = hint;
  if (state.state === 'idle') {
    if (state.message) detail = state.message;
    else if (!state.settings.fishing_key) detail = 'Three quick steps below, then press Start fishing.';
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
  $('setup-locked').hidden = !running;
  $('more-settings').disabled = running;
  $('more-locked').hidden = !running;
  $('check').disabled = running;
  if (running) $('check-message').hidden = true; // what Take a look said is about an older picture

  const stats = state.stats;
  $('stat-looted-label').textContent = state.practice ? 'Would have clicked' : 'Caught';
  $('stat-looted').textContent = state.practice ? stats.practice_clicks : stats.looted;
  $('stat-missed').textContent = stats.missed;
  $('stat-time').textContent = clock(stats.elapsed_seconds);
}

function addToLog(entries) {
  const list = $('log');
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 30;

  for (const entry of entries) {
    if (entry.id <= lastLogId) continue; // two refreshes can overlap and carry the same lines
    lastLogId = entry.id;
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
    $('preview-frame').hidden = false;
    $('preview-empty').hidden = true;
    $('preview-key').hidden = false;
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
  showStatus();
  addToLog(next.log);
  cursor = Math.max(cursor, next.log_cursor);
  showClicks(next.clicks);

  if (next.preview && next.preview !== pictureTag) {
    const live = next.preview.startsWith('live-');
    if (!live || Date.now() - pictureAt >= LIVE_PICTURE_MS) {
      pictureTag = next.preview;
      loadPicture();
    }
  }
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
  if (!state.settings.fishing_key && startProblems.length) {
    const key = document.querySelector('[data-key-setting="fishing_key"]');
    key.scrollIntoView({ behavior: 'smooth', block: 'center' });
    key.focus();
  }
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
  const say = (text, bad) => {
    message.textContent = text;
    message.classList.toggle('bad', bad);
    message.hidden = false;
  };

  button.disabled = true;
  button.textContent = 'Looking…';
  say('The game is coming to the front for a moment. Come back here to see the picture.', false);
  try {
    const result = await api('/api/check', {});
    say(result.message, !result.ok);
  } catch (error) {
    say(error.message, true);
  }
  button.textContent = 'Take a look';
  await refresh();
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

// ----- go -----

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
