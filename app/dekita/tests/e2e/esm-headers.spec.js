import { test, expect } from '@playwright/test';

test('should load ES module headers without errors', async ({ page }) => {
  test.setTimeout(30000);
  
  const modules = [
    'src/modules/index.js',
    'src/modules/core/GameState.js',
    'src/modules/core/AudioManager.js',
    'src/modules/core/ScreenManager.js',
    'src/modules/games/CountGame.js',
    'src/modules/games/ColorGame.js',
    'src/modules/games/AnimalGame.js',
    'src/modules/games/MazeGame.js'
  ];

  const errors = [];

  for (const url of modules) {
    try {
      const response = await page.goto(`http://localhost:8525/${url}`, { waitUntil: 'domcontentloaded' });
      const status = response?.status();
      const headers = response?.headers();
      
      console.log(`URL: ${url}, Status: ${status}`);
      console.log(`Content-Type: ${headers?.['content-type']}`);

      if (status !== 200) {
        errors.push({ url, status });
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
