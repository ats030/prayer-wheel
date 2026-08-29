import { test, expect } from '@playwright/test';

test('should load ES module content without syntax error', async ({ page }) => {
  const urls = [
    'http://localhost:8525/src/modules/index.js',
    'http://localhost:8525/src/modules/core/GameState.js',
    'http://localhost:8525/src/modules/games/MazeGame.js'
  ];

  for (const url of urls) {
    const { content, error } = await page.evaluate(async (u) => {
      try {
        const response = await fetch(u);
        const text = await response.text();
        return { content: text, error: null };
      } catch (e) {
        return { content: null, error: e.message };
      }
    }, url);

    console.log(`URL: ${url}`);
    console.log(`Error: ${error}`);
    console.log(`Content preview: ${content ? content.substring(0, 100) : 'N/A'}`);

    if (error) {
      throw new Error(`Failed to load ${url}: ${error}`);
    }
  }
});
