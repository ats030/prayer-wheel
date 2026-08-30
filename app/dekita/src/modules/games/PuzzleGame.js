/**
 * dekita - Preschool Edition Puzzle Game Module
 * For 3-year-olds: Drag and drop puzzle with silhouette matching
 */

export class PuzzleGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
    this.gridSize = 3;
    this.grid = [];
    this.draggedPiece = null;
    this.score = 0;
    this.moves = 0;
    this.gameOver = false;
    this.theme = null;
    this.emojis = ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨'];
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'puzzle';
  }

  registerEventListeners() {
    const puzzleStartBtn = this.root.getElementById('puzzle-start-btn');
    if (puzzleStartBtn) {
      puzzleStartBtn.addEventListener('click', () => {
        this.audio.init();
        this.audio.playPopSound();
        this.start();
      });
    }

    const puzzleResetBtn = this.root.getElementById('puzzle-reset-btn');
    if (puzzleResetBtn) {
      puzzleResetBtn.addEventListener('click', () => {
        this.resetGame();
      });
    }

    const puzzleNextBtn = this.root.getElementById('puzzle-next-btn');
    if (puzzleNextBtn) {
      puzzleNextBtn.addEventListener('click', () => {
        this.audio.playPopSound();
        this.nextRound();
      });
    }
  }

  start() {
    this.score = 0;
    this.moves = 0;
    this.gameOver = false;
    this.draggedPiece = null;
    this.state.questionsAnswered = 0;
    this.state.questionsTotal = 5;
    this.screen.showPuzzleGame();
    this.generatePuzzle();
  }

  getGridArea() {
    return this.root.getElementById('puzzle-grid');
  }

  generatePuzzle() {
    const themes = [
      { name: 'どうぶつ', emojis: ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨'] },
      { name: 'かみもの', emojis: ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒'] },
      { name: 'のりもの', emojis: ['🚗', '🚕', '🚙', '🚌', '🚎', '🏎️', '🚓', '🚑', '🚒'] }
    ];
    
    this.theme = themes[Math.floor(Math.random() * themes.length)];
    this.pieces = [...this.theme.emojis];
    
    for (let i = this.pieces.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [this.pieces[i], this.pieces[j]] = [this.pieces[j], this.pieces[i]];
    }
    
    this.createGrid();
  }

  createGrid() {
    const gridArea = this.getGridArea();
    if (!gridArea) return;

    gridArea.innerHTML = '';
    gridArea.style.display = 'grid';
    gridArea.style.gridTemplateColumns = `repeat(${this.gridSize}, 100px)`;
    gridArea.style.gridTemplateRows = `repeat(${this.gridSize}, 100px)`;
    gridArea.style.gap = '8px';
    gridArea.style.margin = '0 auto';

    for (let i = 0; i < this.gridSize * this.gridSize; i++) {
      const slot = document.createElement('div');
      slot.className = 'puzzle-silhouette';
      slot.dataset.index = i;
      slot.dataset.correctEmoji = this.theme.emojis[i];
      gridArea.appendChild(slot);
    }

    this.grid = [];
    for (let i = 0; i < this.gridSize * this.gridSize; i++) {
      const piece = document.createElement('div');
      piece.className = 'puzzle-piece';
      piece.textContent = this.pieces[i];
      piece.draggable = true;
      piece.dataset.index = i;

      piece.addEventListener('dragstart', (e) => this.handleDragStart(e, i));
      piece.addEventListener('dragover', (e) => e.preventDefault());
      piece.addEventListener('drop', (e) => this.handleDrop(e, i));
      piece.addEventListener('dragenter', (e) => e.preventDefault());
      piece.addEventListener('dragleave', (e) => e.preventDefault());

      gridArea.appendChild(piece);
      
      this.grid.push({
        element: piece,
        correctEmoji: this.theme.emojis[i],
        currentEmoji: this.pieces[i]
      });
    }

    this.updateProgress();
  }

  handleDragStart(e, index) {
    this.draggedPiece = this.grid[index];
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', index.toString());
    setTimeout(() => e.target.style.opacity = '0.5', 0);
  }

  handleDrop(e, targetIndex) {
    e.preventDefault();
    if (this.draggedPiece) {
      this.draggedPiece.element.style.opacity = '1';
    }

    const targetSlot = this.grid[targetIndex];
    
    if (this.draggedPiece && this.draggedPiece !== targetSlot) {
      const tempEmoji = targetSlot.currentEmoji;
      targetSlot.element.textContent = this.draggedPiece.currentEmoji;
      targetSlot.currentEmoji = this.draggedPiece.currentEmoji;
      
      this.draggedPiece.element.textContent = tempEmoji;
      this.draggedPiece.currentEmoji = tempEmoji;

      this.moves++;
      this.checkWin();
    }
  }

  checkWin() {
    const isWin = this.grid.every((cell) => cell.correctEmoji === cell.currentEmoji);
    
    if (isWin) {
      this.state.addScore(20);
      this.playCorrectFeedback();
      
      if (this.state.isGameOver()) {
        setTimeout(() => this.endGame(), 2000);
      } else {
        setTimeout(() => this.nextQuestion(), 2000);
      }
    }
  }

  playCorrectFeedback() {
    const area = this.root.getElementById('puzzle-feedback-area');
    const text = this.root.getElementById('puzzle-feedback-text');
    area.style.display = 'block';
    text.textContent = 'やったー！＋20てん';
    text.style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  nextQuestion() {
    this.state.incrementQuestionsAnswered();
    this.root.getElementById('puzzle-feedback-area').classList.add('hidden');
    
    if (this.state.isGameOver()) {
      this.endGame();
    } else {
      this.generatePuzzle();
    }
  }

  nextRound() {
    this.screen.showTitle();
  }

  resetGame() {
    this.screen.showTitle();
  }

  updateProgress() {
    const progressElement = this.root.getElementById('puzzle-progress-text');
    if (progressElement) {
      progressElement.textContent = `${this.state.questionsAnswered + 1}/${this.state.questionsTotal} 問`;
    }
  }

  endGame() {
    this.gameOver = true;
    const area = this.root.getElementById('puzzle-feedback-area');
    const text = this.root.getElementById('puzzle-feedback-text');
    area.style.display = 'block';
    text.textContent = `せいかい！ スコア：${this.state.score}`;
    this.audio.playPopSound();
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }
}
