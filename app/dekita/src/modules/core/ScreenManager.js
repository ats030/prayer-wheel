/* 
 * dekita - Preschool Edition Screen Manager
 */

export class ScreenManager {
  constructor() {
    this.currentScreen = null;
  }

  show(screenId) {
    const screens = document.querySelectorAll('.screen');
    screens.forEach(s => s.classList.add('hidden'));
    
    const newScreen = document.getElementById(screenId);
    if (newScreen) {
      newScreen.classList.remove('hidden');
      this.currentScreen = screenId;
    }
  }

  hide(screenId) {
    const screen = document.getElementById(screenId);
    if (screen) {
      screen.classList.add('hidden');
    }
  }

  showTitle() {
    this.show('title-screen');
  }

  showNumberSelect() {
    this.show('title-screen');
  }

  showColorGame() {
    this.show('color-game-screen');
  }

  showMazeThemeSelect() {
    this.show('maze-theme-select-screen');
  }

  showGame() {
    this.show('game-screen');
  }

  showMazeGame() {
    this.show('maze-play-screen');
  }

  showResult() {
    this.show('result-screen');
  }

  showMazeResult() {
    this.show('result-screen');
  }

  isHidden(screenId) {
    const screen = document.getElementById(screenId);
    return screen && screen.classList.contains('hidden');
  }
}
