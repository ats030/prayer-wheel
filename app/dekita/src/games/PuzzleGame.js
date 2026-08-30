/**
 * dekita - Preschool Edition Puzzle Game Module
 * For 3-year-olds: Drag and drop puzzle with silhouette matching
 * 3x3 grid with silhouettes, drag the correct emoji from outside to match
 */

export class PuzzleGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
    this.gridSize = 3;
    this.draggedEmoji = null;
    this.score = 0;
    this.moves = 0;
    this.gameOver = false;
    this.theme = null;
    this.silhouettes = [];
    this.correctIndex = 0;
    this.correctEmoji = '';
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
    this.draggedEmoji = null;
    this.state.questionsAnswered = 0;
    this.state.questionsTotal = 5;
    this.screen.showPuzzleGame();
    this.generatePuzzle();
  }

  getGridArea() {
    return this.root.getElementById('puzzle-grid');
  }

  getDragEmojiArea() {
    return this.root.getElementById('puzzle-drag-emoji');
  }

  generatePuzzle() {
    const themes = [
      { name: 'どうぶつ', emojis: ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨'] },
      { name: 'かみもの', emojis: ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒'] },
      { name: 'のりもの', emojis: ['🚗', '🚕', '🚙', '🚌', '🚎', '🏎️', '🚓', '🚑', '🚒'] }
    ];
    
    this.theme = themes[Math.floor(Math.random() * themes.length)];
    const shuffledEmojis = [...this.theme.emojis].sort(() => Math.random() - 0.5);
    this.silhouettes = shuffledEmojis.slice(0, 9);
    this.correctIndex = Math.floor(Math.random() * 9);
    this.correctEmoji = this.silhouettes[this.correctIndex];
    
    this.createGrid();
    this.updateDragEmoji();
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

    for (let i = 0; i < 9; i++) {
      const slot = document.createElement('div');
      slot.className = 'puzzle-silhouette';
      slot.dataset.index = i;
      slot.dataset.emoji = this.silhouettes[i];
      slot.textContent = this.silhouettes[i];
      slot.style.filter = 'brightness(20%)';
      gridArea.appendChild(slot);
    }

    const targetSlot = gridArea.children[this.correctIndex];
    targetSlot.style.filter = 'brightness(20%)';

    targetSlot.addEventListener('dragover', (e) => this.handleDragOver(e));
    targetSlot.addEventListener('drop', (e) => this.handleDrop(e));
    targetSlot.addEventListener('dragenter', (e) => e.preventDefault());
    targetSlot.addEventListener('dragleave', (e) => e.preventDefault());
    
    for (let i = 0; i < 9; i++) {
      const slot = gridArea.children[i];
      slot.removeEventListener('dragover', (e) => this.handleDragOver(e));
      slot.removeEventListener('drop', (e) => this.handleDrop(e));
      slot.removeEventListener('dragenter', (e) => e.preventDefault());
      slot.removeEventListener('dragleave', (e) => e.preventDefault());
    }
  }

  updateDragEmoji() {
    const dragArea = this.getDragEmojiArea();
    if (dragArea) {
      dragArea.textContent = this.correctEmoji;
      dragArea.style.opacity = '1.0';
      dragArea.draggable = true;
      
      dragArea.removeEventListener('dragstart', this.handleDragStart.bind(this));
      dragArea.removeEventListener('dragend', this.handleDragEnd.bind(this));
      
      dragArea.addEventListener('dragstart', (e) => this.handleDragStart(e));
      dragArea.addEventListener('dragend', (e) => this.handleDragEnd(e));
    }
  }

  handleDragStart(e) {
    this.draggedEmoji = this.correctEmoji;
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('text/plain', this.correctEmoji);
    e.target.style.opacity = '0.5';
  }

  handleDragEnd(e) {
    e.target.style.opacity = '1.0';
    this.draggedEmoji = null;
  }

  handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }

  handleDrop(e) {
    e.preventDefault();
    
    const targetSlot = e.target.closest('.puzzle-silhouette');
    if (!targetSlot) {
      return;
    }

    const targetIndex = parseInt(targetSlot.dataset.index, 10);
    
    if (targetIndex === this.correctIndex) {
      this.checkWin(targetSlot);
    } else {
      this.audio.playErrorSound();
      const area = this.root.getElementById('puzzle-feedback-area');
      const text = this.root.getElementById('puzzle-feedback-text');
      area.style.display = 'block';
      text.textContent = '違うかも...';
      text.style.color = '#FF5722';
      setTimeout(() => {
        area.style.display = 'none';
      }, 1000);
    }
  }

  checkWin(targetSlot) {
    targetSlot.style.opacity = '1.0';
    targetSlot.style.borderColor = '#4CAF50';
    targetSlot.classList.remove('puzzle-silhouette');
    targetSlot.classList.add('revealed');

    this.state.addScore(20);
    this.playCorrectFeedback();
    
    if (this.state.isGameOver()) {
      setTimeout(() => this.endGame(), 2000);
    } else {
      setTimeout(() => this.nextQuestion(), 2000);
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
