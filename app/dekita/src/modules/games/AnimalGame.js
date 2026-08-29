/**
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

    const pictureArea = this.root.getElementById('picture-area');
    pictureArea.innerHTML = '';
    
    const soundIcon = document.createElement('div');
    soundIcon.className = 'sound-icon';
    soundIcon.textContent = '🔊';
    soundIcon.style.fontSize = '80px';
    soundIcon.style.cursor = 'pointer';
    soundIcon.onclick = () => this.replaySound(correct.sound);
    pictureArea.appendChild(soundIcon);

    const questionText = this.root.getElementById('question-text');
    questionText.textContent = 'だれの こえかな？';

    const answerButtons = this.root.getElementById('answer-buttons');
    answerButtons.innerHTML = '';

    // 回答ボタンを表示：emoji + 日本語名
    const options = [correct, ...incorrect.sort(() => Math.random() - 0.5).slice(0, 3)];
    options.sort(() => Math.random() - 0.5);

    options.forEach(animal => {
      const btn = document.createElement('button');
      btn.className = 'answer-btn';
      const contentSpan = document.createElement('span');
      contentSpan.textContent = `${animal.emoji} ${animal.name}`;
      contentSpan.style.fontSize = 'clamp(14px, 5dvw, 28px)';
      btn.style.fontSize = 'clamp(14px, 5dvw, 28px)';
      btn.style.padding = '12px 16px';
      btn.style.width = 'auto';
      btn.onclick = () => this.checkAnswer(animal, correct);
      btn.appendChild(contentSpan);
      answerButtons.appendChild(btn);
    });

    this.audio.speak('だれの こえかな？');
    setTimeout(() => {
      this.audio.speak(correct.sound);
    }, 1500);
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
    text.textContent = 'やったー！';
    text.style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    const area = this.root.getElementById('feedback-area');
    const text = this.root.getElementById('feedback-text');
    area.classList.remove('hidden');
    text.textContent = 'だいじょうぶ！もういっこ！';
    text.style.color = '#E57373';
    this.audio.speak('だいじょうぶ！もういっこ！');
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

  replaySound(soundText) {
    this.audio.playPopSound();
    this.audio.speak(soundText);
  }
}
