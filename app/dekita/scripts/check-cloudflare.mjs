// Run against wrangler dev, or the deployed URL supplied as the first argument.
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {readFile} from 'node:fs/promises';

const base = process.argv[2] || 'http://127.0.0.1:8787';
const browser = await chromium.launch({headless: true});
try {
  const oldContext = await browser.newContext({acceptDownloads: true});
  const oldPage = await oldContext.newPage();
  const errors = [];
  oldPage.on('pageerror', error => errors.push(error.message));
  // Existing local-only analytics must not trigger LAN requests in this check.
  await oldContext.route('http://ubuntu-server-app:8526/**', route => route.abort());
  for (const [button, screen] of [
    ['start-btn', 'game-screen'], ['color-start-btn', 'color-game-screen'],
    ['animal-start-btn', 'animal-game-screen'], ['maze-start-btn', 'maze-play-screen'],
    ['match-start-btn', 'match-game-screen'], ['puzzle-start-btn', 'puzzle-game-screen'],
  ]) {
    await oldPage.goto(base);
    await oldPage.click(`#${button}`);
    await oldPage.waitForSelector(`#${screen}:not(.hidden)`);
  }
  assert.deepEqual(errors, [], 'game scripts must execute without page errors');
  for (const path of ['/audio/correct.mp3', '/src/main.js', '/migration.js']) {
    const response = await oldContext.request.get(base + path);
    assert.equal(response.status(), 200, path);
    assert.equal(response.headers()['x-content-type-options'], 'nosniff');
  }
  for (const path of ['/package.json', '/Dockerfile', '/.env', '/src/tests/setup.js', '/tests/e2e/game.spec.js']) {
    assert.equal((await oldContext.request.get(base + path)).status(), 404, path);
  }
  await oldPage.goto(base + '/migration.html');
  await oldPage.evaluate(() => localStorage.setItem('gakushuGameHighScore', '123'));
  await oldPage.reload();
  const downloadPromise = oldPage.waitForEvent('download');
  await oldPage.click('#export');
  const download = await downloadPromise;
  const contents = await readFile(await download.path());
  assert.deepEqual(JSON.parse(contents), {format: 'dekita-high-score', version: 1, highScore: 123});

  const newContext = await browser.newContext();
  await newContext.route('http://ubuntu-server-app:8526/**', route => route.abort());
  const newPage = await newContext.newPage();
  await newPage.goto(base + '/migration.html');
  assert.equal(await newPage.locator('#score').textContent(), '0');
  const upload = async buffer => {
    await newPage.locator('#import').setInputFiles({name: 'score.json', mimeType: 'application/json', buffer});
    await newPage.waitForFunction(() => document.querySelector('#import').value === '');
  };
  await upload(contents);
  assert.equal(await newPage.locator('#score').textContent(), '123');
  await upload(Buffer.from(JSON.stringify({format: 'dekita-high-score', version: 1, highScore: 10})));
  assert.equal(await newPage.locator('#score').textContent(), '123');
  for (const buffer of [
    Buffer.from('{bad json'),
    Buffer.from(JSON.stringify({format: 'dekita-high-score', version: 1, highScore: -1})),
    Buffer.from(JSON.stringify({format: 'other-app', version: 1, highScore: 500})),
    Buffer.alloc(4097, 32),
  ]) {
    await upload(buffer);
    assert.equal(await newPage.locator('#score').textContent(), '123');
    assert.notEqual(await newPage.locator('#status').textContent(), 'ハイスコアを引き継ぎました。');
  }
  await newPage.goto(base);
  await newPage.waitForFunction(() => window.gameApp?.gameState);
  assert.equal(await newPage.evaluate(() => window.gameApp.gameState.highScore), 123);
  // Count, Animal and Maze all call this completion method. A lower result
  // must not overwrite the imported score; a better result must replace it.
  await newPage.evaluate(() => {
    window.gameApp.gameState.score = 10;
    window.gameApp.gameState.saveScore();
  });
  await newPage.reload();
  await newPage.waitForFunction(() => window.gameApp?.gameState);
  assert.equal(await newPage.evaluate(() => window.gameApp.gameState.highScore), 123);
  await newPage.evaluate(() => {
    window.gameApp.gameState.score = 150;
    window.gameApp.gameState.saveScore();
  });
  await newPage.reload();
  await newPage.waitForFunction(() => window.gameApp?.gameState);
  assert.equal(await newPage.evaluate(() => window.gameApp.gameState.highScore), 150);
  await newPage.evaluate(() => localStorage.setItem('gakushuGameHighScore', 'not-a-score'));
  await newPage.reload();
  await newPage.waitForFunction(() => window.gameApp?.gameState);
  assert.equal(await newPage.evaluate(() => window.gameApp.gameState.highScore), 0);
  await newPage.evaluate(() => {
    window.gameApp.gameState.score = 20;
    window.gameApp.gameState.saveScore();
  });
  await newPage.reload();
  await newPage.waitForFunction(() => window.gameApp?.gameState);
  assert.equal(await newPage.evaluate(() => window.gameApp.gameState.highScore), 20);
  console.log('PASS: six game screens, audio delivery, headers, private-file exclusion, score transfer, invalid-file rejection and score preservation after completion');
} finally {
  await browser.close();
}
