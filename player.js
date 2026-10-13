// Reuse one media element so touch-initiated playback stays on the same element.
export class SutraPlayer {
  constructor(chunks, audio, changed = () => {}) {
    Object.assign(this, { chunks, audio, changed, pending: [], active: null,
      nextSequence: 0, currentSequence: -1, turns: 0, angle: 0, paused: false,
      completedCycles: new Set(), error: '', notice: '', generation: 0, timer: null });
    this.detach = () => {};
  }

  forward() {
    if (this.error || this.pending.length >= 5) {
      this.notice = this.error ? '音声を再試行してから回してください。'
        : '予約は5句までです。読み上げをお待ちください。';
      this.changed();
      return false;
    }
    this.pending.push({ sequence: this.nextSequence++, started: false });
    this.turns++;
    this.angle += 30;
    this.notice = '';
    this.pump();
    this.changed();
    return true;
  }

  backward() {
    if (this.pending.length) {
      this.nextSequence = this.pending.pop().sequence;
      this.turns = Math.max(0, this.turns - 1);
      this.angle -= 30;
      this.notice = '末尾の予約を1句取り消しました。';
    } else {
      const sequence = this.active?.sequence ?? this.currentSequence;
      if (sequence <= 0) {
        this.notice = 'ここが最初の句です。';
        this.changed();
        return false;
      }
      this.stopAudio();
      this.active = { sequence: sequence - 1, started: false, needsSource: true };
      this.error = '';
      this.nextSequence = sequence;
      this.turns = Math.max(0, this.turns - 1);
      this.angle -= 30;
      this.notice = '前の句を読み直します。';
      if (!this.paused) this.playActive(true);
    }
    this.changed();
    return true;
  }

  pump() {
    if (this.active || this.paused || this.error || !this.pending.length) return;
    this.active = this.pending.shift();
    this.playActive(true);
  }

  playActive(newSource) {
    const entry = this.active;
    const token = ++this.generation;
    this.detach();
    const valid = () => this.active === entry && this.generation === token;
    const fail = (message) => {
      if (!valid()) return;
      this.clearTimer();
      this.audio.pause();
      this.error = message;
      this.changed();
    };
    const failed = () => fail('音声を読み込めませんでした。接続を確認して再試行してください。');
    const waiting = () => {
      if (valid() && !this.paused && !this.error) {
        this.clearTimer();
        this.timer = setTimeout(failed, 20000);
      }
    };
    const handlers = {
      playing: () => {
        if (!valid() || this.paused || this.error) return;
        this.clearTimer();
        entry.started = true;
        this.notice = '';
        this.currentSequence = entry.sequence;
        this.changed();
      },
      ended: () => {
        if (!valid() || !entry.started || this.error || this.paused) return;
        this.clearTimer();
        this.detach();
        // Replaying a cycle's final section must not count the cycle twice.
        if (entry.sequence % this.chunks.length === this.chunks.length - 1) {
          this.completedCycles.add(Math.floor(entry.sequence / this.chunks.length));
        }
        this.active = null;
        this.notice = '';
        this.pump();
        this.changed();
      },
      error: failed, waiting, stalled: waiting,
      timeupdate: () => {
        if (valid() && !this.paused && !this.error && !this.audio.paused
            && this.audio.currentTime > lastTime) {
          lastTime = this.audio.currentTime;
          this.clearTimer();
        }
      },
    };
    let lastTime = newSource ? 0 : this.audio.currentTime;
    for (const [event, handler] of Object.entries(handlers)) this.audio.addEventListener(event, handler);
    this.detach = () => {
      for (const [event, handler] of Object.entries(handlers)) this.audio.removeEventListener(event, handler);
    };
    if (newSource) {
      entry.started = false;
      entry.needsSource = false;
      this.audio.src = this.chunks[entry.sequence % this.chunks.length].audio;
      this.audio.load();
    }
    waiting();
    try {
      this.audio.play()?.catch((err) => fail(err.name === 'NotAllowedError'
        ? '音声の再生には操作が必要です。「音声を再試行」を押してください。'
        : '音声を再生できませんでした。再試行してください。'));
    } catch { failed(); }
  }

  togglePause() {
    if (this.error || (!this.active && !this.pending.length)) return;
    this.paused = !this.paused;
    this.notice = '';
    if (this.paused) {
      this.clearTimer();
      this.generation++;
      this.detach();
      this.audio.pause();
    } else if (this.active) this.playActive(Boolean(this.active.needsSource));
    else this.pump();
    this.changed();
  }

  retry() {
    if (!this.error || !this.active) return;
    this.error = '';
    this.notice = '';
    this.paused = false;
    this.playActive(true);
    this.changed();
  }

  clearTimer() { clearTimeout(this.timer); this.timer = null; }

  stopAudio() {
    this.generation++;
    this.clearTimer();
    this.detach();
    this.audio.pause();
    this.audio.removeAttribute('src');
    this.audio.load();
  }

  restart() {
    this.stopAudio();
    this.pending = [];
    this.active = null;
    this.nextSequence = 0;
    this.currentSequence = -1;
    this.turns = 0;
    this.angle = 0;
    this.paused = false;
    this.completedCycles.clear();
    this.error = '';
    this.notice = '';
    this.changed();
  }
}
