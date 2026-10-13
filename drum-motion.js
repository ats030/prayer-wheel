// A critically damped angular spring: the selected face attracts the drum,
// while friction dissipates its velocity. Exact integration avoids frame-rate drift.
export function advanceMotion({ angle, velocity }, target, seconds) {
  const frequency = 8;
  const displacement = angle - target;
  const momentum = velocity + frequency * displacement;
  const decay = Math.exp(-frequency * seconds);
  return {
    angle: target + (displacement + momentum * seconds) * decay,
    velocity: (velocity - frequency * momentum * seconds) * decay,
  };
}

export class DrumMotion {
  constructor(element, initialAngle) {
    this.element = element;
    this.reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
    this.reducedMotion.addEventListener('change', () => {
      if (this.reducedMotion.matches) this.snap(this.target);
    });
    this.snap(initialAngle);
  }

  draw() {
    this.element.style.setProperty('--drum-turn', `${this.angle}deg`);
    this.onDraw?.();
  }

  snap(angle) {
    cancelAnimationFrame(this.frame);
    this.frame = null;
    this.lastTime = null;
    this.target = this.angle = angle;
    this.velocity = 0;
    this.element.dataset.moving = 'false';
    this.draw();
  }

  moveTo(target) {
    this.target = target;
    if (this.reducedMotion.matches) return this.snap(target);
    if (this.frame !== null || this.angle === target && this.velocity === 0) return;
    this.element.dataset.moving = 'true';
    this.lastTime = performance.now();
    this.frame = requestAnimationFrame(time => this.tick(time));
  }

  tick(time) {
    Object.assign(this, advanceMotion(this, this.target, Math.max(0, (time - this.lastTime) / 1000)));
    this.lastTime = time;
    if (Math.abs(this.angle - this.target) < .03 && Math.abs(this.velocity) < .1) {
      return this.snap(this.target);
    }
    this.draw();
    this.frame = requestAnimationFrame(next => this.tick(next));
  }
}
