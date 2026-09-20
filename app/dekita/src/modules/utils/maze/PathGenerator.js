/* 
 * dekita - Preschool Edition Path Generator for Mazes
 * Generates smooth maze paths using bezierCurveTo
 */

export class PathGenerator {
  constructor() {
    this.path = [];
  }

  generate(canvasWidth, canvasHeight) {
    const gridCols = 8;
    const gridRows = 8;
    const rangeStart = 1;
    const rangeEnd = gridCols - 2;

    const randomCoord = () =>
      rangeStart + Math.floor(Math.random() * (rangeEnd - rangeStart + 1));

    this.path = [];

    // 始点（端から1セル余白のある範囲でランダム）
    let start = { x: randomCoord(), y: randomCoord() };

    // ゴール（始点と異なる範囲内のランダム地点）
    let goal = { x: randomCoord(), y: randomCoord() };
    while (goal.x === start.x && goal.y === start.y) {
      goal = { x: randomCoord(), y: randomCoord() };
    }

    const targetX = goal.x;
    const targetY = goal.y;

    this.path.push({ ...start });

    let current = { ...start };

    // 前2つの移動方向を記録（滑らかさを保つため）
    let directionHistory = [];

    // 既に通った地点を記録（交差防止）
    const visited = new Set();
    visited.add(`${start.x},${start.y}`);

    // ゴールへ向かうルートを生成（可能な限り一本線で滑らかに）
    let loopCount = 0;
    const maxLoops = 10000;
    while (current.x !== targetX || current.y !== targetY) {
      loopCount++;
      if (loopCount > maxLoops) {
        console.warn('generateRandomPath: max loops reached, breaking');
        break;
      }
      const possibleMoves = [];
      
      // 2つ前の方向を取得（尖った経路回避用）
      let prev2Move = { x: 0, y: 0 };
      if (directionHistory.length >= 2) {
        prev2Move = directionHistory[directionHistory.length - 2];
      }
      
      // 範囲内且つ制約条件を満たす移動候補（尖った90度曲がりと交差を避ける）
      
      // 上へ移動
      if (current.y > targetY && current.y > 1) {
        const wouldBeReverse = (prev2Move.x === 0 && prev2Move.y === 1);
        const wouldBeSharpTurn = (prev2Move.x === 1 && prev2Move.y === 0);
        const wouldVisitVisited = visited.has(`${current.x},${current.y - 1}`);
        if (!wouldBeReverse && !wouldBeSharpTurn && !wouldVisitVisited) {
          possibleMoves.push({ x: current.x, y: current.y - 1 });
        }
      }
      // 下へ移動
      if (current.y < targetY && current.y < gridRows - 2) {
        const wouldBeReverse = (prev2Move.x === 0 && prev2Move.y === -1);
        const wouldBeSharpTurn = (prev2Move.x === -1 && prev2Move.y === 0);
        const wouldVisitVisited = visited.has(`${current.x},${current.y + 1}`);
        if (!wouldBeReverse && !wouldBeSharpTurn && !wouldVisitVisited) {
          possibleMoves.push({ x: current.x, y: current.y + 1 });
        }
      }
      // 左へ移動
      if (current.x > targetX && current.x > 1) {
        const wouldBeReverse = (prev2Move.x === 1 && prev2Move.y === 0);
        const wouldBeSharpTurn = (prev2Move.x === 0 && prev2Move.y === -1);
        const wouldVisitVisited = visited.has(`${current.x - 1},${current.y}`);
        if (!wouldBeReverse && !wouldBeSharpTurn && !wouldVisitVisited) {
          possibleMoves.push({ x: current.x - 1, y: current.y });
        }
      }
      // 右へ移動
      if (current.x < targetX && current.x < gridCols - 2) {
        const wouldBeReverse = (prev2Move.x === -1 && prev2Move.y === 0);
        const wouldBeSharpTurn = (prev2Move.x === 0 && prev2Move.y === 1);
        const wouldVisitVisited = visited.has(`${current.x + 1},${current.y}`);
        if (!wouldBeReverse && !wouldBeSharpTurn && !wouldVisitVisited) {
          possibleMoves.push({ x: current.x + 1, y: current.y });
        }
      }
      
      // 候補があれば選択
      if (possibleMoves.length > 0) {
        // 目標方向へ向かう候補を優先
        const forwardMoves = possibleMoves.filter(move => {
          const dxToTarget = targetX - current.x;
          const dyToTarget = targetY - current.y;
          const dxMove = move.x - current.x;
          const dyMove = move.y - current.y;
          
          // 目標方向へ進む移動のみ
          return (dxToTarget >= 0 && dxMove > 0) || (dxToTarget <= 0 && dxMove < 0) ||
                 (dyToTarget >= 0 && dyMove > 0) || (dyToTarget <= 0 && dyMove < 0);
        });
        
        if (forwardMoves.length > 0) {
          current = forwardMoves[Math.floor(Math.random() * forwardMoves.length)];
        } else {
          current = possibleMoves[Math.floor(Math.random() * possibleMoves.length)];
        }
        
        // 既に訪れた地点としてマーク
        const key = `${current.x},${current.y}`;
        if (!visited.has(key)) {
          visited.add(key);
        }
        
        // 移動方向を記録
        const moveDir = {
          x: current.x - this.path[this.path.length - 1].x,
          y: current.y - this.path[this.path.length - 1].y
        };
        directionHistory.push(moveDir);
        if (directionHistory.length > 2) {
          directionHistory.shift();
        }
        
        this.path.push(current);
      } else {
        // 進路が塞がれている場合はバックアップ
        if (this.path.length > 1) {
          this.path.pop();
          directionHistory.pop();
          current = this.path[this.path.length - 1];
          continue;
        }
        break;
      }
    }
    
     // 終点が達成されていない場合、強制的に終点へ
      if (current.x !== targetX || current.y !== targetY) {
        this.path.push({ x: targetX, y: targetY });
      }
     
     // グリッド座標をピクセル座標に変換（中心点）
     const cellSize = canvasWidth / gridCols;
     this.path = this.path.map(p => ({
       x: p.x * cellSize + cellSize / 2,
       y: p.y * cellSize + cellSize / 2
     }));
    
    // プレイヤーとゴールの初期位置
    const player = { x: this.path[0].x, y: this.path[0].y };
    const goalPos = { x: this.path[this.path.length - 1].x, y: this.path[this.path.length - 1].y };

    return { path: this.path, player, goal: goalPos };
  }

  draw(ctx, canvasWidth, canvasHeight, themeEmojiStart, themeEmojiEnd) {
    console.log('PathGenerator.draw called:');
    console.log('  canvasWidth:', canvasWidth);
    console.log('  canvasHeight:', canvasHeight);
    console.log('  themeEmojiStart:', themeEmojiStart);
    console.log('  themeEmojiEnd:', themeEmojiEnd);
    console.log('  this.path.length:', this.path.length);
    
    const gridCols = 8;
    const cellSize = canvasWidth / gridCols;

    ctx.clearRect(0, 0, canvasWidth, canvasHeight);

    // 経路を描画
    ctx.beginPath();
    ctx.lineWidth = 10;
    ctx.strokeStyle = '#81D4FA';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    if (this.path.length > 0) {
      ctx.moveTo(this.path[0].x, this.path[0].y);

      for (let i = 1; i < this.path.length; i++) {
        ctx.lineTo(this.path[i].x, this.path[i].y);
      }
    }
    ctx.stroke();

    // ゴール地点の絵文字
    ctx.font = '36px serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(themeEmojiEnd, this.path[this.path.length - 1].x, this.path[this.path.length - 1].y);

    // 経路外の境界線（失敗判定用）
    ctx.beginPath();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#E57373';
    for (let x = 0; x <= 8; x++) {
      ctx.moveTo(x * cellSize, 0);
      ctx.lineTo(x * cellSize, canvasHeight);
    }
    for (let y = 0; y <= 8; y++) {
      ctx.moveTo(0, y * cellSize);
      ctx.lineTo(canvasWidth, y * cellSize);
    }
    ctx.stroke();
  }

  getPath() {
    return this.path;
  }
}
