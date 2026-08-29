import { test, expect } from '@playwright/test';

test('should evaluate ES module content without syntax error', async ({ page }) => {
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

  expect(error).toBeNull();
  expect(content).toContain('export function init');

  try {
    await page.evaluate(content);
  } catch (e) {
    console.log('Evaluation error:', e.message);
    throw e;
  }
});
