import { test, expect } from '@playwright/test';

test('should load ESM module without syntax error', async ({ page }) => {
  test.setTimeout(60000);
  
  const errors = [];
  
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  
  await page.goto('http://localhost:8525/index.html');
  
  console.log('Errors:', errors);
  
  if (errors.length > 0) {
    throw new Error(`Browser console error: ${errors.join(', ')}`);
  }
  
  await expect(page.locator('h1')).toHaveText('できた！');
});
