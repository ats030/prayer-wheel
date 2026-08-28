/**
 * dekita - Preschool Edition Maze Game Module
 * For 3-year-olds: tap-to-move, visual learning, no reading required
 */

import { PathGenerator } from '../utils/maze/PathGenerator.js';

export class MazeGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
    this.pathGenerator = new PathGenerator();
  }

  setTestMode(enabled) {
    this.state._testMode = enabled;
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.initMazeEvents();
    this.state.gameMode = 'maze';
  }

  registerEventListeners() {
    this.root.getElementById('maze-start-btn').addEventListener('click', () => {
      this.audio.init();
      this.audio.playPopSound();
      this.startMazeGame(0);
    });

    this.root.getElementById('maze-reset-btn').addEventListener('click', () => {
      this.resetGame();
    });

    this.root.getElementById('maze-next-btn').addEventListener('click', () => {
      this.nextTurn();
    });
  }

  startMazeGame(themeIndex) {
    this.state.questionsAnswered = 0;
    this.state.questionsTotal = 5;
    this.state.score = 0;
    this.state.mazeActive = true;
    
    // テーマ設定
    const themes = [
      { start: '🐝', end: '🌸', text: 'はちさんが おはなまで いけるかな?' },
      { start: '🐰', end: '🥕', text: 'うさぎさんが にんじんまで いけるかな?' },
      { start: '🐱', end: '🐟', text: 'ねこさんが おさかなまで いけるかな?' },
      { start: '🐵', end: '🍌', text: 'さるさんが バナナまで いけるかな?' }
    ];
    
    this.state.mazeCurrentTheme = themes[themeIndex] || themes[0];
    this.state.themeEmojiStart = this.state.mazeCurrentTheme.start;
    this.state.themeEmojiEnd = this.state.mazeCurrentTheme.end;
    this.state.mazeQuestionText = this.state.mazeCurrentTheme.text;
    
    this.updateQuestionText();
    
    const canvas = this.root.getElementById('maze-canvas');
    canvas.width = 300;
    canvas.height = 300;
    
    // 経路生成
    const result = this.pathGenerator.generate(canvas.width, canvas.height);
    this.state.mazePath = result.path;
    this.state.mazePlayer = { x: result.player.x, y: result.player.y };
    this.state.mazeGoal = { x: result.goal.x, y: result.goal.y };
    
    this.screen.showMazeGame();
    this.drawMaze();
    this.updateScore();
    
    // 音声ガイド
    this.audio.speak(this.state.mazeQuestionText);
  }

  updateQuestionText() {
    const questionText = this.root.getElementById('question-text');
    if (questionText) {
      questionText.textContent = this.state.mazeQuestionText;
    }
  }

  drawMaze() {
    const canvas = this.root.getElementById('maze-canvas');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    this.pathGenerator.draw(ctx, canvas.width, canvas.height, this.state.themeEmojiStart, this.state.themeEmojiEnd);
    
    // プレイヤーの位置を更新
    const playerSize = 32;
    ctx.font = `${playerSize}px serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(this.state.themeEmojiStart, this.state.mazePlayer.x, this.state.mazePlayer.y);
  }

  resetGame() {
    this.state.gameMode = 'maze';
    this.screen.showTitle();
  }

  playCorrectFeedback() {
    const area = this.root.getElementById('maze-feedback-area');
    const text = this.root.getElementById('maze-feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'やったー！';
    text.style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  nextTurn() {
    this.root.getElementById('maze-feedback-area').classList.add('hidden');
    this.state.questionsAnswered++;
    
    if (this.state.questionsAnswered >= this.state.questionsTotal) {
      this.endGame();
    } else {
      const canvas = this.root.getElementById('maze-canvas');
      canvas.width = 300;
      canvas.height = 300;
      
      // 新しい経路生成
      const result = this.pathGenerator.generate(canvas.width, canvas.height);
      this.state.mazePath = result.path;
      this.state.mazePlayer = { x: result.player.x, y: result.player.y };
      this.state.mazeGoal = { x: result.goal.x, y: result.goal.y };
      
      this.drawMaze();
      this.updateScore();
    }
  }

  updateScore() {
    const scoreEl = this.root.getElementById('maze-score');
    if (scoreEl) {
      scoreEl.textContent = '⭐️' + this.state.score;
    }
  }

  initMazeEvents() {
    const canvas = this.root.getElementById('maze-canvas');
    if (!canvas) return;

    canvas.addEventListener('click', (e) => {
      if (!this.state.mazeActive) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;

      const clickX = (e.clientX - rect.left) * scaleX;
      const clickY = (e.clientY - rect.top) * scaleY;

      this.movePlayerTo(clickX, clickY);
    });
  }

  isPath(x, y) {
    if (!this.state.mazePath || this.state.mazePath.length < 2) return true;

    let onPath = false;
    for (let i = 0; i < this.state.mazePath.length - 1; i++) {
      const p1 = this.state.mazePath[i];
      const p2 = this.state.mazePath[i + 1];

      const dx = p2.x - p1.x;
      const dy = p2.y - p1.y;
      const lenSq = dx * dx + dy * dy;

      if (lenSq === 0) continue;

      const t = ((x - p1.x) * dx + (y - p1.y) * dy) / lenSq;
      const clampedT = Math.max(0, Math.min(1, t));

      const closestX = p1.x + clampedT * dx;
      const closestY = p1.y + clampedT * dy;

      const distSq = (x - closestX) * (x - closestX) + (y - closestY) * (y - closestY);

      if (distSq < 400) {
        onPath = true;
        break;
      }
    }

    return onPath;
  }

  movePlayerTo(targetX, targetY) {
    if (!this.isPath(targetX, targetY)) {
      this.failMaze();
      return;
    }

    const goal = this.state.mazeGoal;
    const dx = targetX - goal.x;
    const dy = targetY - goal.y;
    const distance = Math.sqrt(dx * dx + dy * dy);

    if (distance < 30) {
      this.winMaze(targetX, targetY);
    } else {
      this.state.mazePlayer.x = targetX;
      this.state.mazePlayer.y = targetY;
      this.drawMaze();
    }
  }

  failMaze() {
    console.log('failMaze() called');
    this.state.mazeActive = false;
    const area = this.root.getElementById('maze-feedback-area');
    const text = this.root.getElementById('maze-feedback-text');
    console.log('area:', area, 'text:', text);
    if (area && text) {
      area.classList.remove('hidden');
      text.textContent = 'だいじょうぶ！もういっこ！';
      text.style.color = '#FF9800';
      this.audio.speak('だいじょうぶ！もういっこ！');
      this.audio.playPopSound();
    }
  }

  winMaze(x, y) {
    this.state.mazeActive = false;
    this.state.mazePlayer.x = x;
    this.state.mazePlayer.y = y;
    this.drawMaze();

    const area = this.root.getElementById('maze-feedback-area');
    const text = this.root.getElementById('maze-feedback-text');

    if (area && text) {
      area.classList.remove('hidden');
      text.textContent = 'やったー！＋10てん';
      text.style.color = '#4CAF50';
      this.state.score += 10;
      this.updateScore();
      this.audio.speak('やったー！10てん！');
      this.audio.playPopSound();

      setTimeout(() => {
        this.nextTurn();
      }, 1500);
    }
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }

  setTestMode(enabled) {
    this.state._testMode = enabled;
  }
}
