/* 
 * dekita - Preschool Edition Game Modules
 */

export class ColorGame {
  constructor() {
    this.state = window.gameState;
    this.audio = window.audioManager;
    this.screen = window.screenManager;
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'color';
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
      { name: 'あか', hex: '#ff3333' },
      { name: 'あお', hex: '#3333ff' },
      { name: 'きいろ', hex: '#ffff33' },
      { name: 'みどり', hex: '#33ff33' }
    ];

    const correct = colors[Math.floor(Math.random() * colors.length)];
    const otherColors = colors.filter(c => c !== correct);
    
    const answerButtons = this.root.getElementById('color-answer-buttons');
    answerButtons.innerHTML = '';

    const options = [correct, ...otherColors.sort(() => Math.random() - 0.5).slice(0, 3)];
    options.sort(() => Math.random() - 0.5);

    options.forEach(color => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      btn.textContent = color.name;
      btn.onclick = () => this.checkAnswer(color, correct);
      answerButtons.appendChild(btn);
    });

    const swatch = this.root.getElementById('color-swatch');
    swatch.style.backgroundColor = correct.hex;
    swatch.style.border = `3px solid ${correct.hex}`;

    const text = `これ なん の いろかな？`;
    this.root.getElementById('color-question-text').textContent = text;
    this.audio.speak(text);
  }

  checkAnswer(selected, correct) {
    if (selected === correct) {
      this.state.addScore(10);
      this.playCorrectFeedback();
    } else {
      this.playWrongFeedback();
    }

    this.updateScore();

    setTimeout(() => {
      this.root.getElementById('color-feedback-area').classList.add('hidden');
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
    this.audio.speak('ちょんぼ。もういっこ！');
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
    document.getElementById('color-score').textContent = this.state.score;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = this.state.score;
    this.state.saveScore();
  }

  resetGame() {
    this.state.gameMode = 'color';
    this.screen.showTitle();
  }
}
