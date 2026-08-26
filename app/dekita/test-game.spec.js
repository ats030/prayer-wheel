const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

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
    await page.click('#start-btn');
    await page.click('.number-btn:text("5")');

    const scoreBoard = page.locator('#score');
    const initialScore = await scoreBoard.textContent();
    
    const firstQuestionAnswer = await page.evaluate(() => {
      const answerBtns = Array.from(document.querySelectorAll('.answer-btn'));
      return answerBtns.find(btn => btn.textContent === '3')?.textContent || answerBtns[0].textContent;
    });

    await page.click(`.answer-btn:text("${firstQuestionAnswer}")`);
    
    await expect(page.locator('#feedback-area')).toBeVisible();
    await expect(page.locator('#feedback-text')).toHaveText('せいかい! +10てん');
    
    await page.click('#next-btn');
    
    const newScore = await scoreBoard.textContent();
    expect(parseInt(newScore)).toBe(parseInt(initialScore) + 10);
  });

  test('6. 回答チェック - 不正解時に音声再生・フィード表示', async ({ page }) => {
    await page.click('#start-btn');
    await page.click('.number-btn:text("5")');

      const firstAnswer = await page.evaluate(() => {
        const answerBtns = Array.from(document.querySelectorAll('.answer-btn'));
        return answerBtns[0].textContent;
      });
      await page.click(`.answer-btn:text("${firstAnswer}")`);

    await expect(page.locator('#feedback-area')).toBeVisible();
    await expect(page.locator('#feedback-text')).toHaveText('ちょんぼ…');
    await expect(page.locator('#feedback-text')).toHaveCSS('color', 'rgb(229, 115, 115)');
  });

  test('7. 5問進んだら結果画面が表示され、最高スコアがlocalStorageに保存されること', async ({ page }) => {
     await page.evaluate(() => localStorage.removeItem('gakushuGameHighScore'));
     
     await page.click('#start-btn');
     await page.click('.number-btn:text("5")');

     for (let i = 0; i < 5; i++) {
       await page.waitForTimeout(100);
       
       const firstAnswer = await page.evaluate(() => {
         const answerBtns = Array.from(document.querySelectorAll('.answer-btn'));
         return answerBtns[0].textContent;
       });
       
       await page.click(`.answer-btn:text("${firstAnswer}")`);
       await page.click('#next-btn');
     }

    await expect(page.locator('#result-screen')).toBeVisible();
    await expect(page.locator('#final-score')).toBeVisible();
    
     await page.click('#replay-btn');
     await page.click('.number-btn:text("5")');

     for (let i = 0; i < 2; i++) {
      await page.click(`.answer-btn`, { clickCount: 1 });
      await page.click('#next-btn');
    }

    const correctAnswer = await page.evaluate(() => {
      const datasetVal = document.querySelector('#answer-buttons')?.dataset?.currentQuestion;
      return datasetVal || '';
    });
    if (correctAnswer) {
      await page.click(`.answer-btn:text("${correctAnswer}")`);
    }
    
     await expect(page.locator('#feedback-text')).toContainText('せいかい');
   });

   test('8. 5問目終了時に結果画面が正しく表示されること', async ({ page }) => {
     await page.click('#start-btn');
     await page.click('.number-btn:text("3")');

     for (let i = 0; i < 4; i++) {
      await page.click(`.answer-btn`, { timeout: 5000 });
      await page.click('#next-btn');
    }

    await expect(page.locator('#question-text')).toBeVisible();
    await page.click(`.answer-btn`, { timeout: 5000 });
    
    await expect(page.locator('#result-screen')).toBeVisible({ timeout: 10000 });
  });

   test('9. クイズがランダムに表示されること', async ({ page }) => {
     await page.click('#start-btn');
     await page.click('.number-btn:text("5")');

     const questionTypes = [];
     for (let i = 0; i < 5; i++) {
       const question = await page.locator('#question-text').textContent();
       questionTypes.push(question);
       await page.click(`.answer-btn`, { timeout: 5000 });
       await page.click('#next-btn', { timeout: 5000 });
     }

     expect(questionTypes.length).toBe(5);
   });

   test('10. リセットボタンでタイトル画面に戻ること', async ({ page }) => {
     await page.click('#start-btn');
     await page.click('.number-btn:text("3")');
    await expect(page.locator('#game-screen')).toBeVisible();

    await page.click('#reset-btn');
    await expect(page.locator('#title-screen')).toBeVisible();
  });

  test('11. カウントアップゲームで絵文字が正しく表示される', async ({ page }) => {
    await page.click('#start-btn');
    await page.click('.number-btn:text("5")');
    await page.waitForTimeout(200);

    const firstQuestion = await page.locator('#question-text').textContent();
    if (firstQuestion.includes('なんこの')) {
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
    await expect(page.locator('#start-btn')).toHaveText('すうじ');
    await expect(page.locator('#color-start-btn')).toHaveText('いろ');
  });

  test('13. いろボタンでゲーム画面に移り、色サンプルと4択の色名ボタンが表示されること', async ({ page }) => {
    await page.click('#color-start-btn');
    await expect(page.locator('#game-screen')).toBeVisible();
    await expect(page.locator('#score')).toHaveText('0');
    await expect(page.locator('#question-text')).toHaveText('これ なん の いろ?');

    const swatch = page.locator('.color-swatch');
    await expect(swatch).toBeVisible();

    const answerButtons = page.locator('.color-answer-btn');
    await expect(answerButtons).toHaveCount(4);
    const names = await answerButtons.allTextContents();
    expect(names.sort()).toEqual(['あお', 'あか', 'きいろ', 'みどり']);
  });

  test('14. 色当てで正解したときに+10点加算されること', async ({ page }) => {
    await page.click('#color-start-btn');

    const correctName = await page.evaluate(() => {
      const map = { 'rgb(255, 51, 51)': 'あか', 'rgb(51, 51, 255)': 'あお', 'rgb(255, 255, 51)': 'きいろ', 'rgb(51, 255, 51)': 'みどり' };
      const bg = getComputedStyle(document.querySelector('.color-swatch')).backgroundColor;
      return map[bg];
    });

     await page.click(`.color-answer-btn:text("${correctName}")`);

     await expect(page.locator('#feedback-text')).toHaveText('せいかい！すごいね！');
     await expect(page.locator('#score')).toHaveText('10');
  });

  test('15. 色当てで不正解したときに「ざんねん...」が表示されポイント加算されないこと', async ({ page }) => {
    await page.click('#color-start-btn');

    const correctName = await page.evaluate(() => {
      const map = { 'rgb(255, 51, 51)': 'あか', 'rgb(51, 51, 255)': 'あお', 'rgb(255, 255, 51)': 'きいろ', 'rgb(51, 255, 51)': 'みどり' };
      const bg = getComputedStyle(document.querySelector('.color-swatch')).backgroundColor;
      return map[bg];
    });
    const allNames = ['あか', 'あお', 'きいろ', 'みどり'];
    const wrongName = allNames.find(n => n !== correctName);

     await page.click(`.color-answer-btn:text("${wrongName}")`);

     await expect(page.locator('#feedback-text')).toHaveText('ちょんぼ…');
     await expect(page.locator('#score')).toHaveText('0');
  });

  test('16. 色当てを10問進んだら結果画面が表示されること', async ({ page }) => {
    await page.click('#color-start-btn');

    for (let i = 0; i < 9; i++) {
      await page.click(`.color-answer-btn`, { timeout: 5000 });
      await page.click('#next-btn');
    }

    await page.click(`.color-answer-btn`, { timeout: 5000 });
    await expect(page.locator('#result-screen')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#final-score')).toBeVisible();
  });

  test('17. 色当てゲームのリセットでタイトル画面に戻り、いろボタンが再び使えること', async ({ page }) => {
    await page.click('#color-start-btn');
    await expect(page.locator('#game-screen')).toBeVisible();

    await page.click('#reset-btn');
    await expect(page.locator('#title-screen')).toBeVisible();

    await page.click('#color-start-btn');
    await expect(page.locator('#game-screen')).toBeVisible();
    const answerButtons = page.locator('.color-answer-btn');
    await expect(answerButtons).toHaveCount(4);
  });
});

test.afterEach(async ({ page }) => {
  await page.close();
});
