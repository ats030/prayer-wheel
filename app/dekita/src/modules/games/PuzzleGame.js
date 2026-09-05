/**
 * dekita - Preschool Edition Puzzle Game Module
 * For 3-year-olds: Drag and drop puzzle with silhouette matching
 * 3x3 grid with different emojis as silhouettes (30% opacity)
 * Drag the correct emoji to match the silhouette
 */

import { GameBase } from '../core/GameBase.js';

export class PuzzleGame extends GameBase {
  constructor(gameState, audio, screen) {
    super(gameState, audio, screen);
    this.gridSize = 3;
    this.draggedPiece = null;
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
    super.start();
    this.score = 0;
    this.moves = 0;
    this.gameOver = false;
    this.draggedPiece = null;
    this.state.questionsAnswered = 0;
    this.state.questionsTotal = 5;
    this.screen.showPuzzleGame();
    this.setupDragSource();
    this.generatePuzzle();
  }

  getGridArea() {
    return this.root.getElementById('puzzle-grid');
  }

  setupDragSource() {
    const dragSource = this.root.getElementById('puzzle-drag-emoji');
    if (dragSource) {
      dragSource.addEventListener('dragstart', (e) => {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', this.correctEmoji);
      });
    }
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
    
    console.log('[Puzzle] Correct emoji:', this.correctEmoji, 'at index:', this.correctIndex);
    console.log('[Puzzle] All silhouettes:', this.silhouettes);
    
    this.setupDragSource();
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
      slot.dataset.emoji = this.silhouettes[i];
      slot.textContent = this.silhouettes[i];
      slot.style.opacity = '0.3';
      slot.setAttribute('draggable', 'false');
      slot.addEventListener('dragover', (e) => e.preventDefault());
      slot.addEventListener('drop', (e) => this.handleDrop(e));
      slot.addEventListener('dragenter', (e) => e.preventDefault());
      slot.addEventListener('dragleave', (e) => e.preventDefault());
      gridArea.appendChild(slot);
    }

    const correctSlot = gridArea.children[this.correctIndex];
    if (correctSlot) {
      correctSlot.setAttribute('draggable', 'true');
      correctSlot.addEventListener('dragstart', (e) => this.handleDragStart(e));
      console.log('[Puzzle] Set correct slot draggable:', correctSlot.dataset.emoji, 'at index:', this.correctIndex);
    } else {
      console.warn('[Puzzle] Correct slot not found at index:', this.correctIndex);
    }

    this.audio.init();
    this.audio.setInterAudioDelay(300);
    this.audio.playSequence(['これ なん の もの？']);
    this.updateProgress();
  }

  handleDragStart(e) {
    this.draggedPiece = this.correctEmoji;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', this.correctEmoji);
  }

  handleDrop(e) {
    e.preventDefault();
    this.moves++;
    
    let slot = e.target.closest('[data-emoji]');
    if (!slot) {
      slot = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-emoji]');
    }
    if (!slot) {
      console.log('[Puzzle] No slot found for drop');
      return;
    }
    
    const slotEmoji = slot.dataset.emoji;
    console.log('[Puzzle] Drop on emoji:', slotEmoji, 'Expected:', this.correctEmoji);
    
    if (slotEmoji === this.correctEmoji) {
      this.checkWin();
    } else {
      this.audio.playErrorSound();
      const area = this.root.getElementById('puzzle-feedback-area');
      const text = this.root.getElementById('puzzle-feedback-text');
      area.style.display = 'block';
      text.textContent = 'ちがいます';
      text.style.color = '#FF5722';
      setTimeout(() => {
        area.style.display = 'none';
      }, 1000);
    }
  }

  checkWin() {
    const gridArea = this.getGridArea();
    if (gridArea && gridArea.children[this.correctIndex]) {
      gridArea.children[this.correctIndex].classList.remove('puzzle-piece');
      gridArea.children[this.correctIndex].classList.add('puzzle-silhouette', 'revealed');
    }

    this.state.addScore(20);
    this.playCorrectFeedback();
    
    if (this.state.isGameOver()) {
      setTimeout(() => this.endGame(), 2000);
    } else {
      setTimeout(() => this.nextQuestion(), 2000);
    }
  }

  playCorrectFeedback() {
    super.playCorrectFeedback();
    if (this.root) {
      const text = this.root.getElementById('puzzle-feedback-text');
      if (text) {
        text.textContent = 'やったー！＋20てん';
      }
    }
    this.audio.init();
    this.audio.setInterAudioDelay(300);
    this.audio.playSequence(['やったー！']);
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
    super.updateProgress();
    if (this.root) {
      this.root.getElementById('puzzle-progress-text').textContent = 
        `${this.state.questionsAnswered + 1}/${this.state.questionsTotal} 問`;
    }
  }

  endGame() {
    super.endGame();
    this.gameOver = true;
    if (this.root) {
      const area = this.root.getElementById('puzzle-feedback-area');
      const text = this.root.getElementById('puzzle-feedback-text');
      if (area && text) {
        area.style.display = 'block';
        text.textContent = `せいかい！ スコア：${this.state.score}`;
      }
    }
    this.audio.init();
    this.audio.playSequence(['おわった！']);
    this.audio.playPopSound();
  }

  cleanup() {
    this.draggedPiece = null;
    this.gameOver = false;
  }
}
