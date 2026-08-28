/* 
 * dekita - Preschool Edition Path Generator for Mazes
 * Generates maze paths using recursive backtracking
 */

export class PathGenerator {
  constructor(width, height) {
    this.width = width;
    this.height = height;
    this.grid = [];
  }

  generate() {
    this.grid = [];
    for (let y = 0; y < this.height; y++) {
      this.grid[y] = [];
      for (let x = 0; x < this.width; x++) {
        this.grid[y][x] = 1; // 1 = wall, 0 = path
      }
    }

    this.carve(1, 1);
    return this.grid;
  }

  carve(x, y) {
    this.grid[y][x] = 0;
    
    const directions = [
      { dx: 0, dy: -2 },
      { dx: 0, dy: 2 },
      { dx: -2, dy: 0 },
      { dx: 2, dy: 0 }
    ];

    directions.sort(() => Math.random() - 0.5);

    for (const dir of directions) {
      const nx = x + dir.dx;
      const ny = y + dir.dy;

      if (nx >= 1 && nx < this.width - 1 && ny >= 1 && ny < this.height - 1 && this.grid[ny][nx] === 1) {
        this.grid[y + dir.dy / 2][x + dir.dx / 2] = 0;
        this.carve(nx, ny);
      }
    }
  }

  getStart() {
    return { x: 1, y: 1 };
  }

  getEnd() {
    return { x: this.width - 2, y: this.height - 2 };
  }
}
