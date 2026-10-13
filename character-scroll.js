// The spoken glyph is nearest the center throughout its voiced interval.
// Adjacent intervals meet halfway between rows, including section boundaries.
export function characterPosition(cues, seconds, reducedMotion = false) {
  let index = 0;
  while (index + 1 < cues.length && cues[index + 1].start <= seconds) index++;
  const cue = cues[index];
  const progress = Math.max(0, Math.min(1, (seconds - cue.start) / (cue.end - cue.start)));
  return { index, position: reducedMotion ? index : index - .5 + progress };
}
