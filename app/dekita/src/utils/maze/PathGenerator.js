/**
 * dekita - Preschool Edition Maze Game Path Generator
 * Generates maze paths for the game
 */

export class PathGenerator {
  constructor() {
    this.gridSize = 5;
    this.cellSize = 60;
    this.margin = 45;
  }

  generate(canvasWidth, canvasHeight) {
    this._currentPath = this.generatePath();
    
    const playerX = this._currentPath[0].x * this.cellSize + this.cellSize / 2;
    const playerY = this._currentPath[0].y * this.cellSize + this.cellSize / 2;
    
    const goalX = this._currentPath[this._currentPath.length - 1].x * this.cellSize + this.cellSize / 2;
    const goalY = this._currentPath[this._currentPath.length - 1].y * this.cellSize + this.cellSize / 2;
    
    return {
      path: this._currentPath,
      player: { x: playerX, y: playerY },
      goal: { x: goalX, y: goalY }
    };
  }

  generatePath() {
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

  draw(ctx, canvasWidth, canvasHeight, startEmoji, endEmoji) {
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);
    
    ctx.strokeStyle = '#FF9800';
    ctx.lineWidth = 10;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    
    const centerX = canvasWidth / 2;
    const centerY = canvasHeight / 2;
    const offsetX = centerX - (this.gridSize - 1) * this.cellSize / 2;
    const offsetY = centerY - (this.gridSize - 1) * this.cellSize / 2;
    
    if (this._currentPath && this._currentPath.length > 0) {
      ctx.beginPath();
      ctx.moveTo(offsetX, offsetY);
      
      for (let i = 1; i < this._currentPath.length; i++) {
        const p = this._currentPath[i];
        const px = offsetX + p.x * this.cellSize;
        const py = offsetY + p.y * this.cellSize;
        ctx.lineTo(px, py);
      }
      
      ctx.stroke();
    }
    
    const emojiSize = 40;
    ctx.font = `${emojiSize}px serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    
    if (this._currentPath && this._currentPath.length > 0) {
      const startX = offsetX;
      const startY = offsetY;
      ctx.fillText(startEmoji, startX, startY);
    }
    
    if (this._currentPath && this._currentPath.length > 0) {
      const lastP = this._currentPath[this._currentPath.length - 1];
      const goalX = offsetX + lastP.x * this.cellSize;
      const goalY = offsetY + lastP.y * this.cellSize;
      ctx.fillText(endEmoji, goalX, goalY);
    }
  }

  setPath(path) {
    this._currentPath = path;
  }
}
