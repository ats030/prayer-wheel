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
    this.isDragging = false;
  }

  setTestMode(enabled) {
    this.state._testMode = enabled;
  }

  cleanup() {
    this.isDragging = false;
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
    this.state.isAnswering = false;
    
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
    
    console.log('startMazeGame called:', themeIndex);
    console.log('themes[0]:', themes[0]);
    console.log('this.state.themeEmojiStart:', this.state.themeEmojiStart);
    console.log('this.state.themeEmojiEnd:', this.state.themeEmojiEnd);
    
    const canvas = this.root.getElementById('maze-canvas');
    canvas.width = 300;
    canvas.height = 300;
    
    const result = new PathGenerator().generate(canvas.width, canvas.height);
    this.state.mazePath = result.path;
    this.state.mazePlayer = { x: result.player.x, y: result.player.y };
    this.state.mazeGoal = { x: result.goal.x, y: result.goal.y };
    
    this.screen.showMazeGame();
    this.drawMaze();
    this.audio.speak(this.state.mazeCurrentTheme.text);
    this.updateScore();
  }

  updateQuestionText() {
  }

  drawMaze() {
    const canvas = this.root.getElementById('maze-canvas');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    console.log('drawMaze called:');
    console.log('  canvas.width:', canvas.width);
    console.log('  canvas.height:', canvas.height);
    console.log('  ctx:', ctx);
    console.log('  themeEmojiStart:', this.state.themeEmojiStart);
    console.log('  themeEmojiEnd:', this.state.themeEmojiEnd);
    console.log('  mazePath length:', this.state.mazePath.length);
    
    const gridCols = 8;
    const cellSize = canvas.width / gridCols;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 経路を描画
    ctx.beginPath();
    ctx.lineWidth = 10;
    ctx.strokeStyle = '#81D4FA';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (this.state.mazePath.length > 0) {
      ctx.moveTo(this.state.mazePath[0].x, this.state.mazePath[0].y);

      for (let i = 1; i < this.state.mazePath.length; i++) {
        ctx.lineTo(this.state.mazePath[i].x, this.state.mazePath[i].y);
      }
    }
    ctx.stroke();

    // ゴール地点の絵文字
    ctx.font = '36px serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(this.state.themeEmojiEnd, this.state.mazeGoal.x, this.state.mazeGoal.y);

    // 経路外の境界線（失敗判定用）
    ctx.beginPath();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#E57373';
    for (let x = 0; x <= 8; x++) {
      ctx.moveTo(x * cellSize, 0);
      ctx.lineTo(x * cellSize, canvas.height);
    }
    for (let y = 0; y <= 8; y++) {
      ctx.moveTo(0, y * cellSize);
      ctx.lineTo(canvas.width, y * cellSize);
    }
    ctx.stroke();

    const playerSize = 32;
    ctx.font = `${playerSize}px serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(this.state.themeEmojiStart, this.state.mazePlayer.x, this.state.mazePlayer.y);
  }

  resetGame() {
    this.screen.showTitle();
  }

  playCorrectFeedback() {
    const area = this.root.getElementById('maze-feedback-area');
    const text = this.root.getElementById('maze-feedback-text');
    area.style.display = 'block';
    text.textContent = 'やったー！＋10てん';
    text.style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  nextTurn() {
    this.state.mazeActive = true;
    this.isDragging = false;
    this.state.questionsAnswered++;
    
    if (this.state.questionsAnswered >= this.state.questionsTotal) {
      this.endGame();
    } else {
      const canvas = this.root.getElementById('maze-canvas');
      canvas.width = 300;
      canvas.height = 300;
      
      const result = new PathGenerator().generate(canvas.width, canvas.height);
      this.state.mazePath = result.path;
      this.state.mazePlayer = { x: result.player.x, y: result.player.y };
      this.state.mazeGoal = { x: result.goal.x, y: result.goal.y };
      
      this.drawMaze();
      this.updateScore();
      this.audio.speak(this.state.mazeCurrentTheme.text);
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

    // マウスイベント
    canvas.addEventListener('mousedown', (e) => {
      if (!this.state.mazeActive) return;
      this.isDragging = true;
      e.preventDefault();
    }, { passive: false });

    canvas.addEventListener('mousemove', (e) => {
      if (!this.state.mazeActive || !this.isDragging) return;
      e.preventDefault();
      
      const rect = canvas.getBoundingClientRect();
      const scaleX = rect.width / canvas.width;
      const scaleY = rect.height / canvas.height;
      
      const x = (e.clientX - rect.left) * scaleX;
      const y = (e.clientY - rect.top) * scaleY;
      
      this.dragPlayer(x, y);
    }, { passive: false });

    canvas.addEventListener('mouseup', (e) => {
      if (!this.state.mazeActive || !this.isDragging) return;
      this.isDragging = false;
      
      const rect = canvas.getBoundingClientRect();
      const scaleX = rect.width / canvas.width;
      const scaleY = rect.height / canvas.height;
      
      const x = (e.clientX - rect.left) * scaleX;
      const y = (e.clientY - rect.top) * scaleY;
      
      this.releasePlayer(x, y);
    });

    canvas.addEventListener('mouseleave', () => {
      if (this.isDragging) {
        this.isDragging = false;
      }
    });

    // タッチイベント
    canvas.addEventListener('touchstart', (e) => {
      if (!this.state.mazeActive) return;
      this.isDragging = true;
      e.preventDefault();
    }, { passive: false });

    canvas.addEventListener('touchmove', (e) => {
      if (!this.state.mazeActive || !this.isDragging) return;
      e.preventDefault();
      
      const rect = canvas.getBoundingClientRect();
      const scaleX = rect.width / canvas.width;
      const scaleY = rect.height / canvas.height;
      
      const touch = e.touches[0];
      const x = (touch.clientX - rect.left) * scaleX;
      const y = (touch.clientY - rect.top) * scaleY;
      
      this.dragPlayer(x, y);
    }, { passive: false });

    canvas.addEventListener('touchend', (e) => {
      if (!this.state.mazeActive || !this.isDragging) return;
      this.isDragging = false;
      
      const rect = canvas.getBoundingClientRect();
      const scaleX = rect.width / canvas.width;
      const scaleY = rect.height / canvas.height;
      
      const touch = e.changedTouches[0];
      const x = (touch.clientX - rect.left) * scaleX;
      const y = (touch.clientY - rect.top) * scaleY;
      
      this.releasePlayer(x, y);
    });

    canvas.addEventListener('touchcancel', () => {
      if (this.isDragging) {
        this.isDragging = false;
      }
    });
  }

  isPath(x, y) {
    if (!this.state.mazePath || this.state.mazePath.length < 2) return true;

    const cellSize = this.state.mazePath.length > 0 ? (300 / 8) : 37.5;
    const margin = cellSize / 2 + 15;

    for (let i = 0; i < this.state.mazePath.length - 1; i++) {
      const p1 = this.state.mazePath[i];
      const p2 = this.state.mazePath[i + 1];

      if (Math.abs(p1.x - p2.x) < 1e-10) {
        const minX = Math.min(p1.x, p2.x) - margin;
        const maxX = Math.max(p1.x, p2.x) + margin;
        const minY = Math.min(p1.y, p2.y) - margin;
        const maxY = Math.max(p1.y, p2.y) + margin;

        if (x >= minX && x <= maxX && y >= minY && y <= maxY) {
          return true;
        }
      } else if (Math.abs(p1.y - p2.y) < 1e-10) {
        const minY = Math.min(p1.y, p2.y) - margin;
        const maxY = Math.max(p1.y, p2.y) + margin;
        const minX = Math.min(p1.x, p2.x) - margin;
        const maxX = Math.max(p1.x, p2.x) + margin;

        if (y >= minY && y <= maxY && x >= minX && x <= maxX) {
          return true;
        }
      }
    }

    return false;
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

  dragPlayer(x, y) {
    if (this.state.isAnswering) return;
    if (!this.isPath(x, y)) {
      this.failMaze();
      return;
    }
    
    this.state.mazePlayer.x = x;
    this.state.mazePlayer.y = y;
    this.drawMaze();
  }

  releasePlayer(x, y) {
    if (this.state.isAnswering) return;
    if (!this.isPath(x, y)) {
      this.failMaze();
      return;
    }

    const goal = this.state.mazeGoal;
    const dx = x - goal.x;
    const dy = y - goal.y;
    const distance = Math.sqrt(dx * dx + dy * dy);

    if (distance < 30) {
      this.state.isAnswering = true;
      this.winMaze(x, y);
    } else {
      this.state.mazePlayer.x = x;
      this.state.mazePlayer.y = y;
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
      area.style.display = 'block';
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
      area.style.display = 'block';
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
    this.root.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
  }
}
