'use strict';

// All text from the app, the log and the assistant is inserted with textContent, never as HTML.

const token = document.querySelector('meta[name="fishbot-token"]').content;
const $ = (id) => document.getElementById(id);

const STATUS = {
  idle: ['Ready', 'Open the game, then press Start fishing.'],
  starting: ['Starting…', 'Loading the model.'],
  waiting: ['Waiting for the game', 'Click on the game window. Nothing is sent to other windows.'],
  fishing: ['Fishing', 'Watching for the splash.'],
  paused: ['Paused', 'Press Resume here, or the pause key in the game.'],
  stopped: ['Stopping…', ''],
};
const SCAN_NAMES = { full: 'Whole window', center75: 'Middle 75%', center50: 'Middle 50%' };
const LIVE_PREVIEW_MS = 1400;
const MAX_LOG_LINES = 200;
const CHAT_MESSAGES_SENT = 12;

let state = null;
let cursor = 0;
let listening = null;
let startProblems = [];
let previewTag = '';
let previewUrl = null;
let previewAt = 0;
let savedTimer = null;
let closed = false;
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
    throw new Error(data.error || `The app answered with an error (${response.status}).`);
  }
  return data;
}

// ----- formatting -----

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

function settingText(name, value) {
  if (typeof value === 'boolean') return value ? 'on' : 'off';
  if (name === 'confidence') return `${Math.round(value * 100)}%`;
  if (name === 'scan_area') return SCAN_NAMES[value] || value;
  if (name.endsWith('_key') || name.endsWith('_hotkey')) return value ? keyLabel(value) : 'not set';
  return String(value);
}

// ----- rendering -----

function setUp(first) {
  $('platform').textContent = first.platform.label;
  $('demo-banner').hidden = first.platform.system !== 'demo';
  $('version').textContent = `Version ${first.version}`;

  const notes = $('platform-notes');
  for (const note of first.platform.notes) {
    const item = document.createElement('li');
    item.textContent = note;
    notes.append(item);
  }

  for (const select of document.querySelectorAll('[data-hotkeys]')) {
    for (const name of first.hotkeys) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = keyLabel(name);
      select.append(option);
    }
  }
}

function syncSettings(settings) {
  for (const element of document.querySelectorAll('[data-setting]')) {
    if (element === document.activeElement) continue; // do not fight the user's typing
    const value = settings[element.dataset.setting];
    if (element.type === 'checkbox') element.checked = value;
    else if (element.type === 'radio') element.checked = element.value === value;
    else if ('percent' in element.dataset) element.value = Math.round(value * 100);
    else element.value = value;
  }

  for (const button of document.querySelectorAll('[data-key-setting]')) {
    if (listening && listening.button === button) continue;
    const key = settings[button.dataset.keySetting];
    button.textContent = key ? keyLabel(key) : 'Not set';
    button.classList.toggle('unset', !key);
  }

  $('lure-options').hidden = !settings.lure_enabled;
  $('assistant-body').hidden = !settings.assistant_enabled;
  $('checks-value').textContent = $('checks_per_second').value;
  $('hint-pause').textContent = keyLabel(settings.pause_hotkey);
  $('hint-stop').textContent = keyLabel(settings.stop_hotkey);
}

function renderStatus() {
  const [title, hint] = STATUS[state.state] || STATUS.idle;
  $('status-title').textContent = title;
  $('status-detail').textContent = state.state === 'idle' && state.message ? state.message : hint;
  $('status-dot').className = `dot ${state.state}`;

  const problems = state.running ? [] : [...state.problems, ...startProblems];
  const list = $('problems');
  list.replaceChildren(...problems.map((text) => {
    const item = document.createElement('li');
    item.textContent = text;
    return item;
  }));
  list.hidden = problems.length === 0;

  $('start').hidden = state.running;
  $('start').disabled = state.problems.length > 0;
  $('pause').hidden = !state.running;
  $('pause').textContent = state.state === 'paused' ? 'Resume' : 'Pause';
  $('stop').hidden = !state.running;

  $('bot-settings').disabled = state.running;
  $('settings-locked').hidden = !state.running;
  $('check').disabled = state.running;

  const stats = state.stats;
  $('stat-casts').textContent = stats.casts;
  $('stat-looted').textContent = stats.looted;
  $('stat-missed').textContent = stats.missed;
  $('stat-time').textContent = clock(stats.elapsed_seconds);
  $('stat-speed').textContent = stats.inference_ms ? `${stats.inference_ms} ms` : '–';
  if (stats.best_score !== null) setScore(stats.best_score);
}

function setScore(score) {
  $('score-meter').value = score;
  const needed = Math.round(state.settings.confidence * 100);
  $('score-text').textContent = `${Math.round(score * 100)}% · needs ${needed}%`;
}

function appendLog(entries) {
  if (!entries.length) return;
  const list = $('log');
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 30;

  for (const entry of entries) {
    const item = document.createElement('li');
    item.className = entry.level;
    const time = document.createElement('time');
    time.textContent = new Date(entry.time * 1000).toLocaleTimeString([], { hour12: false });
    const text = document.createElement('span');
    text.textContent = entry.message;
    item.append(time, text);
    list.append(item);
  }
  while (list.children.length > MAX_LOG_LINES) list.firstElementChild.remove();
  if (atBottom) list.scrollTop = list.scrollHeight;
}

async function loadPreview() {
  previewAt = Date.now();
  try {
    const response = await fetch('/api/preview.jpg', { headers: { 'X-Fishbot-Token': token } });
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    const image = $('preview');
    image.src = url;
    image.hidden = false;
    $('preview-empty').hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = url;
  } catch (error) {
    // the next refresh tries again
  }
}

function render(next) {
  const first = state === null;
  state = next;
  if (first) setUp(next);

  syncSettings(next.settings);
  renderStatus();
  appendLog(next.log);
  cursor = next.log_cursor;

  if (next.preview && next.preview !== previewTag) {
    const live = next.preview.startsWith('live-');
    if (!live || Date.now() - previewAt >= LIVE_PREVIEW_MS) {
      previewTag = next.preview;
      loadPreview();
    }
  }
}

async function refresh() {
  if (closed) return;
  try {
    render(await api(`/api/state?since=${cursor}`));
    $('offline').hidden = true;
  } catch (error) {
    $('offline').hidden = false;
  }
}

// ----- settings -----

function setError(name, message) {
  const target = document.querySelector(`[data-error-for="${name}"]`);
  if (target) target.textContent = message ? `${message.charAt(0).toUpperCase()}${message.slice(1)}.` : '';
}

function flashSaved() {
  $('saved').textContent = 'Saved';
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { $('saved').textContent = ''; }, 1500);
}

async function save(changes) {
  startProblems = [];
  try {
    const result = await api('/api/settings', changes);
    for (const name of Object.keys(changes)) setError(name, result.errors[name] || '');
    if (Object.keys(result.errors).length === 0) flashSaved();
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

$('checks_per_second').addEventListener('input', (event) => {
  $('checks-value').textContent = event.target.value;
});

// ----- press-to-set keys -----

function keyName(event) {
  const code = event.code;
  if (/^F([1-9]|1[0-2])$/.test(code)) return code.toLowerCase();
  if (code === 'Space') return 'space';
  if (code === 'Tab') return 'tab';
  if (/^Numpad\d$/.test(code)) return `num${code.slice(6)}`;
  // For everything else use the character, so other keyboard layouts send the key they show.
  return event.key && event.key.length === 1 ? event.key.toLowerCase() : null;
}

function stopListening() {
  if (!listening) return;
  listening.button.classList.remove('listening');
  listening = null;
  if (state) syncSettings(state.settings);
}

function startListening(button) {
  stopListening();
  listening = { button, name: button.dataset.keySetting };
  setError(listening.name, '');
  button.classList.remove('unset');
  button.classList.add('listening');
  button.textContent = 'Press a key…';
}

document.addEventListener('keydown', (event) => {
  if (!listening) return;
  event.preventDefault();
  event.stopPropagation();
  if (event.key === 'Escape') return stopListening();
  if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(event.key)) return undefined;

  const field = listening.name;
  const name = keyName(event);
  stopListening();
  if (!name || !state.keys.includes(name)) {
    return setError(field, 'that key cannot be used here. Try a letter, a number or F1 to F12');
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

// ----- controls -----

async function act(path, body) {
  try {
    return await api(path, body);
  } catch (error) {
    startProblems = [error.message];
    return null;
  } finally {
    await refresh();
  }
}

$('start').addEventListener('click', async () => {
  startProblems = [];
  $('start').disabled = true;
  const result = await api('/api/start', {}).catch((error) => ({ problems: [error.message] }));
  startProblems = result.problems;
  await refresh();
});

$('pause').addEventListener('click', () => act('/api/pause', { paused: state.state !== 'paused' }));
$('stop').addEventListener('click', () => act('/api/stop', {}));

$('quit').addEventListener('click', async () => {
  if (!window.confirm('Close the app? Fishing stops.')) return;
  closed = true;
  await api('/api/quit', {}).catch(() => null);
  $('offline').textContent = 'The app is closed. You can close this tab.';
  $('offline').hidden = false;
});

$('check').addEventListener('click', async () => {
  const button = $('check');
  const message = $('check-message');
  const show = (text, bad) => {
    message.textContent = text;
    message.classList.toggle('bad', bad);
    message.hidden = false;
  };

  button.disabled = true;
  button.textContent = 'Checking…';
  show('The game comes to the front for a moment. Switch back here to see the result.', false);
  try {
    const result = await api('/api/check', {});
    show(result.message, !result.ok);
    if (result.best_score !== undefined) setScore(result.best_score);
  } catch (error) {
    show(error.message, true);
  }
  button.textContent = 'Check now';
  await refresh();
});

// ----- assistant -----

function chatItem(role, text) {
  const item = document.createElement('li');
  item.className = role;
  item.textContent = text;
  $('chat').append(item);
  $('chat').scrollTop = $('chat').scrollHeight;
  return item;
}

function proposalBox(answer) {
  const box = document.createElement('div');
  box.className = 'proposal';
  const title = document.createElement('strong');
  title.textContent = 'Suggested settings';
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
    item.textContent = `Not applied – ${answer.labels[name] || name}: ${reason}`;
    list.append(item);
  }
  box.append(title, list);

  if (Object.keys(answer.changes).length) {
    const buttons = document.createElement('div');
    buttons.className = 'buttons';
    const apply = document.createElement('button');
    apply.type = 'button';
    apply.className = 'button primary small';
    apply.textContent = 'Apply';
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'button small';
    dismiss.textContent = 'Dismiss';

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
      finish(failed ? 'Some settings could not be applied.' : state.running ? 'Applied. Takes effect the next time you start.' : 'Applied.');
    });
    dismiss.addEventListener('click', () => finish('Dismissed.'));
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
  const waiting = chatItem('thinking', 'Thinking… a local model can take a while.');

  try {
    const answer = await api('/api/assistant/chat', { messages: chat.slice(-CHAT_MESSAGES_SENT) });
    waiting.remove();
    chat.push({ role: 'assistant', content: answer.reply });
    const item = chatItem('assistant', answer.reply);
    if (Object.keys(answer.changes).length || Object.keys(answer.rejected).length) {
      item.append(proposalBox(answer));
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
  result.className = 'muted';
  result.textContent = 'Connecting…';
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
