/**
 * dekita - Preschool Edition Puzzle Game Module
 * For 3-year-olds: 3x3 picture puzzle (shuffle and arrange)
 */

export class PuzzleGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
    this.gridSize = 3;
    this.grid = [];
    this.selectedIndex = null;
    this.score = 0;
    this.moves = 0;
    this.gameOver = false;
    this.theme = null;
    this.emojis = ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯', '🦁', '🐮', '🐷', '🐸', '🐵', '🐔'];
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'puzzle';
    this.style = this.getRootStyle();
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
    this.selectedIndex = null;
    this.state.questionsAnswered = 0;
    this.state.questionsTotal = 5;
    this.screen.showPuzzleGame();
    this.generatePuzzle();
  }

  getRootStyle() {
    return this.root.getElementById('puzzle-grid');
  }

  generatePuzzle() {
    // テーマ選択（動物、果物、乗り物など）
    const themes = [
      { name: 'どうぶつ', emojis: ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨'] },
      { name: 'かみもの', emojis: ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒'] },
      { name: 'のりもの', emojis: ['🚗', '🚕', '🚙', '🚌', '🚎', '🏎️', '🚓', '🚑', '🚒'] }
    ];
    
    this.theme = themes[Math.floor(Math.random() * themes.length)];
    this.themeEmojis = [...this.theme.emojis]; // スプレッドでコピー
    
    // シャッフル
    for (let i = this.themeEmojis.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [this.themeEmojis[i], this.themeEmojis[j]] = [this.themeEmojis[j], this.themeEmojis[i]];
    }
    
    this.createGrid();
  }

  createGrid() {
    const gridArea = this.root.getElementById('puzzle-grid');
    if (!gridArea) return;

    gridArea.innerHTML = '';
    gridArea.style.display = 'grid';
    gridArea.style.gridTemplateColumns = `repeat(${this.gridSize}, 80px)`;
    gridArea.style.gridTemplateRows = `repeat(${this.gridSize}, 80px)`;
    gridArea.style.gap = '4px';
    gridArea.style.margin = '0 auto';

    this.grid = [];
    
    for (let i = 0; i < this.gridSize * this.gridSize; i++) {
      const cell = {
        index: i,
        correctValue: this.theme.emojis[i], // 正解の絵文字
        currentValue: this.themeEmojis[i], // 現在の絵文字
        element: null
      };
      this.grid.push(cell);

      const piece = document.createElement('button');
      piece.className = 'puzzle-piece';
      piece.dataset.index = i;
      piece.textContent = cell.currentValue;
      piece.style.fontSize = '48px';
      piece.style.width = '80px';
      piece.style.height = '80px';
      piece.style.background = '#f0f0f0';
      piece.style.border = '2px solid #ccc';
      piece.style.borderRadius = '8px';
      piece.style.display = 'flex';
      piece.style.justifyContent = 'center';
      piece.style.alignItems = 'center';
      piece.style.cursor = 'pointer';
      piece.style.transition = 'all 0.2s';

      piece.addEventListener('click', () => this.handlePieceClick(i));
      gridArea.appendChild(piece);
      cell.element = piece;
    }

    this.updateProgress();
  }

  handlePieceClick(index) {
    if (this.gameOver) return;

    const cell = this.grid[index];
    
    if (this.selectedIndex === null) {
      // 初回選択
      this.selectedIndex = index;
      cell.element.style.background = '#FFD54F';
      cell.element.style.transform = 'scale(1.1)';
      cell.element.style.boxShadow = '0 0 10px rgba(255, 213, 79, 0.8)';
    } else if (this.selectedIndex === index) {
      // 同一ピース選択→解除
      cell.element.style.background = '#f0f0f0';
      cell.element.style.transform = 'none';
      cell.element.style.boxShadow = 'none';
      this.selectedIndex = null;
    } else {
      // 交換処理
      this.swapPieces(this.selectedIndex, index);
      this.selectedIndex = null;
    }
  }

  swapPieces(idx1, idx2) {
    const cell1 = this.grid[idx1];
    const cell2 = this.grid[idx2];

    // 交換
    [cell1.currentValue, cell2.currentValue] = [cell2.currentValue, cell1.currentValue];
    [cell1.element.textContent, cell2.element.textContent] = [cell2.element.textContent, cell1.element.textContent];

    this.moves++;
    this.checkWin();
  }

  checkWin() {
    const isWin = this.grid.every((cell, index) => cell.correctValue === cell.currentValue);
    
    if (isWin) {
      this.state.addScore(10);
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
    text.textContent = 'やったー！＋10てん';
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
      progressElement.textContent = `${this.state.questionsAnswered + 1}/${this.state.questionsTotal} 枚`;
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
