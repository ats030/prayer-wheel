/* 
 * dekita - Preschool Edition Animal Sound Game Module
 */

export class AnimalGame {
  constructor() {
    this.state = window.gameState;
    this.audio = window.audioManager;
    this.screen = window.screenManager;
  }

  init(rootElement) {
    this.root = rootElement;
    this.registerEventListeners();
    this.state.gameMode = 'animal';
  }

  registerEventListeners() {
    this.root.getElementById('animal-start-btn').addEventListener('click', () => {
      this.audio.init();
      this.audio.playPopSound();
      this.start();
    });

    this.root.getElementById('reset-btn').addEventListener('click', () => {
      this.resetGame();
    });

    this.root.getElementById('next-btn').addEventListener('click', () => {
      this.nextQuestion();
    });
  }

  start() {
    this.state.resetScore();
    this.state.resetQuestionsAnswered();
    this.state.questionsTotal = 8;
    this.screen.showGame();
    this.updateScore();
    this.generateQuestion();
  }

  generateQuestion() {
    if (this.state.isGameOver()) {
      this.endGame();
      return;
    }

    const animals = [
      { name: 'いぬ', emoji: '🐶', sound: 'ワンワン！' },
      { name: 'ねこ', emoji: '🐱', sound: 'ニャー！' },
      { name: 'うし', emoji: '🐮', sound: 'モー！' },
      { name: 'ぶた', emoji: '🐷', sound: 'ブヒブヒ！' },
      { name: 'とり', emoji: '🐦', sound: 'ピーピー！' },
      { name: 'らいおん', emoji: '🦁', sound: 'ガオー！' },
      { name: 'ぞう', emoji: '🐘', sound: 'パオーン！' },
      { name: 'さる', emoji: '🐒', sound: 'ウキキ！' }
    ];

    const correct = animals[Math.floor(Math.random() * animals.length)];
    const incorrect = animals.filter(a => a !== correct);

    this.root.getElementById('picture-area').innerHTML = `<span class="picture-item" style="font-size: 80px;">${correct.emoji}</span>`;
    
    const answerButtons = this.root.getElementById('answer-buttons');
    answerButtons.innerHTML = '';

    const options = [correct, ...incorrect.sort(() => Math.random() - 0.5).slice(0, 3)];
    options.sort(() => Math.random() - 0.5);

    options.forEach(animal => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      btn.textContent = animal.name;
      btn.onclick = () => this.checkAnswer(animal, correct);
      answerButtons.appendChild(btn);
    });

    this.audio.speak('これは どんな こえかな？');
    setTimeout(() => {
      this.audio.speak(correct.sound);
    }, 500);
  }

  checkAnswer(selected, correct) {
    if (selected === correct) {
      this.state.addScore(10);
      this.playCorrectFeedback();
    } else {
      this.playWrongFeedback();
    }

    this.updateScore();
  }

  playCorrectFeedback() {
    this.root.getElementById('feedback-area').classList.remove('hidden');
    this.root.getElementById('feedback-text').textContent = 'やったー！＋10てん';
    this.root.getElementById('feedback-text').style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    this.root.getElementById('feedback-area').classList.remove('hidden');
    this.root.getElementById('feedback-text').textContent = 'だいじょうぶ！もういっこ！';
    this.root.getElementById('feedback-text').style.color = '#E57373';
    this.audio.speak('まちがい。もういっこ！');
  }

  nextQuestion() {
    this.state.incrementQuestionsAnswered();
    this.updateScore();
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

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = this.state.score;
    this.state.saveScore();
  }

  resetGame() {
    this.state.gameMode = 'animal';
    this.screen.showTitle();
  }
}
