/**
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
    this.updateScore();
    this.generateQuestion();
  }

  registerEventListeners() {
    const startBtn = this.root.getElementById('start-btn');
    if (startBtn) {
      startBtn.addEventListener('click', () => {
        this.audio.init();
        this.audio.playPopSound();
        this.start();
      });
    }

    const resetBtn = this.root.getElementById('reset-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        this.resetGame();
      });
    }

    const replayBtn = this.root.getElementById('replay-btn');
    if (replayBtn) {
      replayBtn.addEventListener('click', () => {
        this.audio.init();
        this.audio.playPopSound();
        this.start();
      });
    }
  }

  start() {
    this.state.resetScore();
    this.state.resetQuestionsAnswered();
    this.state.gameMode = 'number';
    this.screen.showGame();
    this.generateQuestion();
  }

  loadScore() {
    const saved = localStorage.getItem('gakushuGameHighScore');
    if (saved) {
      console.log(`前回の最高点: ${saved}てん`);
    }
  }

  renderNumberGrid() {
    const grid = this.root.getElementById('number-grid');
    if (grid) {
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
  }

  startGameWithNumber(number) {
    this.state.currentNumber = number;
    this.screen.showGame();
    this.generateQuestionForNumber(number);
  }

  generateQuestionForNumber(number) {
    if (this.state.isGameOver()) {
      this.endGame();
      return;
    }

    const emoji = this.getRandomPicture();
    this.state.currentAnswer = number;

    this.state.currentQuestion = { emoji, emojiCount: number };
    this.renderQuestion(emoji, number);
  }

  getRandomPicture() {
    const pictures = ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒', '🍑'];
    return pictures[Math.floor(Math.random() * pictures.length)];
  }

  renderQuestion(emoji, emojiCount) {
    const questionArea = this.root.getElementById('question-area');
    const pictureArea = this.root.getElementById('picture-area');
    const answerButtons = this.root.getElementById('answer-buttons');
    const questionText = this.root.getElementById('question-text');

    answerButtons.innerHTML = '';
    pictureArea.innerHTML = '';

    // エモジと問題文を表示
    questionText.textContent = `${emoji}はいくつあるかな？`;
    for (let i = 0; i < emojiCount; i++) {
      const span = document.createElement('span');
      span.className = 'picture-item';
      span.textContent = emoji;
      span.style.fontSize = '64px';
      span.style.margin = '10px';
      pictureArea.appendChild(span);
    }

    const answers = this.generateAnswers(emojiCount);
    answers.forEach(a => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      btn.textContent = a;
      btn.style.fontSize = 'clamp(24px, 6dvw, 48px)';
      btn.style.width = 'auto';
      btn.onclick = () => this.checkAnswer(a);
      answerButtons.appendChild(btn);
    });

    this.audio.speak('いくつあるかな？');
  }

  generateAnswers(correct) {
    const answers = [correct];
    while (answers.length < 4) {
      const wrong = Math.floor(Math.random() * 10) + 1;
      if (!answers.includes(wrong)) {
        answers.push(wrong);
      }
    }
    answers.sort(() => Math.random() - 0.5);
    return answers.slice(0, 4);
  }

  checkAnswer(selected) {
    const correct = this.state.currentAnswer;
    
    if (this.state.isAnswering) return;
    this.state.isAnswering = true;
    
    if (correct === selected) {
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
    const area = this.root.getElementById('feedback-area');
    const text = this.root.getElementById('feedback-text');
    area.style.display = 'block';
    text.textContent = 'やったー！＋10てん';
    text.style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    const area = this.root.getElementById('feedback-area');
    const text = this.root.getElementById('feedback-text');
    area.style.display = 'block';
    text.textContent = 'だいじょうぶ！もういっこ！';
    text.style.color = '#E57373';
    this.audio.speak('だいじょうぶ！もういっこ！');
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
  
  generateQuestion() {
    if (this.state.isGameOver()) {
      this.endGame();
      return;
    }

    const emoji = this.getRandomPicture();
    const emojiCount = Math.floor(Math.random() * 10) + 1;
    this.state.currentAnswer = emojiCount;
    this.state.currentQuestion = { emoji, emojiCount };
    this.renderQuestion(emoji, emojiCount);
  }

  updateScore() {
    this.root.getElementById('score').textContent = '⭐️' + this.state.score;
  }

  updateProgress() {
    this.root.getElementById('progress-text').textContent = 
      `${this.state.questionsAnswered + 1}/${this.state.questionsTotal}`;
  }

  endGame() {
    this.screen.showResult();
    this.root.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }

  resetGame() {
    this.screen.showTitle();
  }

  cleanup() {
    this.state.isAnswering = false;
  }
}
