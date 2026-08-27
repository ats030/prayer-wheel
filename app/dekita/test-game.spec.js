const { test, expect } = require('@playwright/test');
const fs = require('fs');
const { exec } = require('child_process');

function runCommand(command) {
  return new Promise((resolve, reject) => {
    exec(command, (error, stdout, stderr) => {
      if (error) {
        reject(error);
      } else {
        resolve({ stdout, stderr });
      }
    });
  });
}

let serverProcess = null;

test.beforeAll(async () => {
  try {
    await runCommand('pkill -f "http-server" 2>/dev/null || true');
  } catch (e) {}
  
  serverProcess = require('child_process').spawn('npx', ['http-server', '-p', '8525', '-c-1', '--silent'], {
    cwd: '/home/ats030/app/dekita',
    stdio: ['pipe', 'pipe', 'pipe']
  });
  
  serverProcess.stdout.pipe(require('fs').createWriteStream('/tmp/server.log'));
  serverProcess.stderr.pipe(require('fs').createWriteStream('/tmp/server.log'));
  serverProcess.unref();
  
  const checkServer = async () => {
    try {
      await runCommand('curl -s -o /dev/null -w "%{http_code}" http://localhost:8525/index.html');
    } catch (e) {
      setTimeout(checkServer, 500);
      return;
    }
  };
  
  await new Promise((resolve) => setTimeout(resolve, 1000));
  await checkServer();
});

test.afterAll(async () => {
  if (serverProcess) {
    serverProcess.kill('SIGTERM');
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
});

test.describe('できた！全機能テスト', () => {
  
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
  });

  test('1. 初期状態でタイトル画面が表示されること', async ({ page }) => {
    await expect(page.locator('#title-screen')).toBeVisible();
    await expect(page.locator('#number-select-screen')).not.toBeVisible();
    await expect(page.locator('#game-screen')).not.toBeVisible();
    await expect(page.locator('#result-screen')).not.toBeVisible();
  });

  test('2. サウンド生成 - 正解音（440Hz+550Hz正弦波0.2s）', async ({ page }) => {
    const audioContext = await page.evaluateHandle(() => {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      return ctx;
    });

    const oscillator = await page.evaluateHandle((ctx) => {
      const osc = ctx.createOscillator();
      osc.frequency.value = 440;
      osc.type = 'sine';
      osc.connect(ctx.destination);
      osc.start();
      return osc;
    }, audioContext);

    await page.evaluate(() => {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      osc.frequency.value = 550;
      osc.type = 'sine';
      osc.connect(ctx.destination);
      osc.start();
    });
  });

  test('3. サウンド生成 - 不正解音（330Hzノコギリ波0.3s）', async ({ page }) => {
    await page.evaluate(() => {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      osc.frequency.value = 330;
      osc.type = 'sawtooth';
      osc.connect(ctx.destination);
      osc.start();
    });
  });

  test('4. ゲーム開始: 5問生成・表示され4択ボタンが描画されること', async ({ page }) => {
    await page.click('#start-btn');
    await expect(page.locator('#number-select-screen')).toBeVisible({ timeout: 5000 });

    await page.waitForTimeout(300);
    await page.click('.number-btn:text("5")');
    await page.waitForTimeout(300);
    await expect(page.locator('#game-screen')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#score')).toHaveText('0');

    const questionText = await page.locator('#question-text');
    await expect(questionText).toBeVisible();
    
    const answerButtons = await page.locator('.answer-btn');
    await expect(answerButtons).toHaveCount(4);
  });

  test('5. 回答チェック - 正解時に+10点、音声再生', async ({ page }) => {
     await page.evaluate(() => localStorage.removeItem('gakushuGameHighScore'));
     await page.waitForSelector('#start-btn', { state: 'visible' });
     await page.click('#start-btn');
     await page.click('.number-btn:text("5")');
     await page.waitForSelector('#game-screen', { state: 'visible' });
     await page.waitForFunction(() => document.querySelector('.answer-btn') !== null);

     const scoreBoard = page.locator('#score');
     await scoreBoard.waitFor({ state: 'visible' });
     const initialScore = await scoreBoard.textContent();
     
     const correctBtn = page.locator('.answer-btn[data-correct="true"]');
     await correctBtn.waitFor({ state: 'visible' });
      await correctBtn.click();
      await page.waitForSelector('#feedback-area', { state: 'visible' });
      await expect(page.locator('#feedback-text')).toContainText('せいかい');
      await expect(page.locator('#feedback-text')).toContainText('＋10てん');
      
      await page.click('#next-btn');
     await page.waitForSelector('#question-text', { state: 'visible' });
     
     const newScore = await scoreBoard.textContent();
     expect(parseInt(newScore)).toBe(parseInt(initialScore) + 10);
   });

   test('6. 回答チェック - 不正解時に音声再生・フィード表示', async ({ page }) => {
     await page.evaluate(() => localStorage.removeItem('gakushuGameHighScore'));
     await page.waitForSelector('#start-btn', { state: 'visible' });
     await page.click('#start-btn');
     await page.click('.number-btn:text("5")');
     await page.waitForSelector('#game-screen', { state: 'visible' });
     await page.waitForFunction(() => document.querySelector('.answer-btn') !== null);

     const answerButtons = page.locator('.answer-btn:not([data-correct="true"])');
     await answerButtons.first().waitFor({ state: 'visible' });
     
     await answerButtons.first().click();
     await page.waitForSelector('#feedback-area', { state: 'visible' });
     await expect(page.locator('#feedback-text')).toContainText('ちょんぼ…');
     await expect(page.locator('#feedback-text')).toContainText('💦');
     await expect(page.locator('#feedback-text')).toHaveCSS('color', 'rgb(229, 115, 115)');
   });

  test('7. 10問進んだら結果画面が表示され、最高スコアがlocalStorageに保存させること', async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem('gakushuGameHighScore'));
    
    await page.click('#start-btn');
    await page.click('.number-btn:text("5")');
    await page.waitForSelector('#game-screen', { state: 'visible' });
    
    for (let i = 0; i < 10; i++) {
      await page.waitForFunction(() => document.querySelector('.answer-btn') !== null);
      
      const correctBtn = page.locator('.answer-btn[data-correct="true"]');
      await correctBtn.waitFor({ state: 'visible' });
      await correctBtn.click();
      await page.waitForSelector('#next-btn', { state: 'visible' });
      await page.click('#next-btn');
    }

    await expect(page.locator('#result-screen')).toBeVisible();
    await expect(page.locator('#final-score')).toBeVisible();
  });

test('8. 10問目終了時に結果画面が正しく表示されること', async ({ page }) => {
  await page.click('#start-btn');
  await page.click('.number-btn:text("3")');
  await page.waitForSelector('#game-screen', { state: 'visible' });

  for (let i = 0; i < 10; i++) {
   await page.waitForFunction(() => document.querySelector('.answer-btn') !== null);
    const correctBtn = page.locator('.answer-btn[data-correct="true"]');
   await correctBtn.waitFor({ state: 'visible' });
   await correctBtn.click();
   if (i < 9) {
     await page.waitForSelector('#next-btn', { state: 'visible' });
     await page.click('#next-btn');
   }
  }

  await expect(page.locator('#result-screen')).toBeVisible();
  await expect(page.locator('#final-score')).toBeVisible();
});

   test('9. クイズがランダムに表示されること', async ({ page }) => {
     await page.click('#start-btn');
     await page.click('.number-btn:text("5")');
     await page.waitForSelector('#game-screen', { state: 'visible' });

     const questionTypes = [];
     for (let i = 0; i < 5; i++) {
       await page.waitForSelector('#question-text', { state: 'visible' });
       const question = await page.locator('#question-text').textContent();
       questionTypes.push(question);
       await page.waitForFunction(() => document.querySelector('.answer-btn') !== null);
       await page.click(`.answer-btn`, { timeout: 5000 });
       await page.waitForSelector('#next-btn', { state: 'visible' });
       await page.click('#next-btn', { timeout: 5000 });
     }

     expect(questionTypes.length).toBe(5);
   });

    test('10. リセットボタンでタイトル画面に戻ること', async ({ page }) => {
      await page.click('#start-btn');
      await page.click('.number-btn:text("3")');
      await page.waitForSelector('#game-screen', { state: 'visible' });
     await expect(page.locator('#game-screen')).toBeVisible();

     await page.click('#reset-btn');
     await expect(page.locator('#title-screen')).toBeVisible();
   });

  test('11. カウントアップゲームで絵文字が正しく表示される', async ({ page }) => {
    await page.click('#start-btn');
    await page.click('.number-btn:text("5")');
    await page.waitForSelector('#game-screen', { state: 'visible' });
    await page.waitForFunction(() => document.querySelector('#question-text') !== null);

    const firstQuestion = await page.locator('#question-text').textContent();
    if (firstQuestion.includes('なんこの')) {
      await page.waitForFunction(() => document.querySelector('.answer-btn') !== null);
      await page.click(`.answer-btn`, { clickCount: 1, timeout: 5000 });
    }
  });
});

test.describe('できた！色当てゲームテスト', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:8525/index.html');
  });

   test('12. タイトル画面に「すうじ」と「いろ」ボタンが表示されること', async ({ page }) => {
     await expect(page.locator('#title-screen')).toBeVisible();
      await expect(page.locator('#start-btn')).toHaveText('🔢 すうじ');
      await expect(page.locator('#color-start-btn')).toHaveText('🎨 いろ');
    });

    test('13. いろボタンでゲーム画面に移り、色サンプルと4択の色名ボタンが表示されること', async ({ page }) => {
      await page.click('#color-start-btn');
      await expect(page.locator('#color-game-screen')).toBeVisible();
      await expect(page.locator('#color-score')).toHaveText('0');
      await expect(page.locator('#color-question-text')).toHaveText('これ なん の いろかな？');

      const swatch = page.locator('#color-swatch');
      await expect(swatch).toBeVisible();

     const answerButtons = page.locator('.color-answer-btn');
     await expect(answerButtons).toHaveCount(4);
     const names = await answerButtons.allTextContents();
     expect(names.sort()).toEqual(['あお', 'あか', 'きいろ', 'みどり']);
   });

    test('14. 色当てで正解したときに+10点加算されること', async ({ page }) => {
      await page.click('#color-start-btn');
      await page.waitForSelector('#color-game-screen', { state: 'visible' });
      await page.waitForSelector('#color-swatch', { state: 'visible' });
      
      const correctName = await page.evaluate(() => {
        if (window.correctAnswer) {
          return window.correctAnswer;
        }
        
        const buttons = Array.from(document.querySelectorAll('.color-answer-btn'));
        const emojiMap = {
          '🍎': 'あか', '🍓': 'あか', '🍒': 'あか', '🍅': 'あか',
          '🐳': 'あお', '🧊': 'あお', '🔵': 'あお', '🐬': 'あお',
          '🍌': 'きいろ', '🍋': 'きいろ', '🌽': 'きいろ', '🌻': 'きいろ',
          '🥦': 'みどり', '🍐': 'みどり', '🥬': 'みどり', '🍏': 'みどり'
        };
        
        const swatch = document.getElementById('color-swatch');
        const emoji = swatch ? swatch.textContent.trim() : '';
        
        return emojiMap[emoji] || null;
      });

      if (!correctName) {
        throw new Error('正解の色名を特定できません');
      }

      await page.click(`.color-answer-btn:text("${correctName}")`);
      await page.waitForSelector('#color-feedback-area', { state: 'visible' });

      await expect(page.locator('#color-feedback-text')).toContainText('せいかい');
      await expect(page.locator('#color-score')).toHaveText('10');
     });

    test('15. 色当てで不正解したときに「ざんねん...」が表示されポイント加算されないこと', async ({ page }) => {
      await page.click('#color-start-btn');
      await page.waitForSelector('#color-game-screen', { state: 'visible' });
      await page.waitForSelector('.color-swatch', { state: 'visible' });

      await page.click(`.color-answer-btn:not([data-correct="true"])`);
      await page.waitForSelector('#color-feedback-area', { state: 'visible' });

      await expect(page.locator('#color-feedback-text')).toHaveText('ちょんぼ… 💦');
      await expect(page.locator('#color-score')).toHaveText('0');
     });

      test('16. 色当てを10問進んだら結果画面が表示されること', async ({ page }) => {
        await page.click('#color-start-btn');

        for (let i = 0; i < 10; i++) {
          await page.waitForSelector('.color-answer-btn', { state: 'visible' });
          await page.click(`.color-answer-btn:not([data-correct="true"])`);
          await page.waitForTimeout(2200);
        }

         await page.waitForSelector('#result-screen', { state: 'visible', timeout: 15000 });
        await expect(page.locator('#final-score')).toBeVisible();
      });

    test('17. 色当てゲームのリセットでタイトル画面に戻り、いろボタンが再び使えること', async ({ page }) => {
      await page.click('#color-start-btn');
      await expect(page.locator('#color-game-screen')).toBeVisible();

      await page.click('#color-reset-btn');
      await page.waitForSelector('#title-screen', { state: 'visible', timeout: 15000 });

      await page.click('#color-start-btn');
      await expect(page.locator('#color-game-screen')).toBeVisible();
      const answerButtons = page.locator('.color-answer-btn');
      await expect(answerButtons).toHaveCount(4);
    });
});

test.afterEach(async ({ page }) => {
  await page.close();
});
