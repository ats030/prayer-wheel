/* 
 * dekita - Preschool Edition Game Base
 * Base class for game modules
 */

export class GameBase {
  constructor(state, audioManager, screenManager) {
    this.state = state;
    this.audio = audioManager;
    this.screen = screenManager;
  }

  init() {
    if (this.state.score > this.state.highScore) {
      this.state.highScore = this.state.score;
    }
  }

  start() {
    this.state.resetScore();
    this.state.resetQuestionsAnswered();
    this.updateScore();
  }

  endGame() {
    this.screen.showResult();
    document.getElementById('final-score').textContent = this.state.score;
  }

  updateScore() {
    const scoreElement = document.getElementById('score');
    if (scoreElement) {
      scoreElement.textContent = this.state.score;
    }
  }

  updateProgress() {
    const progressElement = document.getElementById('progress-text');
    if (progressElement) {
      progressElement.textContent = `${this.state.questionsAnswered + 1}/${this.state.questionsTotal} 問`;
    }
  }

  playCorrectFeedback() {
    document.getElementById('feedback-area').style.display = 'block';
    document.getElementById('feedback-text').textContent = 'やったー！＋10てん';
    document.getElementById('feedback-text').style.color = '#4CAF50';
    this.audio.speak('やったー！');
    this.audio.playPopSound();
  }

  playWrongFeedback() {
    document.getElementById('feedback-area').style.display = 'block';
    document.getElementById('feedback-text').textContent = 'だいじょうぶ！もういっこ！';
    document.getElementById('feedback-text').style.color = '#E57373';
    this.audio.speak('ちょんぼ。もういっこ！');
  }

  hideFeedback() {
    document.getElementById('feedback-area').style.display = 'none';
  }
}
