import { test, expect } from '@playwright/test';

test.use({ 
  headless: false,
  launchOptions: {
    args: ['--disable-cache', '--disable-http-cache']
  }
});

let serverProcess = null;

test.describe('Dekita Game - Network Events', () => {
  test.beforeAll(async () => {
    const { spawn } = await import('child_process');
    serverProcess = spawn('curl', ['-s', 'http://localhost:8525/index.html', '> /dev/null'], { detached: true, stdio: 'ignore' });
    serverProcess.unref();
    await new Promise(resolve => setTimeout(resolve, 1000));
  });

  test.afterAll(async () => {
    if (serverProcess) {
      serverProcess.kill();
    }
  });

  test('should load index.html without ESM syntax error', async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => {
      errors.push({ message: err.message, stack: err.stack });
    });
    
    await page.goto('http://localhost:8525/index.html');
    
    console.log('Errors during load:', errors);
    expect(errors.length).toBe(0);
  });
});
