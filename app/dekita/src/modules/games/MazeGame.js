/* 
 * dekita - Preschool Edition Maze Game Module
 * For 3-year-olds: tap-to-move, visual learning, no reading required
 */

export class MazeGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
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
    this.state.mazePlayer = { x: 1, y: 1 };
    this.state.mazeGoal = { x: mazeSize - 2, y: mazeSize - 2 };
    
    this.screen.showMazeGame();
    this.renderMazeCanvas();
    this.updateScore();
  }

  renderMazeCanvas() {
    const canvas = this.root.getElementById('maze-canvas');
    const ctx = canvas.getContext('2d');
    
    const tileSize = 50;
    const margin = 10;
    const size = 7;
    
    canvas.width = size * tileSize + 2 * margin;
    canvas.height = size * tileSize + 2 * margin;
    
    const themes = [
      { name: 'Mite', color: '#FFD700' },
      { name: 'Uzuki', color: '#FFFFFF' },
      { name: 'Neko', color: '#FF69B4' },
      { name: 'Saru', color: '#8B4513' }
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
    ctx.beginPath();
    ctx.arc(
      margin + this.state.mazePlayer.x * tileSize + tileSize / 2,
      margin + this.state.mazePlayer.y * tileSize + tileSize / 2,
      tileSize / 3, 0, Math.PI * 2
    );
    ctx.fill();
    
    ctx.fillStyle = '#00FF00';
    ctx.beginPath();
    ctx.arc(
      margin + this.state.mazeGoal.x * tileSize + tileSize / 2,
      margin + this.state.mazeGoal.y * tileSize + tileSize / 2,
      tileSize / 2, 0, Math.PI * 2
    );
    ctx.fill();
    
    canvas.onclick = (e) => {
      const rect = canvas.getBoundingClientRect();
      const x = Math.floor((e.clientX - rect.left - margin) / tileSize);
      const y = Math.floor((e.clientY - rect.top - margin) / tileSize);
      this.movePlayer(x, y);
    };
  }

  movePlayer(x, y) {
    if (x < 0 || y < 0 || x >= 7 || y >= 7) return;
    
    const dx = Math.abs(x - this.state.mazePlayer.x);
    const dy = Math.abs(y - this.state.mazePlayer.y);
    
    if ((dx === 1 && dy === 0) || (dx === 0 && dy === 1)) {
      this.state.mazePlayer.x = x;
      this.state.mazePlayer.y = y;
      this.renderMazeCanvas();
    }
    
    if (this.state.mazePlayer.x === this.state.mazeGoal.x && this.state.mazePlayer.y === this.state.mazeGoal.y) {
      this.state.addScore(20);
      this.playCorrectFeedback();
    }
    
    this.updateScore();
  }

  playCorrectFeedback() {
    const area = this.root.getElementById('maze-feedback-area');
    const text = this.root.getElementById('maze-feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'できた! すごーい!';
    text.style.color = '#4CAF50';
    this.audio.speak('できた! すごーい!');
    this.audio.playPopSound();
  }

  nextTurn() {
    this.root.getElementById('maze-feedback-area').classList.add('hidden');
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
    document.getElementById('maze-score').textContent = '⭐️' + this.state.score;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }
  resetGame() {
    this.state.gameMode = 'maze';
    this.screen.showTitle();
  }

  handleCanvasClick(x, y) {
    const margin = 10;
    const tileSize = 50;
    const mazeSize = 7;
    
    if (x < 0 || y < 0 || x >= mazeSize || y >= mazeSize) return;
    
    const dx = Math.abs(x - this.state.mazePlayer.x);
    const dy = Math.abs(y - this.state.mazePlayer.y);
    
    if ((dx === 1 && dy === 0) || (dx === 0 && dy === 1)) {
      this.state.mazePlayer.x = x;
      this.state.mazePlayer.y = y;
      this.renderMazeCanvas();
    }
    
    if (this.state.mazePlayer.x === this.state.mazeGoal.x && this.state.mazePlayer.y === this.state.mazeGoal.y) {
      this.state.addScore(20);
      this.playCorrectFeedback();
    }
    
    this.updateScore();
  }
}
