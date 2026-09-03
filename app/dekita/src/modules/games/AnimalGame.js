import { GameBase } from '../core/GameBase.js';

export class AnimalGame extends GameBase {
  constructor(gameState, audio, screen) {
    super(gameState, audio, screen);
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

    this.root.getElementById('animal-reset-btn').addEventListener('click', () => {
      this.resetGame();
    });

    this.root.getElementById('animal-next-btn').addEventListener('click', () => {
      this.nextQuestion();
    });
  }

  start() {
    super.start();
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
    if (this.state.isAnswering) return;
    this.state.isAnswering = true;
    
    if (selected === correct) {
      this.state.addScore(10);
      super.playCorrectFeedback();
    } else {
      super.playWrongFeedback();
    }

    super.updateScore();

    setTimeout(() => {
      this.state.isAnswering = false;
      this.nextQuestion();
    }, 2000);
  }

  playCorrectFeedback() {
    super.playCorrectFeedback();
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    super.playWrongFeedback();
    this.audio.speak('だいじょうぶ！もういっこ！');
  }

  nextQuestion() {
    this.state.incrementQuestionsAnswered();
    super.updateScore();
    if (this.root) {
      this.root.getElementById('feedback-area').classList.add('hidden');
    }

    if (this.state.isGameOver()) {
      this.endGame();
    } else {
      this.generateQuestion();
    }
  }

  updateScore() {
    if (this.root) {
      this.root.getElementById('score').textContent = '⭐️' + this.state.score;
    }
  }

  endGame() {
    super.endGame();
    if (this.root) {
      this.root.getElementById('final-score').textContent = '⭐️' + this.state.score;
    }
    this.state.saveScore();
    this.audio.speak('おわった! おめでとう!');
  }

  resetGame() {
    this.screen.showTitle();
  }

  replaySound(soundText) {
    this.audio.playPopSound();
    this.audio.speak(soundText);
  }

  cleanup() {
    this.state.isAnswering = false;
  }
}
