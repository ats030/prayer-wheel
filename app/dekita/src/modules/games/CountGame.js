/* 
 * dekita - Preschool Edition Count Game Module
 * For 3-year-olds: visual learning, no reading required
 */

export class CountGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'number';
  }

  registerEventListeners() {
    this.root.getElementById('start-btn').addEventListener('click', () => {
      this.audio.init();
      this.audio.playPopSound();
      this.start();
    });

    this.root.getElementById('reset-btn').addEventListener('click', () => {
      this.resetGame();
    });
  }

  start() {
    this.state.resetScore();
    this.state.resetQuestionsAnswered();
    this.state.gameMode = 'number';
    this.renderNumberGrid();
  }

  loadScore() {
    const saved = localStorage.getItem('gakushuGameHighScore');
    if (saved) {
      console.log(`前回の最高点: ${saved}てん`);
    }
  }

  renderNumberGrid() {
    const grid = this.root.getElementById('number-grid');
    grid.innerHTML = '';
    for (let i = 1; i <= this.state.maxNumber; i++) {
      const btn = document.createElement('button');
      btn.className = 'number-btn';
      btn.textContent = i;
      btn.addEventListener('click', () => {
        this.audio.playPopSound();
        this.state.currentNumber = i;
        this.startGameWithNumber(i);
      });
      grid.appendChild(btn);
    }
  }

  startGameWithNumber(number) {
    this.state.currentNumber = number;
    this.screen.showGame();
    this.generateQuestion();
  }

  generateQuestion() {
    if (this.state.isGameOver()) {
      this.endGame();
      return;
    }

    const emoji = this.getRandomPicture();
    const emojiCount = Math.floor(Math.random() * 5) + 1;
    this.state.currentAnswer = emojiCount;

    this.state.currentQuestion = { emoji, emojiCount };
    this.renderQuestion(emoji, emojiCount);
  }

  getRandomPicture() {
    const pictures = ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒', '🍑'];
    return pictures[Math.floor(Math.random() * pictures.length)];
  }

  renderQuestion(emoji, emojiCount) {
    const questionArea = this.root.getElementById('question-area');
    const pictureArea = this.root.getElementById('picture-area');
    const answerButtons = this.root.getElementById('answer-buttons');

    pictureArea.innerHTML = '';
    for (let i = 0; i < emojiCount; i++) {
      const span = document.createElement('span');
      span.className = 'picture-item';
      span.textContent = emoji;
      span.style.fontSize = '48px';
      span.style.margin = '5px';
      pictureArea.appendChild(span);
    }

    const answers = this.generateAnswers(emojiCount);
    answers.forEach(a => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      btn.textContent = a;
      btn.style.fontSize = '64px';
      btn.style.width = '80px';
      btn.style.height = '80px';
      btn.onclick = () => this.checkAnswer(a);
      answerButtons.appendChild(btn);
    });

    this.audio.speak('いくつあるかな？');
  }

  generateAnswers(correct) {
    const answers = [correct];
    while (answers.length < 4) {
      const wrong = Math.floor(Math.random() * 6) + 1;
      if (!answers.includes(wrong)) {
        answers.push(wrong);
      }
    }
    answers.sort(() => Math.random() - 0.5);
    return answers;
  }

  checkAnswer(selected) {
    const correct = this.state.currentAnswer;
    
    if (correct === selected) {
      this.state.addScore(10);
      this.playCorrectFeedback();
    } else {
      this.playWrongFeedback();
    }
    
    this.updateScore();
    
    setTimeout(() => {
      this.root.getElementById('feedback-area').classList.add('hidden');
      this.nextQuestion();
    }, 2000);
  }

  playCorrectFeedback() {
    document.getElementById('feedback-area').classList.remove('hidden');
    const text = document.getElementById('feedback-text');
    text.textContent = 'できた! おめでとう!';
    text.style.color = '#4CAF50';
    this.audio.speak('できた! おめでとう!');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    document.getElementById('feedback-area').classList.remove('hidden');
    const text = document.getElementById('feedback-text');
    text.textContent = 'いいね! こえでかく';
    text.style.color = '#E57373';
    this.audio.speak('いーて! こえでかく');
  }

  nextQuestion() {
    this.state.incrementQuestionsAnswered();
    this.updateScore();
    this.updateProgress();
    this.root.getElementById('feedback-area').classList.add('hidden');
    
    if (this.state.isGameOver()) {
      this.endGame();
    } else {
      this.generateQuestion();
    }
  }

  updateScore() {
    document.getElementById('score').textContent = '⭐️' + this.state.score;
  }

  updateProgress() {
    document.getElementById('progress-text').textContent = 
      `${this.state.questionsAnswered + 1}/${this.state.questionsTotal}`;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }

  resetGame() {
    this.state.gameMode = 'number';
    this.screen.showTitle();
  }
}
