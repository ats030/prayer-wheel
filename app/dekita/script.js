let score = 0;
let currentNumber = 1;
let currentQuestion = null;
let audioContext = null;
let gameMode = 'number';
let questionsAnswered = 0;
const MAX_NUMBER = 5;
const TOTAL_QUESTIONS = 10;
const SEIKAI = 'seikaion';
const ZANNEN = 'zannen';

// 音声ガイド設定
let voiceEnabled = true;
const TEXTS = {
  start: 'スタート！',
  end: 'おわった!',
  score: 'スコア',
  progress: '{current}/{total} 問',
  wrong: 'だいじょうぶ！もういっこ！',
  correct: 'やったー！',
  wrongMaze: 'だいじょうぶ！もういっこ！',
  correctMaze: 'やったー！',
  wrongText: 'だいじょうぶ！もういっこ！',
  correctText: 'やったー！',
  wrongAnimal: 'だいじょうぶ！もういっこ！',
  correctAnimal: 'やったー！',
  wrongColor: 'だいじょうぶ！もういっこ！',
  correctColor: 'やったー！',
  wrongMaze2: 'だいじょうぶ！もういっこ！',
  correctMaze2: 'やったー！',
  tryAgain: 'もういっこ！',
  nextQuestion: 'つぎのしつもん！',
  correctMaze3: 'やったー！',
  welcome: 'welcome'
};

const PICTURES = ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒', '🍑'];

const COLORS = [
  { name: 'あか', hex: '#ff3333' },
  { name: 'あお', hex: '#3333ff' },
  { name: 'きいろ', hex: '#ffff33' },
  { name: 'みどり', hex: '#33ff33' }
];

const COLOR_EMOJIS = {
  'あか': ['🍎', '🍓', '🍒', '🍅'],
  'あお': ['🐳', '🧊', '🔵', '🐬'],
  'きいろ': ['🍌', '🍋', '🌽', '🌻'],
  'みどり': ['🥦', '🍐', '🥬', '🍏']
};

const ANIMAL_DATA = [
  { name: 'いぬ', emoji: '🐶', sound: 'ワンワン！' },
  { name: 'ねこ', emoji: '🐱', sound: 'ニャー！' },
  { name: 'うし', emoji: '🐮', sound: 'モー！' },
  { name: 'ぶた', emoji: '🐷', sound: 'ブヒブヒ！' },
  { name: 'とり', emoji: '🐦', sound: 'ピーピー！' },
  { name: 'らいおん', emoji: '🦁', sound: 'ガオー！' },
  { name: 'ぞう', emoji: '🐘', sound: 'パオーン！' },
  { name: 'さる', emoji: '🐒', sound: 'ウキキ！' }
];

function initAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
}

function speak(text) {
  if (!window.speechSynthesis) return;
  
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'ja-JP';
  utterance.pitch = 1.3;
  utterance.rate = 0.9;
  window.speechSynthesis.speak(utterance);
}

let isTestMode = false;

function setTestMode(mode) {
  isTestMode = mode;
}

function playPopSound() {
  if (!audioContext) return;
  
  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();
  
  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);
  
  oscillator.type = 'sine';
  oscillator.frequency.setValueAtTime(400, audioContext.currentTime);
  oscillator.frequency.exponentialRampToValueAtTime(800, audioContext.currentTime + 0.08);
  
  gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
  gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.08);
  
  oscillator.start();
  oscillator.stop(audioContext.currentTime + 0.08);
}


function showScreen(screenId) {
  const screens = document.querySelectorAll('.screen');
  screens.forEach(s => s.classList.add('hidden'));
  
  const newScreen = document.getElementById(screenId);
  newScreen.classList.remove('hidden');
  
  // 強制再描画（画面遷移の安定化）
  void newScreen.offsetWidth;
}

function init() {
  document.getElementById('start-btn').addEventListener('click', () => {
    console.log('start-btn clicked');
    initAudioContext();
    playPopSound();
    gameMode = 'number';
    loadScore();
    startGame();
  });
  
  document.getElementById('color-start-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    gameMode = 'color';
    loadScore();
    startColorGame();
  });

  document.getElementById('animal-start-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    gameMode = 'animal';
    loadScore();
    startAnimalGame();
  });

  document.getElementById('maze-start-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    gameMode = 'maze';
    questionsAnswered = 0;
    score = 0;
    startMazeGame();
  });
  
  document.getElementById('reset-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    resetGame();
  });
  document.getElementById('color-reset-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    resetGame();
  });
  document.getElementById('replay-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    saveScore();
    showTitle();
  });
  
  document.getElementById('next-btn').addEventListener('click', () => {
    initAudioContext();
    playPopSound();
    nextQuestion();
  });
  
  // 迷路のイベントリスナーを一度だけ登録
  initMazeEvents(document.getElementById('maze-canvas'));
  
  renderNumberGrid();
}

function showTitle() {
  score = 0;
  updateScore();
  document.getElementById('picture-area').innerHTML = '';
  document.getElementById('answer-buttons').innerHTML = '';
  document.getElementById('feedback-area').classList.add('hidden');
  showScreen('title-screen');
}

function renderNumberGrid() {
  const grid = document.getElementById('number-grid');
  grid.innerHTML = '';
  for (let i = 1; i <= MAX_NUMBER; i++) {
    const btn = document.createElement('button');
    btn.className = 'number-btn';
    btn.textContent = i;
    btn.addEventListener('click', () => {
      playPopSound();
      currentNumber = i;
      startGameWithNumber(i);
    });
    grid.appendChild(btn);
  }
}

function startGame() {
  score = 0;
  questionsAnswered = 0;
  currentNumber = 5;
  updateScore();
  showScreen('game-screen');
  generateQuestion();
}

function selectNumber() {
}

function resetGame() {
  gameMode = 'number';
  showScreen('title-screen');
  saveScore();
  if (window.audioContext) {
    window.audioContext.close();
  }
  
  mazeActive = false;
  mazePlayer = { x: 0, y: 0 };
  mazeGoal = { x: 0, y: 0 };
  mazePath = [];
  mazeCurrentTheme = null;
  
  // 色当てゲーム用
  if (window.currentQuestion) {
    window.currentQuestion = null;
  }
}

function startAnimalGame() {
  score = 0;
  questionsAnswered = 0;
  updateScore();
  showScreen('game-screen');
  generateAnimalQuestion();
}

function generateAnimalQuestion() {
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
    return;
  }

  const target = ANIMAL_DATA[Math.floor(Math.random() * ANIMAL_DATA.length)];
   currentQuestion = {
     answer: target.name,
     questionText: 'だれの こえかな？',
     type: 'animal',
     animalEmoji: target.emoji,
     animalSound: target.sound
   };

  document.getElementById('question-text').textContent = currentQuestion.questionText;
  
  const pictureArea = document.getElementById('picture-area');
  pictureArea.innerHTML = '';
  const soundIcon = document.createElement('div');
  soundIcon.className = 'sound-icon';
  soundIcon.textContent = '🔊';
  soundIcon.style.fontSize = '80px';
  pictureArea.appendChild(soundIcon);

  renderAnimalAnswerButtons();

  // 音声ガイドと鳴き声を読み上げ
  speak(currentQuestion.questionText);
  setTimeout(() => {
    speak(target.sound);
  }, 1500);
}

function renderAnimalAnswerButtons() {
  const container = document.getElementById('answer-buttons');
  container.innerHTML = '';
  
  const answers = new Set();
  answers.add(currentQuestion.answer);
  
  while (answers.size < 4) {
    const randomAnimal = ANIMAL_DATA[Math.floor(Math.random() * ANIMAL_DATA.length)].name;
    answers.add(randomAnimal);
  }
  
  const answersArray = Array.from(answers);
  shuffleArray(answersArray);
  
  answersArray.forEach(name => {
    const animal = ANIMAL_DATA.find(a => a.name === name);
    const btn = document.createElement('button');
    btn.className = 'answer-btn';
    btn.textContent = `${animal.emoji} ${name}`;
    btn.onclick = () => checkAnswer(name);
    container.appendChild(btn);
  });
}

// Fisher-Yates シャッフル関数
function shuffleArray(array) {
  for (let i = array.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [array[i], array[j]] = [array[j], array[i]];
  }
  return array;
}

const MAZE_THEMES = [
  { start: '🐝', end: '🌸', text: 'はちさんが おはなまで いけるかな?' },
  { start: '🐰', end: '🥕', text: 'うさぎさんが にんじんまで いけるかな?' },
  { start: '🐱', end: '🐟', text: 'ねこさんが おさかなまで いけるかな?' },
  { start: '🐵', end: '🍌', text: 'さるさんが バナナまで いけるかな?' }
];

let mazeActive = false;
let mazePlayer = { x: 0, y: 0 };
let mazeGoal = { x: 0, y: 0 };
let mazePath = [];
let mazeCurrentTheme = null;

function shuffleArray(array) {
  for (let i = array.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [array[i], array[j]] = [array[j], array[i]];
  }
  return array;
}

function startMazeGame() {
  score = 0;
  questionsAnswered = 0;
  updateScore();
  showScreen('maze-theme-select-screen');
  initMazeThemeButtons();
  console.log('Maze theme buttons initialized');
}

function initMazeThemeButtons() {
  const container = document.getElementById('maze-theme-buttons');
  container.innerHTML = '';
  MAZE_THEMES.forEach((theme, index) => {
    const btn = document.createElement('button');
    btn.className = 'maze-theme-btn';
    let themeText = '';
    if (theme.start === '🐝') themeText = 'はちさん';
    else if (theme.start === '🐰') themeText = 'うさぎさん';
    else if (theme.start === '🐱') themeText = 'ねこさん';
    else if (theme.start === '🐵') themeText = 'さるさん';
    btn.textContent = themeText;
    btn.onclick = () => {
      console.log('Maze theme button clicked, index:', index);
      setTestMode(true);
      try {
        playPopSound();
        setupMaze(index);
        console.log('Maze theme button click (setupMaze) succeeded');
      } catch (error) {
        console.error('Error in maze theme button click (setupMaze):', error);
      }
      try {
        showScreen('game-screen');
        drawMaze();
        const canvas = document.getElementById('maze-canvas');
        initMazeEvents(canvas);
        console.log('Maze theme button click succeeded');
      } catch (error) {
        console.error('Error in maze theme button click (after setupMaze):', error);
      }
    };
    container.appendChild(btn);
  });
}

function setupMaze(themeIndex = null) {
  mazeActive = true;
  const canvas = document.getElementById('maze-canvas');
  const picArea = document.getElementById('picture-area');
  const qText = document.getElementById('question-text');
  const ansBtns = document.getElementById('answer-buttons');

  picArea.classList.add('hidden');
  ansBtns.classList.add('hidden');
  qText.classList.remove('hidden');
  canvas.classList.remove('hidden');

  if (themeIndex !== null && themeIndex >= 0 && themeIndex < MAZE_THEMES.length) {
    mazeCurrentTheme = MAZE_THEMES[themeIndex];
  } else {
    mazeCurrentTheme = MAZE_THEMES[Math.floor(Math.random() * MAZE_THEMES.length)];
  }
  qText.textContent = mazeCurrentTheme.text;
  if (!isTestMode) {
    speak(mazeCurrentTheme.text);
  }
  
  canvas.width = 300;
  canvas.height = 300;
  
  generateRandomPath(canvas);
  drawMaze();
}

function generateRandomPath(canvas) {
  // 8x8グリッドの経路を生成（自然で滑らかな一本線、尖った経路と交差を避ける）
  const gridCols = 8;
  const gridRows = 8;
  
  mazePath = [];
  
  // 始点（左上付近）
  mazePath.push({ x: 1, y: 1 });
  
  let current = { x: 1, y: 1 };
  
  // 前2つの移動方向を記録（滑らかさを保つため）
  let directionHistory = [];
  
  // 既に通った地点を記録（交差防止）
  const visited = new Set();
  visited.add('1,1');
  
  // ゴールへ向かうルートを生成（可能な限り一本線で滑らかに）
  let loopCount = 0;
  const maxLoops = 10000;
  while (current.x !== gridCols - 2 || current.y !== gridRows - 2) {
    loopCount++;
    if (loopCount > maxLoops) {
      console.warn('generateRandomPath: max loops reached, breaking');
      break;
    }
    const possibleMoves = [];
    
    // 目標方向を計算
    const targetX = gridCols - 2;
    const targetY = gridRows - 2;
    
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
        x: current.x - mazePath[mazePath.length - 1].x,
        y: current.y - mazePath[mazePath.length - 1].y
      };
      directionHistory.push(moveDir);
      if (directionHistory.length > 2) {
        directionHistory.shift();
      }
      
      mazePath.push(current);
    } else {
      // 進路が塞がれている場合はバックアップ
      if (mazePath.length > 1) {
        const removed = mazePath.pop();
        visited.delete(`${removed.x},${removed.y}`);
        directionHistory.pop();
        current = mazePath[mazePath.length - 1];
        continue;
      }
      break;
    }
  }
  
   // 終点が達成されていない場合、強制的に終点へ
   if (current.x !== gridCols - 2 || current.y !== gridRows - 2) {
     mazePath.push({ x: gridCols - 2, y: gridRows - 2 });
   }
   
   // グリッド座標をピクセル座標に変換（中心点）
   const cellSize = canvas.width / gridCols;
   mazePath = mazePath.map(p => ({
     x: p.x * cellSize + cellSize / 2,
     y: p.y * cellSize + cellSize / 2
   }));
  
  // プレイヤーとゴールの初期位置
  mazePlayer = { x: mazePath[0].x, y: mazePath[0].y };
  mazeGoal = { x: mazePath[mazePath.length - 1].x, y: mazePath[mazePath.length - 1].y };
}

function drawMaze() {
  const canvas = document.getElementById('maze-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const cellSize = canvas.width / 8;
  
  // 経路を太線で描画（直線と曲線を組み合わせる）
  ctx.beginPath();
  ctx.lineWidth = 20;
  ctx.strokeStyle = '#81D4FA';
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  
  if (mazePath.length > 0) {
    ctx.moveTo(mazePath[0].x, mazePath[0].y);
    
    for (let i = 1; i < mazePath.length; i++) {
      const prev = mazePath[i - 1];
      const curr = mazePath[i];
      
      // 最後の点は直線で結ぶ
      if (i === mazePath.length - 1) {
        ctx.lineTo(curr.x, curr.y);
        continue;
      }
      
      const next = mazePath[i + 1];
      
      // 方向ベクトルを計算
      const dx1 = curr.x - prev.x;
      const dy1 = curr.y - prev.y;
      const dx2 = next.x - curr.x;
      const dy2 = next.y - curr.y;
      
      // 同じ方向（直線）
      if ((dx1 === 0 && dx2 === 0) || (dy1 === 0 && dy2 === 0)) {
        ctx.lineTo(curr.x, curr.y);
      } else {
        // 曲線（90度の転換）- 曲率半径は2マス以上
        const controlRadius = cellSize * 2.5; // 2マス以上の半径
        
        // 前の点への制御点
        const prevCtrlX = curr.x - (dx1 ? dx1 * controlRadius / Math.abs(dx1) : 0);
        const prevCtrlY = curr.y - (dy1 ? dy1 * controlRadius / Math.abs(dy1) : 0);
        
        // 次の点への制御点
        const nextCtrlX = curr.x + (dx2 ? dx2 * controlRadius / Math.abs(dx2) : 0);
        const nextCtrlY = curr.y + (dy2 ? dy2 * controlRadius / Math.abs(dy2) : 0);
        
        ctx.bezierCurveTo(prevCtrlX, prevCtrlY, nextCtrlX, nextCtrlY, curr.x, curr.y);
      }
    }
  }
  ctx.stroke();
  
  // ゴール地点の絵文字
  ctx.font = '36px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(mazeCurrentTheme.end, mazeGoal.x, mazeGoal.y);

  // プレイヤーの絵文字
  ctx.font = '32px serif';
  ctx.fillText(mazeCurrentTheme.start, mazePlayer.x, mazePlayer.y);
  
  // 経路外の境界線（失敗判定用） - 簡略化
  ctx.beginPath();
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#E57373';
  for (let x = 0; x <= 8; x++) {
    ctx.moveTo(x * (canvas.width / 8), 0);
    ctx.lineTo(x * (canvas.width / 8), canvas.height);
  }
  for (let y = 0; y <= 8; y++) {
    ctx.moveTo(0, y * (canvas.height / 8));
    ctx.lineTo(canvas.width, y * (canvas.height / 8));
  }
  ctx.stroke();
}

function initMazeEvents(canvas) {
  const handleMove = (e) => {
    if (!mazeActive) return;
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    
    mazePlayer.x = clientX - rect.left;
    mazePlayer.y = clientY - rect.top;

    // 経路外に出たら即失敗
    if (!isPath(mazePlayer.x, mazePlayer.y)) {
      handleMazeFail();
      return;
    }

    // ゴール判定
    const dist = Math.hypot(mazePlayer.x - mazeGoal.x, mazePlayer.y - mazeGoal.y);
    if (dist < 30) {
      mazeActive = false;
      handleMazeWin();
    }

    drawMaze();
  };

  canvas.addEventListener('mousemove', handleMove);
  canvas.addEventListener('touchmove', (e) => {
    e.preventDefault();
    handleMove(e);
  }, { passive: false });
}

function isPath(x, y) {
  if (mazePath.length === 0) return false;
  
  const canvas = document.getElementById('maze-canvas');
  const cellSize = canvas ? canvas.width / 8 : 37.5;
  const tolerance = cellSize * 1.8; // 外れ判定をさらに緩和
  
  for (const p of mazePath) {
    const dist = Math.hypot(x - p.x, y - p.y);
    if (dist < tolerance) return true;
  }
  
  return false;
}

function handleMazeFail() {
  mazeActive = false;
  
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
    return;
  }
  
  document.getElementById('feedback-area').classList.remove('hidden');
  document.getElementById('feedback-text').textContent = 'だいじょうぶ！もういっこ！';
  document.getElementById('feedback-text').style.color = '#E57373';
  speak('まちがい。つぎのしつもん！');
  
  updateScore();
  
  setTimeout(() => {
    document.getElementById('feedback-area').classList.add('hidden');
    nextQuestion();
  }, 2000);
}

function handleMazeWin() {
  mazeActive = false;
  
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
    return;
  }
  
  score += 10;
  updateScore();
  document.getElementById('feedback-area').classList.remove('hidden');
  document.getElementById('feedback-text').textContent = 'やったー！';
  document.getElementById('feedback-text').style.color = '#4CAF50';
  speak('やったー！');
  
  setTimeout(() => {
    document.getElementById('feedback-area').classList.add('hidden');
    nextQuestion();
  }, 2000);
}

function generateQuestion() {
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
    return;
  }
  
  if (gameMode === 'color') {
    generateColorQuestion();
    return;
  }
  
  if (gameMode === 'animal') {
    generateAnimalQuestion();
    return;
  }

  if (gameMode === 'maze') {
    setupMaze(); // mazeCurrentTheme is set by initMazeThemeButtons during mode selection
    return;
  }
  
  // 3歳児向けにカウントのみに限定
  const type = 'count';
  const emoji = PICTURES[Math.floor(Math.random() * PICTURES.length)];
  const emojiCount = Math.floor(Math.random() * 5) + 1; // 1〜5まで
  const answer = emojiCount;
  const questionText = `${emoji}はいくつあるかな？`;
  
  currentQuestion = { answer, questionText, type, emoji, emojiCount };
  document.getElementById('question-text').textContent = questionText;
  renderPicture(type, emoji, null, null, emojiCount);
  renderAnswerButtons();
  
  // 問題文を読み上げ
  speak(questionText);
}

function generateColorQuestion() {
  const colorIndex = Math.floor(Math.random() * COLORS.length);
  const target = COLORS[colorIndex];
  const colorName = target.name;
  const emojisOfColor = COLOR_EMOJIS[colorName];
  const randomEmoji = emojisOfColor[Math.floor(Math.random() * emojisOfColor.length)];
  
   currentQuestion = {
      answer: colorName,
      questionText: 'これ なん の いろかな？',
      type: 'color',
      emoji: randomEmoji
    };
    document.getElementById('color-question-text').textContent = currentQuestion.questionText;
    const pictureArea = document.getElementById('color-swatch');
    pictureArea.innerHTML = '';
    const emojiSpan = document.createElement('span');
    emojiSpan.textContent = randomEmoji;
    emojiSpan.style.fontSize = 'clamp(70px, 22dvw, 140px)';
    pictureArea.appendChild(emojiSpan);
  window.correctAnswer = colorName;
  renderColorAnswerButtons();
  
  speak(currentQuestion.questionText);
}

function renderColorAnswerButtons() {
  const container = document.getElementById('color-answer-buttons');
  container.innerHTML = '';
  COLORS.forEach(c => {
    const btn = document.createElement('button');
    btn.className = 'answer-btn color-answer-btn';
    btn.textContent = c.name;
    btn.style.backgroundColor = c.hex;
    btn.style.color = (c.name === 'きいろ') ? '#5D4037' : 'white';
    if (c.name === window.correctAnswer) {
      btn.setAttribute('data-correct', 'true');
    } else {
      btn.setAttribute('data-correct', 'false');
    }
    btn.onclick = () => checkAnswer(c.name);
    container.appendChild(btn);
  });
}

function startColorGame() {
  gameMode = 'color';
  score = 0;
  questionsAnswered = 0;
  updateScore();
  showScreen('color-game-screen');
  generateColorQuestion();
}

function renderPicture(type, emoji, num1, num2, emojiCount) {
  const pictureArea = document.getElementById('picture-area');
  pictureArea.innerHTML = '';
  
  if (type === 'count') {
    for (let i = 0; i < emojiCount; i++) {
      const span = document.createElement('span');
      span.className = 'picture-item';
      span.textContent = emoji;
      pictureArea.appendChild(span);
    }
  } else if (type === 'add') {
    const group1 = document.createElement('span');
    group1.className = 'picture-group';
    for (let i = 0; i < num1; i++) {
      const item = document.createElement('span');
      item.className = 'picture-item';
      item.textContent = emoji;
      group1.appendChild(item);
    }
    const separator = document.createElement('span');
    separator.textContent = ' | ';
    separator.className = 'separator';
    pictureArea.appendChild(group1);
    pictureArea.appendChild(separator);
    const group2 = document.createElement('span');
    group2.className = 'picture-group';
    for (let i = 0; i < num2; i++) {
      const item = document.createElement('span');
      item.className = 'picture-item';
      item.textContent = emoji;
      group2.appendChild(item);
    }
    pictureArea.appendChild(group2);
  } else if (type === 'sub') {
    const remaining = num1 - num2;
    for (let i = 0; i < remaining; i++) {
      const span = document.createElement('span');
      span.className = 'picture-item';
      span.textContent = emoji;
      pictureArea.appendChild(span);
    }
  }
}

function renderAnswerButtons() {
  const container = document.getElementById('answer-buttons');
  container.innerHTML = '';
  
  const correctAnswer = currentQuestion.answer;
  const answers = new Set();
  answers.add(correctAnswer);
  
  while (answers.size < 4) {
    const wrong = Math.floor(Math.random() * (MAX_NUMBER + 1));
    if (!answers.has(wrong)) {
      answers.add(wrong);
    }
  }
  
   const answersArray = Array.from(answers);
   const originalCorrectValue = correctAnswer;
   shuffleArray(answersArray);
   
   answersArray.forEach(a => {
    const btn = document.createElement('button');
    btn.className = 'answer-btn';
    btn.textContent = a;
    btn.setAttribute('data-correct', a === originalCorrectValue ? 'true' : 'false');
    btn.onclick = () => checkAnswer(a);
    container.appendChild(btn);
  });
}

function checkAnswer(selected) {
  const isColorGame = gameMode === 'color';
  const feedbackArea = document.getElementById(isColorGame ? 'color-feedback-area' : 'feedback-area');
  const feedbackText = document.getElementById(isColorGame ? 'color-feedback-text' : 'feedback-text');
  
  const q = currentQuestion;
  currentQuestion = null;
  
  feedbackArea.classList.remove('hidden');
  
  const correct = q.answer;
  const answerValue = typeof correct === 'number' ? parseInt(correct, 10) : String(correct);
  const selectedValue = typeof selected === 'number' ? parseInt(selected, 10) : String(selected).trim();
  
  if (answerValue === selectedValue) {
    score += 10;
    updateScore();
    feedbackText.textContent = 'やったー！＋10てん';
    feedbackText.style.color = '#4CAF50';
    speak('やったー！');
    playPopSound();
  } else {
    feedbackText.textContent = 'だいじょうぶ！もういっこ！';
    feedbackText.style.color = '#E57373';
    speak('ちょんぼ。もういっこ！');
  }
  
  setTimeout(() => {
    document.getElementById(isColorGame ? 'color-feedback-area' : 'feedback-area').classList.add('hidden');
    nextQuestion();
  }, 2000);
}

function nextQuestion() {
  questionsAnswered++;
  updateScore();
  const isColorGame = gameMode === 'color';
  document.getElementById(isColorGame ? 'color-feedback-area' : 'feedback-area').classList.add('hidden');
  
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
  } else {
    if (isColorGame) {
      generateColorQuestion();
    } else {
      generateQuestion();
    }
  }
}

function endGame() {
  showScreen('result-screen');
  document.getElementById('final-score').textContent = score;
  if (score > getHighScore()) {
    localStorage.setItem('gakushuGameHighScore', score);
  }
}

function updateScore() {
  const isColorGame = gameMode === 'color';
  if (isColorGame) {
    document.getElementById('color-score').textContent = score;
  } else {
    document.getElementById('score').textContent = score;
    document.getElementById('progress-text').textContent = `${questionsAnswered + 1}/${TOTAL_QUESTIONS} 問`;
  }
}

function getHighScore() {
  return parseInt(localStorage.getItem('gakushuGameHighScore') || '0');
}

function updateHighScoreDisplay() {
  const highScore = getHighScore();
  if (highScore > 0) {
    console.log(`前回の最高点: ${highScore}点`);
  }
}

function saveScore() {
  if (score > getHighScore()) {
    localStorage.setItem('gakushuGameHighScore', score);
  }
}

function loadScore() {
  const saved = localStorage.getItem('gakushuGameHighScore');
  if (saved) {
    const highScore = parseInt(saved);
    if (highScore > 0) {
      console.log(`前回の最高点: ${highScore}てん`);
    }
  }
}

window.addEventListener('load', init);