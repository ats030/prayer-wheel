export class GameState {
  constructor() {
    this.score = 0;
    this.currentNumber = 1;
    this.currentQuestion = null;
    this.gameMode = 'number';
    this.questionsAnswered = 0;
    this.questionsTotal = 10;
    this.maxNumber = 10;
    this.isAnswering = false;
    
    this.mazeActive = false;
    this.mazePlayer = { x: 0, y: 0 };
    this.mazeGoal = { x: 0, y: 0 };
    this.mazePath = [];
    this.mazeCurrentTheme = null;
    this._testMode = false;
    
    this.highScore = parseInt(localStorage.getItem('gakushuGameHighScore') || '0');
  }

  incrementQuestionsAnswered() {
    this.questionsAnswered++;
  }

    resetQuestionsAnswered() {
      this.questionsAnswered = 0;
    }

  addScore(points) {
    this.score += points;
    if (this.score > this.highScore) {
      this.highScore = this.score;
      localStorage.setItem('gakushuGameHighScore', this.score);
    }
  }

  resetScore() {
    this.score = 0;
  }

  isGameOver() {
    return this.questionsAnswered >= this.questionsTotal;
  }

  saveScore() {
    localStorage.setItem('gakushuGameHighScore', this.score);
  }

  cleanup() {
    // クリーンアップ用メソッド
  }
}
