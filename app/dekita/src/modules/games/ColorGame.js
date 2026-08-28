/* 
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
      { name: '赤', hex: '#ff3333' },
      { name: '青', hex: '#3333ff' },
      { name: '黄', hex: '#ffff33' },
      { name: '緑', hex: '#33ff33' }
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
      const colorBtn = document.createElement('div');
      colorBtn.style.width = '60px';
      colorBtn.style.height = '60px';
      colorBtn.style.borderRadius = '50%';
      colorBtn.style.backgroundColor = color.hex;
      colorBtn.style.border = '3px solid #fff';
      colorBtn.style.margin = '5px';
      colorBtn.onclick = () => this.checkAnswer(color, correct);
      answerButtons.appendChild(colorBtn);
    });

    const swatch = this.root.getElementById('color-swatch');
    swatch.style.backgroundColor = correct.hex;
    swatch.style.border = `4px solid #fff`;
    swatch.style.width = '100px';
    swatch.style.height = '100px';
    swatch.style.borderRadius = '50%';
    swatch.style.margin = '20px auto';

    this.audio.speak('なにいろかな？');
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
    text.textContent = 'できた! すごい!';
    text.style.color = '#4CAF50';
    this.audio.speak('できた! すごい!');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    const area = this.root.getElementById('color-feedback-area');
    const text = this.root.getElementById('color-feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'いいね! またやろう!';
    text.style.color = '#E57373';
    this.audio.speak('いいね! またやろう!');
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
