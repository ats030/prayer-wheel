let score = 0;
let currentNumber = 1;
let currentQuestion = null;
let audioContext = null;
const MAX_NUMBER = 5;
const TOTAL_QUESTIONS = 10;
const SEIKAI = 'seikaion';
const ZANNEN = 'zannen';
let questionsAnswered = 0;

const PICTURES = ['🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒', '🍑'];

function initAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
}

function playSound(type) {
  if (!audioContext) {
    return;
  }
  
  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();
  
  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);
  
  oscillator.type = 'square';
  
  if (type === 'seikaion') {
    oscillator.frequency.value = 440;
    oscillator.start();
    
    setTimeout(() => {
      oscillator.frequency.value = 550;
    }, 100);
    
    setTimeout(() => {
      oscillator.stop();
      oscillator.disconnect();
    }, 300);
  } else {
    oscillator.frequency.value = 330;
    oscillator.start();
    
    setTimeout(() => {
      oscillator.stop();
      oscillator.disconnect();
    }, 300);
  }
  
  gainNode.gain.setValueAtTime(0.5, audioContext.currentTime);
  gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.1);
}

function showScreen(screenId) {
  document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
  document.getElementById(screenId).classList.remove('hidden');
}

function init() {
  document.getElementById('start-btn').addEventListener('click', () => {
    loadScore();
    selectNumber();
  });
  
  document.getElementById('reset-btn').addEventListener('click', resetGame);
  document.getElementById('replay-btn').addEventListener('click', () => {
    saveScore();
    selectNumber();
  });
  
  document.getElementById('next-btn').addEventListener('click', nextQuestion);
  
  renderNumberGrid();
}

function renderNumberGrid() {
  const grid = document.getElementById('number-grid');
  grid.innerHTML = '';
  for (let i = 1; i <= MAX_NUMBER; i++) {
    const btn = document.createElement('button');
    btn.className = 'number-btn';
    btn.textContent = i;
    btn.addEventListener('click', () => {
      currentNumber = i;
      startGame();
    });
    grid.appendChild(btn);
  }
}

function selectNumber() {
  showScreen('number-select-screen');
}

function startGame() {
  score = 0;
  questionsAnswered = 0;
  updateScore();
  showScreen('game-screen');
  generateQuestion();
}

function resetGame() {
  showScreen('title-screen');
  saveScore();
}

function generateQuestion() {
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
    return;
  }
  
  const types = ['count', 'add', 'sub'];
  const type = types[Math.floor(Math.random() * types.length)];
  
  let num1, num2, answer, questionText, emoji, emojiCount;
  
  emoji = PICTURES[Math.floor(Math.random() * PICTURES.length)];
  
  if (type === 'count') {
    emojiCount = Math.floor(Math.random() * currentNumber) + 1;
    answer = emojiCount;
    questionText = `${emoji}はいくつある?`;
  } else if (type === 'add') {
    num1 = Math.floor(Math.random() * currentNumber) + 1;
    num2 = Math.floor(Math.random() * (currentNumber - num1 + 1));
    answer = num1 + num2;
    questionText = `${num1} たす ${num2} は いくつ?`;
  } else if (type === 'sub') {
    num1 = Math.floor(Math.random() * currentNumber) + 2;
    num2 = Math.floor(Math.random() * (num1 - 1)) + 1;
    answer = num1 - num2;
    questionText = `${num1} ひく ${num2} は いくつ?`;
  }
  
  currentQuestion = { answer, questionText, type, emoji, emojiCount };
  document.getElementById('question-text').textContent = questionText;
  renderPicture(type, emoji, num1, num2, emojiCount);
  renderAnswerButtons();
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
  
  const answersArray = Array.from(answers).sort(() => Math.random() - 0.5);
  
  answersArray.forEach(a => {
    const btn = document.createElement('button');
    btn.className = 'answer-btn';
    btn.textContent = a;
    btn.onclick = () => checkAnswer(a);
    container.appendChild(btn);
  });
}

function checkAnswer(selected) {
  const feedbackArea = document.getElementById('feedback-area');
  const feedbackText = document.getElementById('feedback-text');
  
  const q = currentQuestion;
  currentQuestion = null;
  
  feedbackArea.classList.remove('hidden');
  
  console.log('checkAnswer: selected="' + selected + '", q.answer=' + q.answer + ', typeof selected="' + typeof selected + '", typeof q.answer="' + typeof q.answer + '", Number(selected)=' + Number(selected));
  
  if (Number(selected) === q.answer) {
    score += 10;
    updateScore();
    feedbackText.textContent = 'せいかい! +10てん';
    feedbackText.style.color = '#33ff33';
    playSound(SEIKAI);
  } else {
    feedbackText.textContent = 'ざんねん...';
    feedbackText.style.color = '#ff3333';
    playSound(ZANNEN);
  }
  
  questionsAnswered++;
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
  } else {
    generateQuestion();
  }
}

function nextQuestion() {
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    return;
  }
  
  document.getElementById('feedback-area').classList.add('hidden');
  if (questionsAnswered >= TOTAL_QUESTIONS) {
    endGame();
  } else {
    generateQuestion();
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
  document.getElementById('score').textContent = score;
}

function getHighScore() {
  return parseInt(localStorage.getItem('gakushuGameHighScore') || '0');
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