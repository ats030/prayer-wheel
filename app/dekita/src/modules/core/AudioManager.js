/* 
 * dekita - Preschool Edition Audio Manager
 */

export class AudioManager {
  constructor() {
    this.enabled = true;
    this.pitch = 1.3;
    this.rate = 0.9;
    this.volume = 1.0;
    this.audioContext = null;
    this.state = null;
  }

  init() {
    if (!this.audioContext) {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
  }

  setGameState(state) {
    this.state = state;
  }

   speak(text) {
     if (!this.enabled || !window.speechSynthesis) return;
     
     window.speechSynthesis.cancel();
     const utterance = new SpeechSynthesisUtterance(text);
     utterance.lang = 'ja-JP';
     utterance.pitch = this.pitch;
     utterance.rate = this.rate;
     window.speechSynthesis.speak(utterance);
   }

   playPopSound() {
     if (!this.enabled || !this.audioContext) return;
     
     const oscillator = this.audioContext.createOscillator();
     const gainNode = this.audioContext.createGain();
     
     oscillator.connect(gainNode);
     gainNode.connect(this.audioContext.destination);
     
     oscillator.type = 'sine';
     oscillator.frequency.setValueAtTime(400, this.audioContext.currentTime);
     oscillator.frequency.linearRampToValueAtTime(800, this.audioContext.currentTime + 0.08);
     
     gainNode.gain.setValueAtTime(0.3 * this.volume, this.audioContext.currentTime);
     gainNode.gain.exponentialRampToValueAtTime(0.01, this.audioContext.currentTime + 0.08);
     
     oscillator.start();
     oscillator.stop(this.audioContext.currentTime + 0.08);
   }

  playCorrectSound() {
    if (!this.enabled || !this.audioContext) return;
    
    const ctx = this.audioContext;
    const now = ctx.currentTime;
    
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();
    
    osc1.frequency.value = 440;
    osc2.frequency.value = 550;
    osc1.type = 'sine';
    osc2.type = 'sine';
    
    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);
    
    gain.gain.setValueAtTime(0.3 * this.volume, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.2);
    
    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.2);
    osc2.stop(now + 0.2);
  }

  playWrongSound() {
    if (!this.enabled || !this.audioContext) return;
    
    const ctx = this.audioContext;
    const now = ctx.currentTime;
    
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    
    osc.frequency.value = 330;
    osc.type = 'sawtooth';
    osc.connect(gain);
    gain.connect(ctx.destination);
    
    gain.gain.setValueAtTime(0.3 * this.volume, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);
    
    osc.start(now);
    osc.stop(now + 0.3);
  }

  playErrorSound() {
    if (!this.enabled || !this.audioContext) return;
    
    const ctx = this.audioContext;
    const now = ctx.currentTime;
    
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    
    osc.frequency.value = 220;
    osc.type = 'sawtooth';
    osc.connect(gain);
    gain.connect(ctx.destination);
    
    gain.gain.setValueAtTime(0.3 * this.volume, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);
    
    osc.start(now);
    osc.stop(now + 0.3);
  }

  setEnabled(enabled) {
    this.enabled = enabled;
  }

  saveScore(score) {
    if (score > this.state.highScore) {
      localStorage.setItem('gakushuGameHighScore', score);
    }
  }

  cleanup() {
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
  }
}
