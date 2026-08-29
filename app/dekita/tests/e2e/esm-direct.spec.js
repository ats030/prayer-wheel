import { test, expect } from '@playwright/test';

test('should load ESM module without browser console error', async ({ page }) => {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  
  await page.goto('http://localhost:8525/src/modules/core/GameState.js');
  
  console.log('Errors:', errors);
  expect(errors.length).toBe(0);
});

test('should load main.js without browser console error', async ({ page }) => {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  
  await page.goto('http://localhost:8525/src/main.js');
  
  console.log('Errors:', errors);
  expect(errors.length).toBe(0);
});
