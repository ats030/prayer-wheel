/* 
 * dekita - Preschool Edition Game Base
 * Base class for game modules
 */

export class GameBase {
  constructor(state, audioManager, screenManager) {
    this.state = state;
    this.audio = audioManager;
    this.screen = screenManager;
    this.root = null;
  }

  init(rootElement) {
    this.root = rootElement;
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
    const finalScoreEl = this.root ? this.root.getElementById('final-score') : document.getElementById('final-score');
    if (finalScoreEl) {
      finalScoreEl.textContent = '⭐️' + this.state.score;
    }
  }

  updateScore() {
    const scoreElement = this.root ? this.root.getElementById('score') : document.getElementById('score');
    if (scoreElement) {
      scoreElement.textContent = '⭐️' + this.state.score;
    }
  }

  updateProgress() {
    const progressElement = this.root ? this.root.getElementById('progress-text') : document.getElementById('progress-text');
    if (progressElement) {
      progressElement.textContent = `${this.state.questionsAnswered + 1}/${this.state.questionsTotal} 問`;
    }
  }

  playCorrectFeedback() {
    const feedbackEl = this.root ? this.root.getElementById('feedback-area') : document.getElementById('feedback-area');
    const textEl = this.root ? this.root.getElementById('feedback-text') : document.getElementById('feedback-text');
    if (feedbackEl && textEl) {
      feedbackEl.style.display = 'block';
      textEl.textContent = 'やったー！＋10てん';
      textEl.style.color = '#4CAF50';
      this.audio.speak('やったー！');
      this.audio.playPopSound();
    }
  }

  playWrongFeedback() {
    const feedbackEl = this.root ? this.root.getElementById('feedback-area') : document.getElementById('feedback-area');
    const textEl = this.root ? this.root.getElementById('feedback-text') : document.getElementById('feedback-text');
    if (feedbackEl && textEl) {
      feedbackEl.style.display = 'block';
      textEl.textContent = 'だいじょうぶ！もういっこ！';
      textEl.style.color = '#E57373';
      this.audio.speak('だいじょうぶ！もういっこ！');
    }
  }

  hideFeedback() {
    const feedbackEl = this.root ? this.root.getElementById('feedback-area') : document.getElementById('feedback-area');
    if (feedbackEl) {
      feedbackEl.style.display = 'none';
    }
  }
}
