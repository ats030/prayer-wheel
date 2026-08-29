/**
 * dekita - Preschool Edition Color Game Module
 * For 3-year-olds: visual learning, no reading required
 */

export class ColorGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
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
    this.state.resetScore();
    this.state.resetQuestionsAnswered();
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
  }

  checkAnswerByName(selected, correct) {
    if (this.state.isAnswering) return;
    this.state.isAnswering = true;
    
    if (selected.name === correct.name) {
      this.state.addScore(10);
      this.playCorrectFeedback();
    } else {
      this.playWrongFeedback();
    }

    this.updateScore();

    setTimeout(() => {
      this.state.isAnswering = false;
      this.nextQuestion();
    }, 2000);
  }

  playCorrectFeedback() {
    const area = this.root.getElementById('color-feedback-area');
    const text = this.root.getElementById('color-feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'やったー！＋10てん';
    text.style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    const area = this.root.getElementById('color-feedback-area');
    const text = this.root.getElementById('color-feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'だいじょうぶ！もういっこ！';
    text.style.color = '#E57373';
    this.audio.speak('だいじょうぶ！もういっこ！');
  }

  nextQuestion() {
    this.state.incrementQuestionsAnswered();
    this.updateScore();
    this.root.getElementById('color-feedback-area').classList.add('hidden');

    if (this.state.isGameOver()) {
      this.endGame();
    } else {
      this.generateQuestion();
    }
  }

  updateScore() {
    document.getElementById('color-score').textContent = '⭐️' + this.state.score;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }

  resetGame() {
    this.screen.showTitle();
  }
}
