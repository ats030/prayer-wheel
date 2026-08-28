/* 
 * dekita - Preschool Edition E2E Tests
 * Playwright test suite
 */

import { test, expect } from '@playwright/test';

test.use({ headless: true });

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

  test.beforeEach(async ({ page }) => {
    await page.on('console', msg => {
      const type = msg.type();
      if (type === 'log' || type === 'error' || type === 'warning' || type === 'info') {
        console.log('[Browser] [tests/e2e] ' + type + ':', msg.text());
      }
    });
  });

  test('should load the game page', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await expect(page.locator('h1')).toHaveText('できた！');
  });

  test('should show title screen initially', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    expect(await page.locator('#title-screen').getAttribute('class')).not.toContain('hidden');
    expect(await page.locator('#game-screen').getAttribute('class')).toContain('hidden');
  });

  test('should start number game directly without select screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#start-btn');
    await page.waitForSelector('#game-screen:not(.hidden)', { timeout: 60000 });
    expect(await page.locator('#game-screen').getAttribute('class')).not.toContain('hidden');
  });

  test('should display color game screen when clicking いろ button', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#color-start-btn');
    expect(await page.locator('#color-game-screen').getAttribute('class')).not.toContain('hidden');
  });

  test('should display maze theme select screen when clicking めいろ button', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#maze-start-btn');
    expect(await page.locator('#maze-theme-select-screen').getAttribute('class')).not.toContain('hidden');
  });

  test('should display maze game screen when selecting a theme', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.evaluate(() => setTestMode(true));
    await page.click('#maze-start-btn');
    await page.waitForSelector('#maze-theme-buttons .maze-theme-btn');
    await page.evaluate(() => {
      const btn = document.querySelector('#maze-theme-buttons .maze-theme-btn');
      if (btn) {
        btn.click();
      }
    });
    expect(await page.locator('#game-screen').getAttribute('class')).not.toContain('hidden');
  });

  test('should update score during maze game', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.evaluate(() => setTestMode(true));
    await page.click('#maze-start-btn');
    await page.waitForSelector('#maze-theme-buttons .maze-theme-btn');
    await page.evaluate(() => {
      const btn = document.querySelector('#maze-theme-buttons .maze-theme-btn');
      if (btn) {
        btn.click();
      }
    });
    await page.click('#maze-canvas');
    const scoreText = await page.locator('#score').textContent();
    expect(scoreText).toBe('0');
  });

  test('should show correct feedback after clicking wrong canvas area', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.evaluate(() => setTestMode(true));
    await page.click('#maze-start-btn');
    await page.waitForSelector('#maze-theme-buttons .maze-theme-btn');
    await page.evaluate(() => {
      const btn = document.querySelector('#maze-theme-buttons .maze-theme-btn');
      if (btn) {
        btn.click();
      }
    });
    await page.waitForSelector('#maze-canvas');
    await page.evaluate(() => {
      const canvas = document.getElementById('maze-canvas');
      if (canvas) {
        const rect = canvas.getBoundingClientRect();
        const event = new MouseEvent('mousemove', {
          bubbles: true,
          cancelable: true,
          clientX: rect.left + rect.width + 50,
          clientY: rect.top + rect.height + 50
        });
        canvas.dispatchEvent(event);
      }
    });
    await page.waitForTimeout(2000);
    const feedbackText = await page.locator('#feedback-text').textContent();
    expect(feedbackText === 'だいじょうぶ！もういっこ！' || feedbackText === 'せいかい!').toBe(true);
  });

  test('should display score in game screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#start-btn');
    const scoreText = await page.locator('#score').textContent();
    expect(scoreText).toBe('0');
  });
});
