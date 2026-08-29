import { test, expect } from '@playwright/test';

test('should evaluate ESM module content without syntax error', async ({ page }) => {
  const modules = [
    'http://localhost:8525/src/modules/core/GameState.js',
    'http://localhost:8525/src/modules/core/AudioManager.js',
    'http://localhost:8525/src/modules/core/ScreenManager.js',
    'http://localhost:8525/src/modules/games/CountGame.js',
    'http://localhost:8525/src/modules/games/ColorGame.js',
    'http://localhost:8525/src/modules/games/AnimalGame.js',
    'http://localhost:8525/src/modules/games/MazeGame.js',
    'http://localhost:8525/src/modules/index.js'
  ];

  const errors = [];

  for (const url of modules) {
    try {
      const response = await page.goto(url, { waitUntil: 'domcontentloaded' });
      if (response?.status() !== 200) {
        errors.push({ url, status: response?.status(), error: 'Non-200 status' });
        continue;
      }

      const content = await page.content();
      if (content.includes('SyntaxError') || content.includes('Unexpected token')) {
        errors.push({ url, error: 'Syntax error in page content' });
      }
    } catch (e) {
      errors.push({ url, error: e.message });
    }
  }

  if (errors.length > 0) {
    console.log('Errors:', errors);
    throw new Error(`Failed to load ESM modules: ${JSON.stringify(errors)}`);
  }
});
