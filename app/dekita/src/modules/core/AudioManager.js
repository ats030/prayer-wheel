/* 
 * dekita - Preschool Edition Audio Manager
   * playAudioQueue(queue, index) - Play audio files in sequence with natural delays
   * Now calculates delay based on audio.duration + natural delay buffer (150ms)
   * For errors, uses minimal delay (100ms) to keep the sequence moving
   */

export class AudioManager {
  constructor() {
    this.enabled = true;
    this.volume = 1.0;
    this.audioContext = null;
    this.state = null;
    this.interAudioDelay = 300;
    this.isPlaying = false;
    this.playbackQueue = [];
    this.currentAudio = null;
  }

  init() {
    if (!this.audioContext) {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    // Resume audioContext if it's suspended (browser policy requirement)
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    return this.audioContext;
  }

  setGameState(state) {
    this.state = state;
  }

  getAudioFilePath(text) {
    const audioMap = {
      'いくつあるかな？': 'audio/count-question.mp3',
      'だれの こえかな？': 'audio/animal-question.mp3',
      'ワンワン！': 'audio/dog-sound.mp3',
      'ニャー！': 'audio/cat-sound.mp3',
      'モー！': 'audio/cow-sound.mp3',
      'ブヒブヒ！': 'audio/pig-sound.mp3',
      'ピーピー！': 'audio/bird-sound.mp3',
      'ガオー！': 'audio/lion-sound.mp3',
      'パオーン！': 'audio/elephant-sound.mp3',
      'ウキキ！': 'audio/monkey-sound.mp3',
      'やったー！': 'audio/correct.mp3',
      'だいじょうぶ！もういっこ！': 'audio/wrong.mp3',
      'いいえ': 'audio/incorrect.mp3',
      'おわった! おめでとう!': 'audio/game-over.mp3',
      'せいかい!': 'audio/correct-feedback.mp3',
      'これ なん の いろかな？': 'audio/color-question.mp3',
      'ペアを見つけてね': 'audio/match-instruction.mp3',
      'これ なん の もんなの？': 'audio/count-question.mp3',
      'はちさんが おはなまで いけるかな?': 'audio/maze-hachi.mp3',
      'うさぎさんが にんじんまで いけるかな?': 'audio/maze-usagi.mp3',
      'ねこさんが おさかなまで いけるかな?': 'audio/maze-neko.mp3',
      'さるさんが バナナまで いけるかな?': 'audio/maze-saru.mp3',
      '10てん！': 'audio/maze-win10.mp3'
    };
    return audioMap[text] || null;
  }

  speak(text) {
    if (!this.enabled) return;
    
    // Map text to audio file path
    const audioFile = this.getAudioFilePath(text);
    if (!audioFile) {
      console.warn('[AudioManager] No audio file for text:', text);
      return;
    }
    
    // Resume audioContext if it's suspended (browser policy requirement)
    if (this.audioContext && this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    // Play audio file
    const audio = new Audio(audioFile);
    audio.volume = this.volume;
    audio.play().catch(err => {
      console.error('[AudioManager] Failed to play audio:', audioFile, 'error:', err);
    });
  }

  playPopSound() {
    if (!this.enabled) return;
    
    // Resume audioContext if it's suspended (browser policy requirement)
    if (this.audioContext && this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    // Play pop sound using audio file
    const audio = new Audio('audio/pop.mp3');
    audio.volume = this.volume;
    audio.play().catch(err => {
      console.error('[AudioManager] Failed to play pop sound:', err);
    });
  }

  playCorrectSound() {
    if (!this.enabled) return;
    
    // Resume audioContext if it's suspended (browser policy requirement)
    if (this.audioContext && this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    // Play correct sound using audio file
    const audio = new Audio('audio/correct.mp3');
    audio.volume = this.volume;
    audio.play().catch(err => {
      console.error('[AudioManager] Failed to play correct sound:', err);
    });
  }

  playWrongSound() {
    if (!this.enabled) return;
    
    // Resume audioContext if it's suspended (browser policy requirement)
    if (this.audioContext && this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    // Play wrong sound using audio file
    const audio = new Audio('audio/wrong.mp3');
    audio.volume = this.volume;
    audio.play().catch(err => {
      console.error('[AudioManager] Failed to play wrong sound:', err);
    });
  }

  playErrorSound() {
    if (!this.enabled) return;
    
    // Resume audioContext if it's suspended (browser policy requirement)
    if (this.audioContext && this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    // Play error sound using audio file
    const audio = new Audio('audio/error.mp3');
    audio.volume = this.volume;
    audio.play().catch(err => {
      console.error('[AudioManager] Failed to play error sound:', err);
    });
  }

  setEnabled(enabled) {
    this.enabled = enabled;
  }

  setInterAudioDelay(delay) {
    this.interAudioDelay = delay;
  }

  playSequence(texts) {
    if (!this.enabled || !texts || texts.length === 0) return;
    
    const queue = texts.map(text => this.getAudioFilePath(text)).filter(path => path !== null);
    
    if (queue.length === 0) return;
    
    this.isPlaying = true;
    this.playAudioQueue(queue, 0);
  }

  /**
   * playAudioQueue(queue, index) - Play audio files in sequence with natural delays
   * Calculates delay based on audio.duration + natural delay buffer (150ms)
   * For errors, uses minimal delay (100ms) to keep the sequence moving
   */
  playAudioQueue(queue, index) {
    if (index >= queue.length) {
      this.isPlaying = false;
      this.currentAudio = null;
      return;
    }

    const audio = new Audio(queue[index]);
    audio.volume = this.volume;
    this.currentAudio = audio;

    const naturalDelayBuffer = 150;

    audio.onloadedmetadata = () => {
      const audioDurationMs = audio.duration * 1000;
      const naturalDelay = audioDurationMs + naturalDelayBuffer;

      const playNext = () => {
        this.currentAudio = null;
        setTimeout(() => {
          this.playAudioQueue(queue, index + 1);
        }, naturalDelay);
      };

      audio.onended = playNext;

      audio.onerror = (err) => {
        console.error('[AudioManager] Audio error:', queue[index], err);
        this.currentAudio = null;
        setTimeout(() => {
          this.playAudioQueue(queue, index + 1);
        }, 100);
      };

      audio.play().catch(err => {
        console.error('[AudioManager] Failed to play audio:', queue[index], err);
        this.currentAudio = null;
        setTimeout(() => {
          this.playAudioQueue(queue, index + 1);
        }, 100);
      });
    };
  }

  saveScore(score) {
    if (score > this.state.highScore) {
      localStorage.setItem('gakushuGameHighScore', score);
    }
  }

  stop() {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    this.isPlaying = false;
    this.playbackQueue = [];
  }

  cleanup() {
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
  }
}
