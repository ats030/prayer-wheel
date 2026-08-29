import { test, expect } from '@playwright/test';

test('should load ESM module without syntax error', async ({ page }) => {
  await page.goto('http://localhost:8525/src/modules/core/GameState.js');
  const content = await page.textContent('body');
  expect(content).toContain('export class GameState');
});

test('should load main.js without syntax error', async ({ page }) => {
  await page.goto('http://localhost:8525/src/main.js');
  const content = await page.textContent('body');
  expect(content).toContain('import { init }');
});
