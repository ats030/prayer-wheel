/* 
 * dekita - Preschool Edition Maze Game Module
 */

export class MazeGame {
  constructor() {
    this.state = window.gameState;
    this.audio = window.audioManager;
    this.screen = window.screenManager;
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

    this.root.getElementById('reset-btn').addEventListener('click', () => {
      this.resetGame();
    });

    this.root.getElementById('next-btn').addEventListener('click', () => {
      this.nextTurn();
    });

    this.root.getElementById('feedback-area').addEventListener('click', () => {
      this.nextTurn();
    });

    const themeButtons = this.root.querySelectorAll('.maze-theme-btn');
    themeButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const theme = parseInt(btn.dataset.theme, 10);
        this.startMazeGame(theme);
      });
    });
  }

  showThemeSelect() {
    this.screen.showMazeThemeSelect();
  }

  startMazeGame(theme) {
    this.state.currentTheme = theme;
    this.state.questionsAnswered = 0;
    this.state.questionsTotal = 5;
    this.state.score = 0;
    this.state.mazeActive = true;
    
    const mazeSize = 7;
    this.state.mazePath = [];
    this.state.mazePlayer = { x: 1, y: 1 };
    this.state.mazeGoal = { x: mazeSize - 2, y: mazeSize - 2 };
    
    this.screen.showGame();
    this.renderMazeCanvas();
    this.updateScore();
  }

  renderMazeCanvas() {
    const canvas = this.root.getElementById('maze-canvas');
    const ctx = canvas.getContext('2d');
    
    const tileSize = 40;
    const margin = 20;
    const size = 7;
    
    canvas.width = size * tileSize + 2 * margin;
    canvas.height = size * tileSize + 2 * margin;
    
    const themes = [
      { name: '蜜蜂', color: '#FFD700' },
      { name: 'うさぎ', color: '#FFFFFF' },
      { name: 'ねこ', color: '#FF69B4' },
      { name: 'さる', color: '#8B4513' }
    ];
    
    const theme = themes[this.state.currentTheme] || themes[0];
    
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const isWall = (x % 2 === 0 || y % 2 === 0) || (x === size - 1 && y === size - 1);
        ctx.fillStyle = isWall ? '#444' : theme.color;
        ctx.fillRect(margin + x * tileSize, margin + y * tileSize, tileSize, tileSize);
      }
    }
    
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(margin + this.state.mazePlayer.x * tileSize + 5, margin + this.state.mazePlayer.y * tileSize + 5, tileSize - 10, tileSize - 10);
    
    ctx.fillStyle = '#00FF00';
    ctx.fillRect(margin + this.state.mazeGoal.x * tileSize + 5, margin + this.state.mazeGoal.y * tileSize + 5, tileSize - 10, tileSize - 10);
    
    canvas.onclick = (e) => {
      const rect = canvas.getBoundingClientRect();
      const x = Math.floor((e.clientX - rect.left - margin) / tileSize);
      const y = Math.floor((e.clientY - rect.top - margin) / tileSize);
      this.movePlayer(x, y);
    };
  }

  movePlayer(x, y) {
    if (x < 0 || y < 0 || x >= 7 || y >= 7) return;
    
    if (x === this.state.mazePlayer.x && y === this.state.mazePlayer.y - 1) {
      this.state.mazePlayer.y--;
    } else if (x === this.state.mazePlayer.x && y === this.state.mazePlayer.y + 1) {
      this.state.mazePlayer.y++;
    } else if (x === this.state.mazePlayer.x - 1 && y === this.state.mazePlayer.y) {
      this.state.mazePlayer.x--;
    } else if (x === this.state.mazePlayer.x + 1 && y === this.state.mazePlayer.y) {
      this.state.mazePlayer.x++;
    }
    
    this.renderMazeCanvas();
    
    if (this.state.mazePlayer.x === this.state.mazeGoal.x && this.state.mazePlayer.y === this.state.mazeGoal.y) {
      this.state.addScore(20);
      this.playCorrectFeedback();
    }
    
    this.updateScore();
  }

  playCorrectFeedback() {
    this.root.getElementById('feedback-area').classList.remove('hidden');
    this.root.getElementById('feedback-text').textContent = 'できた! すごーい!';
    this.root.getElementById('feedback-text').style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  nextTurn() {
    this.root.getElementById('feedback-area').classList.add('hidden');
    this.state.questionsAnswered++;
    
    if (this.state.questionsAnswered >= this.state.questionsTotal) {
      this.endGame();
    } else {
      const mazeSize = 7;
      this.state.mazePlayer = { x: 1, y: 1 };
      this.state.mazeGoal = { x: mazeSize - 2, y: mazeSize - 2 };
      this.renderMazeCanvas();
    }
  }

  updateScore() {
    document.getElementById('score').textContent = this.state.score;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = this.state.score;
    this.state.saveScore();
  }

  resetGame() {
    this.state.gameMode = 'maze';
    this.screen.showTitle();
  }
}
