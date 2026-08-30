/**
 * dekita - Preschool Edition Maze Game Path Generator
 * Generates maze paths for the game
 */

export class PathGenerator {
  constructor() {
    this.gridSize = 5;
  }

  generate() {
    return this.generatePath();
  }

  generatePath() {
    // Simple path generation for 5x5 grid
    // Returns an array of coordinates for the maze path
    const path = [];
    let x = 0;
    let y = 0;
    
    path.push({ x, y });
    
    while (x < this.gridSize - 1 || y < this.gridSize - 1) {
      if (x < this.gridSize - 1 && y < this.gridSize - 1) {
        if (Math.random() > 0.5) {
          x++;
        } else {
          y++;
        }
      } else if (x < this.gridSize - 1) {
        x++;
      } else {
        y++;
      }
      path.push({ x, y });
    }
    
    return path;
  }

  isValidMove(x, y, visited) {
    return x >= 0 && x < this.gridSize && y >= 0 && y < this.gridSize && !visited.some(v => v.x === x && v.y === y);
  }
}
