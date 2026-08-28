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
      { name: 'あか', hex: '#ff3333', emoji: '❤️' },
      { name: 'あお', hex: '#3333ff', emoji: '💙' },
      { name: 'きいろ', hex: '#ffff33', emoji: '💛' },
      { name: 'みどり', hex: '#33ff33', emoji: '💚' }
    ];

    const correct = colors[Math.floor(Math.random() * colors.length)];
    const otherColors = colors.filter(c => c !== correct);
    
    const answerButtons = this.root.getElementById('color-answer-buttons');
    answerButtons.innerHTML = '';

    const options = [correct, ...otherColors.sort(() => Math.random() - 0.5).slice(0, 3)];
    options.sort(() => Math.random() - 0.5);

    options.forEach(color => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn color-answer-btn';
      const contentSpan = document.createElement('span');
      contentSpan.textContent = color.emoji;
      btn.appendChild(contentSpan);
      btn.onclick = () => this.checkAnswer(color, correct);
      answerButtons.appendChild(btn);
    });

    const swatch = this.root.getElementById('color-swatch');
    swatch.style.backgroundColor = correct.hex;
    swatch.style.border = `4px solid #fff`;
    swatch.style.width = '120px';
    swatch.style.height = '120px';
    swatch.style.borderRadius = '50%';
    swatch.style.margin = '20px auto';

    const questionText = this.root.getElementById('color-question-text');
    questionText.textContent = 'これ なん の いろかな？';

    this.audio.speak('これ なん の いろかな？');
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
    this.state.gameMode = 'color';
    this.screen.showTitle();
  }
}
