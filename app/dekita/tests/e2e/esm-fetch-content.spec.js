import { test, expect } from '@playwright/test';

test('should fetch ESM module content without syntax error', async ({ page }) => {
  test.setTimeout(30000);
  
  const url = 'http://localhost:8525/src/modules/index.js';
  
  const { content, error } = await page.evaluate(async (u) => {
    try {
      const response = await fetch(u);
      const text = await response.text();
      return { content: text, error: null };
    } catch (e) {
      return { content: null, error: e.message };
    }
  }, url);

  console.log('Error:', error);
  console.log('Content preview:', content ? content.substring(0, 200) : 'N/A');

  if (error) {
    throw new Error(`Failed to fetch: ${error}`);
  }
});
