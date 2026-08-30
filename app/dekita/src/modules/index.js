/* 
 * dekita - Preschool Edition Main Entry Point
 * ES Module version
 */

import { GameState } from './core/GameState.js';
import { AudioManager } from './core/AudioManager.js';
import { ScreenManager } from './core/ScreenManager.js';
import { CountGame } from './games/CountGame.js';
import { ColorGame } from './games/ColorGame.js';
import { AnimalGame } from './games/AnimalGame.js';
import { MazeGame } from './games/MazeGame.js';
import { MatchGame } from './games/MatchGame.js';
import { PuzzleGame } from './games/PuzzleGame.js';

export function init() {
  const gameState = new GameState();
  const audioManager = new AudioManager();
  const screenManager = new ScreenManager();
  
  audioManager.setGameState(gameState);
  
  const countGame = new CountGame(gameState, audioManager, screenManager);
  
  const colorGame = new ColorGame(gameState, audioManager, screenManager);
  
  const animalGame = new AnimalGame(gameState, audioManager, screenManager);
  
  const mazeGame = new MazeGame(gameState, audioManager, screenManager);
  
  const matchGame = new MatchGame(gameState, audioManager, screenManager);
  
  const puzzleGame = new PuzzleGame(gameState, audioManager, screenManager);
  
  countGame.init(document);
  colorGame.init(document);
  animalGame.init(document);
  mazeGame.init(document);
  matchGame.init(document);
  puzzleGame.init(document);
  
  return {
    gameState,
    audioManager,
    screenManager,
    countGame,
    colorGame,
    animalGame,
    mazeGame,
    matchGame,
    puzzleGame
  };
}
