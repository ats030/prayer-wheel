/* 
 * dekita - Preschool Edition E2E Tests
 * Playwright test suite
 */

import { test, expect } from '@playwright/test';

test.setTimeout(180000);

test.use({ 
  headless: true,
  launchOptions: {
    args: ['--disable-cache', '--disable-http-cache', '--disk-cache-size=0', '--media-cache-size=0']
  },
  contextOptions: {
    bypassCSP: true
  },
  trace: 'on-first-retry',
  timeout: 180000
});

let serverProcess = null;

test.describe('Dekita Game - E2E Tests', () => {
  test.beforeAll(async () => {
    const { exec } = await import('child_process');
    serverProcess = exec('curl -s http://localhost:8525/index.html > /dev/null 2>&1 || npx http-server -p 8525 > /dev/null 2>&1 &');
    await new Promise(resolve => setTimeout(resolve, 1000));
  });

  test.afterAll(async () => {
    if (serverProcess) {
      serverProcess.kill();
    }
  });

  test('should load the game page', async ({ page }) => {
    page.on('console', msg => console.log('[BROWSER]', msg.text()));
    const startTime = Date.now();
    const response = await page.goto('http://localhost:8525/index.html', { timeout: 120000 });
    console.log('goto finished, response:', response?.status(), 'elapsed:', Date.now() - startTime, 'ms');
    
    try {
      const h1Text = await page.locator('h1').textContent();
      console.log('h1 text:', h1Text, 'elapsed:', Date.now() - startTime, 'ms');
      expect(h1Text).toBe('できた！');
    } catch (e) {
      console.log('expect error:', e.message);
      throw e;
    }
  });

  test('should show title screen initially', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    expect(await page.locator('#title-screen').getAttribute('class')).not.toContain('hidden');
    expect(await page.locator('#game-screen').getAttribute('class')).toContain('hidden');
  });

  test('should start number game directly without select screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.waitForSelector('#start-btn');
    const gameAppExists = await page.evaluate(() => !!window.gameApp);
    console.log('gameApp exists:', gameAppExists);
    const countGameExists = await page.evaluate(() => !!window.gameApp?.countGame);
    console.log('countGame exists:', countGameExists);
    const startBtn = await page.evaluate(() => document.getElementById('start-btn'));
    console.log('start-btn exists:', !!startBtn);
    await page.click('#start-btn');
    console.log('click finished');
    await page.waitForSelector('#game-screen:not(.hidden)', { timeout: 60000 });
    console.log('page-screen visible');
    expect(await page.locator('#game-screen').getAttribute('class')).not.toContain('hidden');
  });

  test('should display color game screen when clicking いろ button', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    const colorGameExists = await page.evaluate(() => !!window.gameApp?.colorGame);
    console.log('colorGame exists:', colorGameExists);
    await page.click('#color-start-btn');
    const screenClass = await page.locator('#color-game-screen').getAttribute('class');
    expect(screenClass).not.toContain('hidden');
  });

  test('should start maze game directly without theme select screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#maze-start-btn');
    await page.waitForSelector('#maze-play-screen:not(.hidden)', { timeout: 60000 });
    expect(await page.locator('#maze-play-screen').getAttribute('class')).not.toContain('hidden');
  });

  test('should update score during maze game', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#maze-start-btn');
    await page.waitForSelector('#maze-play-screen:not(.hidden)', { timeout: 60000 });
    console.log('maze play screen visible');
    await page.waitForSelector('#maze-canvas.maze-canvas', { timeout: 60000 });
    console.log('canvas visible');
    const scoreText = await page.locator('#maze-score').textContent();
    console.log('score:', scoreText);
    expect(scoreText).toBe('⭐️0');
  });

test('should show correct feedback after clicking wrong canvas area', async ({ page }) => {
  await page.goto('http://localhost:8525/index.html');
  await page.click('#maze-start-btn');
  await page.waitForSelector('#maze-play-screen:not(.hidden)', { timeout: 60000 });
  await page.waitForSelector('#maze-canvas.maze-canvas', { timeout: 60000 });
  await new Promise(resolve => setTimeout(resolve, 1000));
  
  // Simulate wrong click by calling failMaze directly
  const feedbackCalled = await page.evaluate(() => {
    const mazeGame = window.gameApp.mazeGame;
    mazeGame.failMaze();
    return true;
  });
  console.log('failMaze called:', feedbackCalled);
  await new Promise(resolve => setTimeout(resolve, 1000));
  const feedbackText = await page.locator('#maze-feedback-text').textContent();
  console.log('feedback text:', feedbackText);
  expect(feedbackText).toBe('だいじょうぶ！もういっこ！');
});

  test('should display score in game screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#start-btn');
    await page.waitForSelector('#game-screen:not(.hidden)', { timeout: 60000 });
    const screenClass = await page.locator('#game-screen').getAttribute('class');
    expect(screenClass).not.toContain('hidden');
    const scoreElement = await page.locator('#score');
    const scoreText = await scoreElement.textContent();
    console.log('score text:', scoreText);
    expect(scoreText).toBe('⭐️0');
  });
});
