/* 
 * dekita - Preschool Edition Count Game Module
 */

export class CountGame {
  constructor() {
    this.state = window.gameState;
    this.audio = window.audioManager;
    this.screen = window.screenManager;
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
  }

  start() {
    this.state.resetScore();
    this.state.resetQuestionsAnswered();
    this.screen.showNumberSelect();
    this.loadScore();
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
    const answer = emojiCount;
    const questionText = `${emoji}はいくつあるかな？`;

    this.state.currentQuestion = { answer, questionText };
    this.renderQuestion(questionText, emoji, emojiCount);
    
    this.audio.speak(questionText);
  }

  getRandomPicture() {
    const pictures = ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒', '🍑'];
    return pictures[Math.floor(Math.random() * pictures.length)];
  }

  renderQuestion(questionText, emoji, emojiCount) {
    const questionArea = this.root.getElementById('question-area');
    const pictureArea = this.root.getElementById('picture-area');
    const questionTextEl = this.root.getElementById('question-text');
    const answerButtons = this.root.getElementById('answer-buttons');

    pictureArea.innerHTML = '';
    for (let i = 0; i < emojiCount; i++) {
      const span = document.createElement('span');
      span.className = 'picture-item';
      span.textContent = emoji;
      pictureArea.appendChild(span);
    }

    questionTextEl.textContent = questionText;
    
    const answers = [answer];
    while (answers.length < 4) {
      const wrong = Math.floor(Math.random() * 6);
      if (!answers.includes(wrong)) {
        answers.push(wrong);
      }
    }
    answers.sort(() => Math.random() - 0.5);
    
    answers.forEach(a => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      btn.textContent = a;
      btn.onclick = () => this.checkAnswer(a);
      answerButtons.appendChild(btn);
    });
  }

  checkAnswer(selected) {
    const correct = this.state.currentQuestion.answer;
    
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
    document.getElementById('feedback-text').textContent = 'やったー！＋10てん';
    document.getElementById('feedback-text').style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    document.getElementById('feedback-area').classList.remove('hidden');
    document.getElementById('feedback-text').textContent = 'だいじょうぶ！もういっこ！';
    document.getElementById('feedback-text').style.color = '#E57373';
    this.audio.speak('ちょんぼ。もういっこ！');
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
    document.getElementById('score').textContent = this.state.score;
  }

  updateProgress() {
    document.getElementById('progress-text').textContent = 
      `${this.state.questionsAnswered + 1}/${this.state.questionsTotal} 問`;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = this.state.score;
    this.state.saveScore();
  }

  resetGame() {
    this.state.gameMode = 'number';
    this.screen.showTitle();
  }
}
