/**
 * dekita - Preschool Edition Match Game Module
 * Memory card matching game (grid layout)
 */

export class MatchGame {
  constructor(gameState, audio, screen) {
    this.gameState = gameState;
    this.audio = audio;
    this.screen = screen;
    this.gridSize = 4;
    this.emojis = ['🐶', '🐱', '🐭', '🐹'];
    this.grid = [];
    this.score = 0;
    this.moves = 0;
    this.matchesFound = 0;
    this.maxMatches = Math.floor((this.gridSize * this.gridSize) / 2);
    this.selectedCells = [];
    this.matchedIndices = new Set();
    this.gameOver = false;
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
  }

  registerEventListeners() {
    const matchStartBtn = this.root.getElementById('match-start-btn');
    if (matchStartBtn) {
      matchStartBtn.addEventListener('click', () => {
        this.audio.init();
        this.audio.playPopSound();
        this.start();
      });
    }

    const matchResetBtn = this.root.getElementById('match-reset-btn');
    if (matchResetBtn) {
      matchResetBtn.addEventListener('click', () => {
        this.resetGame();
      });
    }

    const matchNextBtn = this.root.getElementById('match-next-btn');
    if (matchNextBtn) {
      matchNextBtn.addEventListener('click', () => {
        this.audio.playPopSound();
        this.nextRound();
      });
    }
  }

  start() {
    this.score = 0;
    this.moves = 0;
    this.matchesFound = 0;
    this.maxMatches = Math.floor((this.gridSize * this.gridSize) / 2);
    this.selectedCells = [];
    this.matchedIndices = new Set();
    this.gameOver = false;
    
    this.screen.showMatchGame();
    this.initGrid();
    this.updateScore();
  }

  initGrid() {
    const totalCells = this.gridSize * this.gridSize;
    const pairsNeeded = totalCells / 2;
    let cellValues = [];

    // Create pairs
    for (let i = 0; i < pairsNeeded; i++) {
      const emoji = this.emojis[i % this.emojis.length];
      cellValues.push(emoji, emoji);
    }

    // Shuffle
    for (let i = cellValues.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [cellValues[i], cellValues[j]] = [cellValues[j], cellValues[i]];
    }

    // Build 2D grid
    this.grid = [];
    for (let y = 0; y < this.gridSize; y++) {
      const row = [];
      for (let x = 0; x < this.gridSize; x++) {
        row.push({
          x,
          y,
          value: cellValues[y * this.gridSize + x],
          revealed: false,
          matched: false
        });
      }
      this.grid.push(row);
    }

    this.renderGrid();
  }

  renderGrid() {
    const gridArea = this.root.getElementById('match-grid');
    if (!gridArea) return;

    gridArea.innerHTML = '';
    gridArea.style.display = 'grid';
    gridArea.style.gridTemplateColumns = `repeat(${this.gridSize}, 64px)`;
    gridArea.style.gridTemplateRows = `repeat(${this.gridSize}, 64px)`;
    gridArea.style.gap = '8px';
    gridArea.style.margin = '0 auto';

    for (let y = 0; y < this.gridSize; y++) {
      for (let x = 0; x < this.gridSize; x++) {
        const cell = this.grid[y][x];
        const card = document.createElement('button');
        card.className = 'match-card';
        card.dataset.x = x;
        card.dataset.y = y;
        card.style.width = '64px';
        card.style.height = '64px';
        card.style.fontSize = '32px';
        card.style.border = '2px solid #4CAF50';
        card.style.borderRadius = '8px';
        card.style.background = 'linear-gradient(135deg, #e8f5e9, #c8e6c9)';
         card.textContent = '❓';
        
        card.addEventListener('click', () => this.handleCardClick(x, y));
        gridArea.appendChild(card);
      }
    }
  }

  handleCardClick(x, y) {
    if (this.gameOver) return;
    
    const cell = this.grid[y][x];
    if (cell.matched || cell.revealed) return;
    
    cell.revealed = true;
    const cardBtn = this.getCardButton(x, y);
    if (cardBtn) {
      cardBtn.textContent = cell.value;
      cardBtn.style.background = '#fff';
    }
    
    this.selectedCells.push(cell);
    
    if (this.selectedCells.length === 2) {
      this.moves++;
      this.checkMatch();
    }
  }

  getCardButton(x, y) {
    return this.root.querySelector(`.match-card[data-x="${x}"][data-y="${y}"]`);
  }

  checkMatch() {
    const [cell1, cell2] = this.selectedCells;
    const isMatch = cell1.value === cell2.value;

    if (isMatch) {
      cell1.matched = true;
      cell2.matched = true;
      this.matchedIndices.add(cell1.y * this.gridSize + cell1.x);
      this.matchedIndices.add(cell2.y * this.gridSize + cell2.x);
      this.score += 10;
      this.matchesFound++;
      this.selectedCells = [];
      
      // Update card UI
      const btn1 = this.getCardButton(cell1.x, cell1.y);
      const btn2 = this.getCardButton(cell2.x, cell2.y);
      if (btn1) {
        btn1.style.background = '#4CAF50';
        btn1.style.color = '#fff';
      }
      if (btn2) {
        btn2.style.background = '#4CAF50';
        btn2.style.color = '#fff';
      }
      
      this.updateScore();
      
      if (this.matchesFound >= this.maxMatches) {
        this.endGame();
      }
    } else {
      setTimeout(() => {
        cell1.revealed = false;
        cell2.revealed = false;
        const btn1 = this.getCardButton(cell1.x, cell1.y);
        const btn2 = this.getCardButton(cell2.x, cell2.y);
        if (btn1) {
            btn1.textContent = '❓';
          btn1.style.background = 'linear-gradient(135deg, #e8f5e9, #c8e6c9)';
        }
        if (btn2) {
            btn2.textContent = '❓';
          btn2.style.background = 'linear-gradient(135deg, #e8f5e9, #c8e6c9)';
        }
        this.selectedCells = [];
      }, 800);
    }
  }

  updateScore() {
    this.root.getElementById('match-score').textContent = '⭐️' + this.score;
    this.root.getElementById('match-progress-text').textContent = 
      `${this.matchesFound}/${this.maxMatches} ペア`;
  }

  nextRound() {
    this.screen.showTitle();
  }

  resetGame() {
    this.screen.showTitle();
  }

  endGame() {
    this.gameOver = true;
    const feedbackArea = this.root.getElementById('match-feedback-area');
    const feedbackText = this.root.getElementById('match-feedback-text');
    feedbackArea.style.display = 'block';
    feedbackText.textContent = `せいかい！ スコア：${this.score}`;
    this.audio.playPopSound();
  }
}
