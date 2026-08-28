/* 
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

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'maze';
  }

  registerEventListeners() {
    this.root.getElementById('maze-start-btn').addEventListener('click', () => {
      this.audio.init();
      this.audio.playPopSound();
      this.showThemeSelect();
    });

    this.root.getElementById('maze-reset-btn').addEventListener('click', () => {
      this.resetGame();
    });

    this.root.getElementById('maze-next-btn').addEventListener('click', () => {
      this.nextTurn();
    });

    const themeButtons = this.root.querySelectorAll('.maze-theme-btn');
    themeButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const themeIndex = parseInt(btn.dataset.theme, 10);
        this.startMazeGame(themeIndex);
      });
    });
  }

  showThemeSelect() {
    this.screen.showMazeThemeSelect();
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
    document.getElementById('maze-score').textContent = '⭐️' + this.state.score;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }
}
