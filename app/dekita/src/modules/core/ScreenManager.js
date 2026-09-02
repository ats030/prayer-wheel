/**
 * dekita - Preschool Edition Screen Manager
 */

export class ScreenManager {
  constructor() {
    this.currentScreen = null;
    this.gameModules = {};
  }

  setGameModules(gameModules) {
    this.gameModules = gameModules;
  }

  show(screenId) {
    const screens = document.querySelectorAll('.screen');
    screens.forEach(s => s.classList.add('hidden'));
    
    const newScreen = document.getElementById(screenId);
    if (newScreen) {
      newScreen.classList.remove('hidden');
      this.currentScreen = screenId;
    }
    
    // 各ゲームモジュールの cleanup を呼び出す
    Object.values(this.gameModules).forEach(game => {
      if (game && typeof game.cleanup === 'function') {
        game.cleanup();
      }
    });
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
  }

  showGame() {
    this.show('game-screen');
  }

  showMazeGame() {
    this.show('maze-play-screen');
  }

  showMatchGame() {
    this.show('match-game-screen');
  }

  showPuzzleGame() {
    this.show('puzzle-game-screen');
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
