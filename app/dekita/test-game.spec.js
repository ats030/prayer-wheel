/* 
 * dekita - Preschool Edition E2E Tests
 * Playwright test suite
 */

import { test, expect } from '@playwright/test';

test.use({ headless: true });

test.describe('Dekita Game - E2E Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.on('console', msg => {
      const type = msg.type();
      if (type === 'log' || type === 'error' || type === 'warning' || type === 'info') {
        console.log('[Browser]', type + ':', msg.text());
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
  });

  test('should switch to number select screen when clicking すうじ button', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#start-btn');
    expect(await page.locator('#number-select-screen').getAttribute('class')).not.toContain('hidden');
    expect(await page.locator('#title-screen').getAttribute('class')).toContain('hidden');
  });

  test('should display number buttons in number select screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#start-btn');
    const numberButtons = page.locator('.number-btn');
    await expect(numberButtons).toHaveCount(5);
    
    const buttonValues = await numberButtons.allTextContents();
    expect(buttonValues).toEqual(['1', '2', '3', '4', '5']);
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
    
    const themeSelectScreen = page.locator('#maze-theme-select-screen');
    await expect(themeSelectScreen).not.toHaveClass('hidden');
    
    await page.waitForSelector('#maze-theme-buttons .maze-theme-btn');
    const buttons = await page.locator('#maze-theme-buttons .maze-theme-btn');
    const count = await buttons.count();
    console.log('Theme buttons count:', count);
    
    await page.evaluate(() => {
      const btn = document.querySelector('#maze-theme-buttons .maze-theme-btn');
      if (btn) {
        btn.click();
      }
    });
    await page.waitForTimeout(1000);
    
    const afterClass = await page.locator('#game-screen').getAttribute('class');
    console.log('After click - game-screen class:', afterClass);
    
    expect(afterClass).not.toContain('hidden');
  });

  test('should display score in game screen', async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
    await page.click('#start-btn');
    await expect(page.locator('#score')).toHaveText('0');
  });
});
