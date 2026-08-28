/* 
 * dekita - Preschool Edition Storage Utility
 * localStorage operations for high scores
 */

export function saveHighScore(score) {
  localStorage.setItem('gakushuGameHighScore', score);
}

export function loadHighScore() {
  return parseInt(localStorage.getItem('gakushuGameHighScore') || '0', 10);
}

export function clearHighScore() {
  localStorage.removeItem('gakushuGameHighScore');
}
