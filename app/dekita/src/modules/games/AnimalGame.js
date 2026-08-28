/* 
 * dekita - Preschool Edition Animal Sound Game Module
 * For 3-year-olds: visual learning, no reading required
 */

export class AnimalGame {
  constructor(gameState, audio, screen) {
    this.state = gameState;
    this.audio = audio;
    this.screen = screen;
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
      { name: '犬', emoji: '🐶', sound: 'ワンワン！' },
      { name: '猫', emoji: '🐱', sound: 'ニャー！' },
      { name: '牛', emoji: '🐮', sound: 'モー！' },
      { name: '猪', emoji: '🐷', sound: 'ブヒブヒ！' },
      { name: '鳥', emoji: '🐦', sound: 'ピーピー！' },
      { name: 'ライオン', emoji: '🦁', sound: 'ガオー！' },
      { name: '象', emoji: '🐘', sound: 'パオーン！' },
      { name: '猿', emoji: '🐒', sound: 'ウキキ！' }
    ];

    const correct = animals[Math.floor(Math.random() * animals.length)];
    const incorrect = animals.filter(a => a !== correct);

    const pictureArea = this.root.getElementById('picture-area');
    pictureArea.innerHTML = '';
    
    const emojiSpan = document.createElement('span');
    emojiSpan.className = 'picture-item';
    emojiSpan.textContent = correct.emoji;
    emojiSpan.style.fontSize = '96px';
    pictureArea.appendChild(emojiSpan);
    
    const audioSpan = document.createElement('span');
    audioSpan.textContent = '🔊';
    audioSpan.style.fontSize = '48px';
    audioSpan.style.marginLeft = '10px';
    pictureArea.appendChild(audioSpan);

    const answerButtons = this.root.getElementById('answer-buttons');
    answerButtons.innerHTML = '';

    const options = [correct, ...incorrect.sort(() => Math.random() - 0.5).slice(0, 3)];
    options.sort(() => Math.random() - 0.5);

    options.forEach(animal => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      const nameSpan = document.createElement('span');
      nameSpan.textContent = animal.name;
      nameSpan.style.fontSize = '48px';
      btn.style.display = 'flex';
      btn.style.justifyContent = 'center';
      btn.style.alignItems = 'center';
      btn.style.flexDirection = 'column';
      btn.style.gap = '5px';
      btn.style.margin = '10px';
      btn.onclick = () => this.checkAnswer(animal, correct);
      btn.appendChild(nameSpan);
      answerButtons.appendChild(btn);
    });

    this.audio.speak('いいつけろ！（ピロピロピロ…）');
    setTimeout(() => {
      this.audio.speak(correct.sound);
    }, 1000);
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
      this.root.getElementById('feedback-area').classList.add('hidden');
      this.nextQuestion();
    }, 2000);
  }

  playCorrectFeedback() {
    const area = this.root.getElementById('feedback-area');
    const text = this.root.getElementById('feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'できた! すごい!';
    text.style.color = '#4CAF50';
    this.audio.speak('できた! すごい!');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    const area = this.root.getElementById('feedback-area');
    const text = this.root.getElementById('feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'いいね! またやろう!';
    text.style.color = '#E57373';
    this.audio.speak('いいね! またやろう!');
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
    document.getElementById('score').textContent = '⭐️' + this.state.score;
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = '⭐️' + this.state.score;
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }

  resetGame() {
    this.state.gameMode = 'animal';
    this.screen.showTitle();
  }
}
