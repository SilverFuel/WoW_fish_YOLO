// Uses the page in a real browser the way a person would, against the pretend game.
// Run it through tools/check_page.py, which starts the app and a stand-in model server first.
//
//   node tools/page_test.js <page address> <model server address> [folder for screenshots]
//
// Needs Playwright: npm install playwright, then npx playwright install chromium.
const { chromium } = require('playwright');
const URL = process.argv[2], LLM = process.argv[3], OUT = process.argv[4];
const picture = (page, name) => (OUT ? page.screenshot({ path: `${OUT}/${name}`, fullPage: true }) : null);
let failed = 0;
const check = (ok, label, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  [' + extra + ']' : ''}`); if (!ok) failed++; };
const text = (page, sel) => page.locator(sel).first().innerText();
const waitText = async (page, sel, want, ms = 20000) => { try { await page.waitForFunction(([s, w]) => document.querySelector(s).innerText.trim() === w, [sel, want], { timeout: ms }); return true; } catch { return false; } };
const waitFor = async (page, fn, arg, ms = 8000) => { try { await page.waitForFunction(fn, arg, { timeout: ms }); return true; } catch { return false; } };
const saved = (page) => page.evaluate(async () => (await (await fetch('/api/state', { headers: { 'X-Fishbot-Token': document.querySelector('meta[name="fishbot-token"]').content } })).json()));
const errorFor = (page, name) => waitFor(page, (n) => document.querySelector(`[data-error-for="${n}"]`).innerText.length > 0, name, 5000);

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 900, height: 1100 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  const problems = [];
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') problems.push(`${m.type()}: ${m.text()}`); });
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('dialog', d => d.accept());

  // ---- first visit ----
  await page.goto(URL);
  check(await waitText(page, '#status-title', 'Ready'), 'the page opens and says Ready');
  check((await text(page, '#status-detail')) === 'Three quick steps below, then press Start fishing.', 'a newcomer is pointed at the three steps', await text(page, '#status-detail'));
  check(await page.locator('#demo-banner').isVisible(), 'the demo says it is a pretend game');
  const visibleControls = await page.evaluate(() => [...document.querySelectorAll('main [data-setting], main [data-key-setting]')].filter((e) => e.offsetParent !== null && e.checkVisibility()).map((e) => e.dataset.setting || e.dataset.keySetting));
  check(JSON.stringify(visibleControls) === JSON.stringify(['fishing_key']), 'only one choice is in view: the fishing key', visibleControls.join(', '));
  check(await page.evaluate(() => document.querySelector('#step-look').classList.contains('later') && document.querySelector('#look-body').hidden && document.querySelector('#cast-body').hidden), 'the later steps wait their turn');
  check(!(await page.locator('#more').evaluate((d) => d.open)) && !(await page.locator('#activity').evaluate((d) => d.open)) && await page.locator('#clicks-block').isHidden(), 'everything else starts folded away');
  const words = await page.evaluate(() => document.body.innerText + ' ' + [...document.querySelectorAll('details')].map((d) => d.textContent).join(' '));
  const jargon = ['CPU', 'thread', 'onfidence', 'scan', 'afeguard', 'inference', 'detector', 'threshold', 'splash', 'fail-safe', 'hotkey'].filter((w) => words.includes(w));
  check(jargon.length === 0, 'no technical words anywhere on the page', jargon.join(', '));
  await picture(page, '01-first-visit.png');

  // ---- the pretend game has no keys of its own, and the page does not pretend otherwise ----
  check(await page.locator('#hint').isHidden() && (await text(page, '#hint-demo')) === 'In this demo, use the buttons above to pause and stop.', 'the demo does not promise keys that do nothing');

  // ---- practice presses nothing, so it works before any key is chosen ----
  await page.click('#practice');
  check(await waitText(page, '#status-title', 'Practice', 15000), 'Practice first works before a key is chosen');
  check((await text(page, '#stat-missed')) === '–', 'practice does not count casts it cannot see');
  await page.click('#stop');
  check(await waitText(page, '#status-title', 'Ready', 8000), 'and stops again');

  // ---- pressing Start too early takes you to what is missing ----
  await page.click('#start');
  check(await waitText(page, '#start-problem', 'Pick your fishing key first.', 5000), 'Start without a key says what to do first');
  check(await page.evaluate(() => document.activeElement && document.activeElement.dataset.keySetting === 'fishing_key'), 'and puts you on the key button');

  // ---- choose the key by pressing it ----
  await page.click('[data-key-setting="fishing_key"]');
  check((await text(page, '[data-key-setting="fishing_key"]')) === 'Press the key now…', 'the key button waits for a key press');
  await page.keyboard.press('F8');
  await errorFor(page, 'fishing_key');
  check((await text(page, '[data-error-for="fishing_key"]')).includes('reserved'), 'a key that is already in use is refused, with the reason', await text(page, '[data-error-for="fishing_key"]'));
  await page.click('[data-key-setting="fishing_key"]');
  await page.keyboard.press('Escape');
  check((await text(page, '[data-key-setting="fishing_key"]')) === 'Choose a key', 'Escape backs out');
  await page.click('[data-key-setting="fishing_key"]');
  await page.keyboard.press('Digit1');
  check(await waitText(page, '[data-key-setting="fishing_key"]', '1', 5000), 'pressing 1 picks 1');
  check(await page.locator('#start-problem').isHidden() && (await text(page, '#status-detail')) === 'Finish the steps below, then press Start fishing.', 'the page points at the remaining steps');
  check(await page.evaluate(() => document.querySelector('#step-key').classList.contains('done') && !document.querySelector('#look-body').hidden && document.querySelector('#cast-body').hidden), 'the key step is ticked and the next step opens');

  // ---- lure: an option now, not a first-run step ----
  await page.click('#more > summary');
  await page.check('#lure_enabled');
  await page.waitForSelector('#lure-options', { state: 'visible' });
  await page.click('[data-key-setting="lure_key"]');
  await page.keyboard.press('Digit1');
  await errorFor(page, 'lure_key');
  check((await text(page, '[data-error-for="lure_key"]')).includes('different keys'), 'the lure cannot share the fishing key');
  await page.click('[data-key-setting="lure_key"]');
  await page.keyboard.press('Digit2');
  check(await waitText(page, '[data-key-setting="lure_key"]', '2', 5000), 'pressing 2 picks the lure key');
  await page.fill('#lure_minutes', '999'); await page.press('#lure_minutes', 'Tab');
  await errorFor(page, 'lure_minutes');
  check((await text(page, '[data-error-for="lure_minutes"]')).includes('between 1 and 240'), 'a number that is out of range is explained', await text(page, '[data-error-for="lure_minutes"]'));
  await page.fill('#lure_minutes', '15'); await page.press('#lure_minutes', 'Tab');
  check(await waitFor(page, () => document.querySelector('[data-error-for="lure_minutes"]').innerText === ''), 'and the message goes away once it is fine');
  await page.uncheck('#lure_enabled');

  // ---- more options ----
  check(await page.locator('input[name="spot_bites_by"][value="both"]').isChecked(), 'a bite is spotted both ways unless you choose otherwise');
  await page.locator('input[name="spot_bites_by"][value="movement"]').check({ force: true });   // the test cast below goes by movement alone
  await page.locator('input[name="scan_area"][value="center75"]').check({ force: true });
  await page.waitForTimeout(600);
  let now = (await saved(page)).settings;
  check(now.scan_area === 'center75' && now.fishing_key === '1' && now.lure_key === '2' && now.lure_minutes === 15 && now.lure_enabled === false, 'choices are saved as they are made', JSON.stringify({ watch: now.scan_area, key: now.fishing_key }));
  check(await page.locator('#pause_on_mouse_move').isChecked(), 'letting go when the mouse moves is on unless switched off');

  await page.click('#more > summary');

  // ---- step 2: check my game ----
  await page.click('#check');
  check(await waitFor(page, () => !document.querySelector('#look-result').hidden && document.querySelector('#look-picture').naturalWidth === 640, null, 20000), 'Check my game shows what it sees, on this page');
  check((await text(page, '#look-caption')) === 'This is what it sees. The bobber has to land inside the blue box.', 'and says what to look for', await text(page, '#look-caption'));
  await page.click('#look-no');
  check(await page.locator('#look-help').isVisible(), 'Not yet says what to fix');
  await page.click('#look-yes');
  check(await page.evaluate(() => document.querySelector('#step-look').classList.contains('done') && document.querySelector('#look-body').hidden && !document.querySelector('#cast-body').hidden), 'Yes ticks the step and opens the last one');

  // ---- step 3: one test cast ----
  await page.click('#test-cast');
  check(await waitText(page, '#status-title', 'Test cast', 15000), 'Do one test cast starts a test cast');
  check(await waitFor(page, () => !document.querySelector('#cast-result').hidden && document.querySelector('#cast-picture').naturalWidth > 0, null, 40000), 'it comes back with a picture of what it clicked');
  const afterTest = await saved(page);
  check(afterTest.stats.casts === 1 && afterTest.stats.looted === 1 && afterTest.running === false && afterTest.settings.stop_after_catches === 0, 'it was exactly one cast, and your own limits are untouched', JSON.stringify({ casts: afterTest.stats.casts, caught: afterTest.stats.looted }));
  check(afterTest.settings.spot_bites_by === 'movement' && afterTest.clicks[0].score === 0, 'by movement alone it found the bobber and the bite, without the trained model', JSON.stringify({ by: afterTest.settings.spot_bites_by, modelScore: afterTest.clicks[0].score }));
  check((await text(page, '#status-detail')) === 'The test cast is done.' && await page.locator('#recovery').isHidden(), 'the page says the test cast is done, without an alarm');
  await picture(page, '01b-test-cast.png');
  await page.click('#cast-no');
  check(await page.locator('#cast-help').isVisible(), 'No says what to check');
  await page.click('#cast-yes');
  check(await page.locator('#guide-done').isVisible() && (await text(page, '#guide-done')).includes('Start fishing'), 'Yes finishes set-up and points at Start fishing');
  await page.reload();
  check(await waitText(page, '#status-title', 'Ready') && await waitFor(page, () => !document.querySelector('#guide-done').hidden && document.querySelector('#look-body').hidden), 'set-up stays finished when the page is opened again');
  await page.click('#more > summary');
  await page.locator('input[name="spot_bites_by"][value="both"]').check({ force: true });        // back to both ways for the rest
  await page.waitForTimeout(600);
  await page.click('#more > summary');

  // ---- fishing ----
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click('#start');
  check(await waitText(page, '#status-title', 'Fishing', 15000), 'Start leads to Fishing');
  check(await waitFor(page, () => /^Cast \d+\. Waiting for a bite/.test(document.querySelector('#status-detail').innerText), null, 10000), 'the main card says what it is doing right now', await text(page, '#status-detail'));
  check(await page.locator('#stop').isVisible() && await page.locator('#pause').isVisible() && await page.locator('#start').isHidden() && await page.locator('#practice-line').isHidden(), 'Pause and Stop take the place of Start');
  check(await page.evaluate(() => document.querySelector('#setup').disabled && document.querySelector('#more-settings').disabled) && await page.locator('#setup-locked').isVisible(), 'set-up is locked while it fishes');
  check(await waitFor(page, () => !document.querySelector('#live-block').hidden && document.querySelector('#preview').naturalWidth > 0, null, 15000), 'What it sees shows the live picture while it fishes');
  check(await waitFor(page, () => Number(document.querySelector('#stat-looted').innerText) >= 1, null, 40000), 'it catches a fish in the pretend game', `caught ${await text(page, '#stat-looted')}`);
  await page.waitForTimeout(1600);
  await page.evaluate(() => window.scrollTo(0, 0));
  await picture(page, '02-fishing.png');
  await page.click('#activity > summary');
  const lines = await page.locator('#log li span').allInnerTexts();
  check(lines.some((l) => /^Got a bite and clicked the bobber/.test(l)) && !lines.some((l) => /x:|y:|\d{3},/.test(l)), 'the activity list is plain sentences without numbers to decode', lines.slice(0, 3).join(' | '));
  await page.click('#activity > summary');

  check(await waitFor(page, () => !document.querySelector('#clicks-block').hidden && document.querySelectorAll('#clicks li img').length >= 1 && document.querySelector('#clicks li img').naturalWidth > 0), 'What it clicked appears once it has clicked', await text(page, '#clicks-block > summary'));
  await page.click('#clicks-block > summary');
  await page.click('#clicks li button');
  check(await page.locator('#click-dialog').evaluate((d) => d.open) && /^Clicked here at .* It was \d+% sure this was a bite\.$/.test(await text(page, '#click-caption')), 'a click opens bigger with a plain caption', await text(page, '#click-caption'));
  await page.click('#click-dialog button');
  await page.click('#clicks-block > summary');

  await page.click('#pause');
  check(await waitText(page, '#status-title', 'Paused', 8000) && (await text(page, '#pause')) === 'Resume', 'Pause leads to Paused and offers Resume');
  await page.click('#pause');
  check(await waitText(page, '#status-title', 'Fishing', 8000), 'Resume carries on');
  await page.click('#stop');
  check(await waitText(page, '#status-title', 'Ready', 8000) && (await text(page, '#status-detail')) === 'Open the game, then press Start fishing.', 'Stop leads back to Ready and says what to do next');
  check(await page.locator('#recovery').isHidden() && await page.evaluate(() => !document.querySelector('#setup').disabled), 'no alarm after stopping it yourself, and set-up unlocks');
  check(await page.locator('#live-block').isHidden(), 'What it sees goes away when it is not running');

  // ---- a limit you set yourself is a calm stop, not an alarm ----
  await page.click('#more > summary');
  await page.fill('#stop_after_catches', '1'); await page.press('#stop_after_catches', 'Tab');
  await page.waitForTimeout(600);
  await page.click('#more > summary');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click('#start');
  check(await waitFor(page, () => document.querySelector('#status-detail').innerText === 'Stopped: you reached your limit of 1 catch.', null, 40000), 'a catch limit stops it after that many catches', await text(page, '#status-detail'));
  check((await text(page, '#status-title')) === 'Ready' && await page.locator('#recovery').isHidden(), 'and that is a calm stop: Ready, no alarm');
  await page.click('#more > summary');
  await page.fill('#stop_after_catches', '0'); await page.press('#stop_after_catches', 'Tab');
  await page.waitForTimeout(600);
  await page.click('#more > summary');

  // ---- it stops on its own and says what to do ----
  await page.click('#more > summary');
  // By its look alone and needing 95%, nothing counts: the pretend bite only looks 90% like one.
  await page.locator('input[name="spot_bites_by"][value="look"]').check({ force: true });
  await page.fill('#confidence', '95'); await page.press('#confidence', 'Tab');
  await page.fill('#cast_seconds', '5'); await page.press('#cast_seconds', 'Tab');
  await page.fill('#stop_after_misses', '1'); await page.press('#stop_after_misses', 'Tab');
  await page.waitForTimeout(600);
  await page.click('#more > summary');
  await page.click('[data-reopen="cast"]');
  await page.click('#test-cast');
  check(await waitFor(page, () => document.querySelector('#cast-message').innerText.startsWith('It did not see a bite on that cast.'), null, 40000), 'a test cast with no bite says so and what to check', await text(page, '#cast-message'));
  check(await page.locator('#recovery').isHidden() && (await text(page, '#status-title')) === 'Ready', 'and that is not an alarm either');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click('#start');
  check(await waitFor(page, () => !document.querySelector('#recovery').hidden, null, 40000) && (await text(page, '#status-detail')).startsWith('No bite on the last cast.'), 'it stops by itself when nothing bites', await text(page, '#status-detail'));
  check((await text(page, '#recovery')).includes('Practice first') && (await page.title()).startsWith('Stopped'), 'and shows three plain steps; the tab title says Stopped', await page.title());
  check((await text(page, '#status-title')) === 'Stopped' && await page.evaluate(() => document.querySelector('#status-dot').classList.contains('stopped-itself')), 'the heading says Stopped, not Ready, with a red dot', await text(page, '#status-title'));
  await picture(page, '03-stopped-itself.png');
  await page.click('#more > summary');
  await page.fill('#confidence', '80'); await page.press('#confidence', 'Tab');
  await page.locator('input[name="spot_bites_by"][value="both"]').check({ force: true });
  await page.fill('#cast_seconds', '20'); await page.press('#cast_seconds', 'Tab');
  await page.fill('#stop_after_misses', '5'); await page.press('#stop_after_misses', 'Tab');
  await page.waitForTimeout(600);
  await page.click('#more > summary');

  // ---- practice is a button ----
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click('#activity > summary');
  const before = await page.locator('#log li').count();
  await page.click('#practice');
  check(await waitText(page, '#status-title', 'Practice', 15000) && (await text(page, '#status-detail')).includes('Nothing is pressed or clicked'), 'Practice first starts watching only', await text(page, '#status-detail'));
  check(await page.locator('#recovery').isHidden(), 'starting again clears the alarm');
  check(await waitFor(page, () => Number(document.querySelector('#stat-looted').innerText) >= 1, null, 40000) && (await text(page, '#stat-looted-label')) === 'Would have clicked', 'it counts what it would have clicked', `${await text(page, '#stat-looted-label')}: ${await text(page, '#stat-looted')}`);
  const practiceLines = (await page.locator('#log li span').allInnerTexts()).slice(before);
  check(practiceLines.some((l) => l.startsWith('Practice: it would have clicked the bobber now')) && !practiceLines.some((l) => /^Cast \d|Got a bite/.test(l)), 'and never casts or clicks', practiceLines.slice(0, 2).join(' | '));
  await page.click('#stop');
  await waitText(page, '#status-title', 'Ready', 8000);
  await page.click('#activity > summary');
  await page.click('#start');
  check(await waitText(page, '#status-title', 'Fishing', 15000) && (await text(page, '#stat-looted-label')) === 'Caught', 'the next normal start is a normal session again');
  await page.click('#stop');
  await waitText(page, '#status-title', 'Ready', 8000);

  // ---- the assistant, tucked away ----
  await page.click('#more > summary');
  check(await page.locator('#assistant-body').isHidden(), 'the assistant is off until switched on');
  await page.check('#assistant_enabled');
  await page.waitForSelector('#assistant-body', { state: 'visible' });
  await page.fill('#assistant_url', 'not a url'); await page.press('#assistant_url', 'Tab');
  await errorFor(page, 'assistant_url');
  check((await text(page, '[data-error-for="assistant_url"]')).includes('web address'), 'a wrong address is refused');
  await page.fill('#assistant_url', LLM); await page.press('#assistant_url', 'Tab');
  await page.waitForTimeout(500);
  await page.click('#assistant-test');
  check(await waitText(page, '#assistant-test-result', 'Connected. qwen3:8b is ready.', 10000), 'checking the connection finds qwen3:8b');
  await page.click('#suggestions .chip-button:nth-child(3)');
  await page.waitForSelector('.proposal', { timeout: 15000 });
  const proposal = await text(page, '.proposal');
  check(/How much of the game it watches: the middle → a small middle/.test(proposal) && /Left out –/.test(proposal), 'a suggestion lists each change in plain words, before and after', proposal.replace(/\n/g, ' | '));
  check((await saved(page)).settings.scan_area === 'center75', 'nothing changes until you say so');
  await page.click('.proposal .button.primary');
  await page.waitForSelector('.proposal .done', { timeout: 5000 });
  now = (await saved(page)).settings;
  check(now.scan_area === 'center50' && now.cpu_threads === 2, 'Use these changes only what is allowed', await text(page, '.proposal .done'));
  await page.fill('#chat-input', 'It keeps missing fish'); await page.press('#chat-input', 'Enter');
  check(await waitFor(page, () => document.querySelectorAll('#chat li.assistant').length === 2, null, 15000) && (await page.locator('.proposal').count()) === 1, 'a plain answer comes without a suggestion box');

  // ---- keys are named the way each system presses them; a repeated line shows once ----
  const names = await page.evaluate(() => {
    const real = state.platform.system; const out = {};
    state.platform.system = 'macos';
    out.mac = [keyName({ code: 'KeyY', key: 'z' }), keyName({ code: 'Digit1', key: '&' }), keyName({ code: 'IntlBackslash', key: '<' })];
    state.platform.system = 'windows';
    out.win = [keyName({ code: 'KeyY', key: 'z' }), keyName({ code: 'Numpad4', key: '4' }), keyName({ code: 'Space', key: ' ' })];
    state.platform.system = real;
    return out;
  });
  check(JSON.stringify(names) === JSON.stringify({ mac: ['y', '1', null], win: ['z', 'num4', 'space'] }), 'keys are named by position on a Mac and by letter on Windows', JSON.stringify(names));
  const added = await page.evaluate(() => { const b = document.querySelectorAll('#log li').length; const line = { id: lastLogId + 1, time: Date.now() / 1000, level: 'info', message: 'only once' }; addToLog([line]); addToLog([line]); return document.querySelectorAll('#log li').length - b; });
  check(added === 1, 'a line that arrives twice is shown once');

  // ---- other screens ----
  const dark = await browser.newContext({ viewport: { width: 900, height: 1100 }, colorScheme: 'dark', deviceScaleFactor: 2 });
  const darkPage = await dark.newPage();
  await darkPage.goto(URL); await darkPage.waitForFunction(() => document.querySelector('#status-title').innerText === 'Ready');
  await picture(darkPage, '04-dark.png');
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const phonePage = await phone.newPage();
  await phonePage.goto(URL); await phonePage.waitForFunction(() => document.querySelector('#status-title').innerText === 'Ready');
  await phonePage.click('#more > summary');
  const overflow = await phonePage.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(overflow <= 0, 'nothing runs off the side on a phone-sized screen', `overflow ${overflow}px`);
  await picture(phonePage, '05-phone.png');

  // ---- a report to send for help ----
  const [download] = await Promise.all([page.waitForEvent('download', { timeout: 20000 }), page.click('#report')]);
  check(/^wow-fish-yolo-report-\d{4}-\d{2}-\d{2}-\d{4}\.zip$/.test(download.suggestedFilename()), 'Save a report hands you one file', download.suggestedFilename());
  check(await waitFor(page, () => document.querySelector('#report-message').innerText.includes('Downloads folder')), 'and says where it went and what is in it', await text(page, '#report-message'));

  // ---- a stranger cannot use it; Quit quits ----
  const stranger = await context.newPage();
  await stranger.goto(URL);
  const status = await stranger.evaluate(async () => (await fetch('/api/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).status);
  check(status === 403, 'a request without the page\'s key is refused', `status ${status}`);
  await page.click('#quit');
  check(await waitFor(page, () => !document.querySelector('#offline').hidden, null, 5000) && (await text(page, '#offline')).includes('has quit'), 'Quit quits and says so');

  check(problems.length === 0, 'no errors in the browser', problems.slice(0, 5).join(' || '));
  console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('SCRIPT ERROR', e); process.exit(2); });
