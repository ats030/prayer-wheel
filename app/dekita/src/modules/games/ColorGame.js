import { GameBase } from '../core/GameBase.js';

export class ColorGame extends GameBase {
  constructor(gameState, audio, screen) {
    super(gameState, audio, screen);
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'color';
    this.state.questionsTotal = 10;
  }

  registerEventListeners() {
    this.root.getElementById('color-start-btn').addEventListener('click', () => {
      this.audio.init();
      this.audio.playPopSound();
      this.start();
    });

    this.root.getElementById('color-reset-btn').addEventListener('click', () => {
      this.resetGame();
    });

    this.root.getElementById('color-next-btn').addEventListener('click', () => {
      this.nextQuestion();
    });
  }

  start() {
    super.start();
    this.screen.showColorGame();
    this.state.questionsTotal = 10;
    this.updateScore();
    this.generateQuestion();
  }

  generateQuestion() {
    if (this.state.isGameOver()) {
      this.endGame();
      return;
    }

    const colors = [
      { name: 'あか', hex: '#ff3333', emoji: ['🍎', '🍒', '🍓', '🍅'] },
      { name: 'あお', hex: '#3333ff', emoji: ['🌎', '🐋', '🐬', '💧'] },
      { name: 'きいろ', hex: '#ffff33', emoji: ['🌽', '🌻', '🍋', '🐤'] },
      { name: 'みどり', hex: '#33ff33', emoji: ['🥦', '🌲', '🍀', '🐢'] },
      { name: 'だいだい', hex: '#FF8C00', emoji: ['🍊', '🥕', '🎃', '🦊'] },
      { name: 'むらさき', hex: '#9370DB', emoji: ['🍇', '🍆', '🪻', '👾'] }
    ];

    const correct = colors[Math.floor(Math.random() * colors.length)];
    const correctEmoji = correct.emoji[Math.floor(Math.random() * correct.emoji.length)];
    const otherColors = colors.filter(c => c !== correct);
    
    const emojiDisplay = this.root.getElementById('color-emoji-display');
    emojiDisplay.textContent = correctEmoji;
    
    const answerButtons = this.root.getElementById('color-answer-buttons');
    answerButtons.innerHTML = '';
    
    const colorOptions = [
      { hex: '#ff3333', name: 'あか' },
      { hex: '#3333ff', name: 'あお' },
      { hex: '#ffff33', name: 'きいろ' },
      { hex: '#33ff33', name: 'みどり' },
      { hex: '#FF8C00', name: 'だいだい' },
      { hex: '#9370DB', name: 'むらさき' }
    ];
    
    colorOptions.forEach(color => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn color-answer-btn';
      btn.style.backgroundColor = color.hex;
      btn.style.color = '#ffffff';
      btn.textContent = color.name;
      btn.onclick = () => this.checkAnswerByName(color, correct);
      answerButtons.appendChild(btn);
    });

    this.updateScore();
    this.root.getElementById('color-feedback-area').classList.add('hidden');
    this.audio.speak('これ なん の いろかな？');
  }

  checkAnswerByName(selected, correct) {
    if (this.state.isAnswering) return;
    this.state.isAnswering = true;
    
    if (selected.name === correct.name) {
      this.state.addScore(10);
      super.playCorrectFeedback();
    } else {
      super.playWrongFeedback();
    }

    this.updateScore();

    setTimeout(() => {
      this.state.isAnswering = false;
      this.nextQuestion();
    }, 2000);
  }

  playCorrectFeedback() {
    super.playCorrectFeedback();
  }

  playWrongFeedback() {
    super.playWrongFeedback();
  }

  nextQuestion() {
    this.state.incrementQuestionsAnswered();
    super.updateScore();
    this.root.getElementById('color-feedback-area').classList.add('hidden');

    if (this.state.isGameOver()) {
      this.endGame();
    } else {
      this.generateQuestion();
    }
  }

  updateScore() {
    if (this.root) {
      this.root.getElementById('color-score').textContent = '⭐️' + this.state.score;
    }
  }

  endGame() {
    super.endGame();
  }

  resetGame() {
    this.screen.showTitle();
  }

  cleanup() {
    this.state.isAnswering = false;
  }
}
