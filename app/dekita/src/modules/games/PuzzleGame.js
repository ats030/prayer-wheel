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
    
    // 1種類の絵文字をランダムに選択
    this.targetEmoji = this.theme.emojis[Math.floor(Math.random() * this.theme.emojis.length)];
    
    // シルエット：外形が同じ（丸い）シルエットを1つ、違うものを8つ
    // 外形の種類（例：丸系、四角系、縦長系、横長系）
    const shapes = ['circle', 'rect', 'vrect', 'hrect'];
    
    this.grid = [];
    let correctIndex = Math.floor(Math.random() * 9);
    
    for (let i = 0; i < 9; i++) {
      const piece = document.createElement('div');
      piece.className = 'puzzle-piece';
      piece.textContent = this.targetEmoji;
      piece.draggable = true;
      piece.dataset.index = i;
      piece.dataset.shape = i === correctIndex ? 'circle' : shapes[i % 4];

      piece.addEventListener('dragstart', (e) => this.handleDragStart(e, i));
      piece.addEventListener('dragover', (e) => e.preventDefault());
      piece.addEventListener('drop', (e) => this.handleDrop(e, i));
      piece.addEventListener('dragenter', (e) => e.preventDefault());
      piece.addEventListener('dragleave', (e) => e.preventDefault());

      this.grid.push({
        element: piece,
        shape: piece.dataset.shape
      });
    }
    
    this.correctIndex = correctIndex;
    
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

    for (let i = 0; i < 9; i++) {
      const slot = document.createElement('div');
      slot.className = 'puzzle-silhouette';
      slot.dataset.index = i;
      slot.dataset.shape = this.grid[i].shape;
      gridArea.appendChild(slot);
    }

    for (let i = 0; i < 9; i++) {
      gridArea.appendChild(this.grid[i].element);
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

    if (this.draggedPiece) {
      this.moves++;
      
      if (targetIndex === this.correctIndex) {
        this.checkWin();
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
  }

  checkWin() {
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
