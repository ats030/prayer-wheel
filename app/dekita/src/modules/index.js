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
  
  const mazeGame = new MazeGame(gameState, audioManager, screenManager);
  
  const matchGame = new MatchGame(gameState, audioManager, screenManager);
  
  const puzzleGame = new PuzzleGame(gameState, audioManager, screenManager);
  
  const animalGame = new AnimalGame(gameState, audioManager, screenManager);
  
  // ゲームモジュールを ScreenManager に設定
  screenManager.setGameModules({
    countGame,
    colorGame,
    mazeGame,
    matchGame,
    puzzleGame,
    animalGame
  });
  
  // 各ゲームモジュールの初期化をtry-catchで囲む
  try {
    countGame.init(document);
    console.log('[gameApp] CountGame initialized');
  } catch (err) {
    console.error('[gameApp] CountGame init error:', err);
  }
  
  try {
    colorGame.init(document);
    console.log('[gameApp] ColorGame initialized');
  } catch (err) {
    console.error('[gameApp] ColorGame init error:', err);
  }
  
  try {
    mazeGame.init(document);
    console.log('[gameApp] MazeGame initialized');
  } catch (err) {
    console.error('[gameApp] MazeGame init error:', err);
  }
  
  try {
    matchGame.init(document);
    console.log('[gameApp] MatchGame initialized');
  } catch (err) {
    console.error('[gameApp] MatchGame init error:', err);
  }
  
  try {
    puzzleGame.init(document);
    console.log('[gameApp] PuzzleGame initialized');
  } catch (err) {
    console.error('[gameApp] PuzzleGame init error:', err);
  }
  
  try {
    animalGame.init(document);
    console.log('[gameApp] AnimalGame initialized');
  } catch (err) {
    console.error('[gameApp] AnimalGame init error:', err);
  }
  
  return {
    gameState,
    audioManager,
    screenManager,
    countGame,
    colorGame,
    mazeGame,
    matchGame,
    puzzleGame,
    animalGame
  };
}
