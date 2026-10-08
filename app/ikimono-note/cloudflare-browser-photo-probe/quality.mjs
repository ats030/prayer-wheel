import {resizeGray} from './resample.mjs';
import {roundOneDecimal} from './round.mjs';
// Local experiment: preserve the Canvas baseline to measure the regression.
export function judgeCanvas(canvas, usePillowResize = true) {
  const {width, height} = canvas;
  const rgba = canvas.getContext('2d', {willReadFrequently: true})
    .getImageData(0, 0, width, height).data;
  const gray = new Uint8ClampedArray(width * height);
  let total = 0, squares = 0;
  for (let i = 0; i < gray.length; i++) {
    // Pillow's fixed-point RGB -> L conversion, including rounding.
    const value = (rgba[4*i]*19595 + rgba[4*i+1]*38470 + rgba[4*i+2]*7471 + 32768) >> 16;
    gray[i] = value;
    total += value;
    squares += value * value;
  }
  const scale = Math.min(1, 320 / Math.max(width, height));
  const smallWidth = Math.max(1, Math.floor(width * scale));
  const smallHeight = Math.max(1, Math.floor(height * scale));
  let data;
  if (usePillowResize) {
    data = resizeGray(gray, width, height, smallWidth, smallHeight);
  } else {
    const source = document.createElement('canvas');
    source.width = width; source.height = height;
    const ctx = source.getContext('2d');
    const pixels = ctx.createImageData(width, height);
    for (let i = 0; i < gray.length; i++) pixels.data.set([gray[i], gray[i], gray[i], 255], i*4);
    ctx.putImageData(pixels, 0, 0);
    const small = document.createElement('canvas');
    small.width = smallWidth; small.height = smallHeight;
    const smallContext = small.getContext('2d');
    smallContext.imageSmoothingQuality = 'high';
    smallContext.drawImage(source, 0, 0, smallWidth, smallHeight);
    data = smallContext.getImageData(0, 0, smallWidth, smallHeight).data.filter((_, i) => i % 4 === 0);
  }
  let lapTotal = 0, lapSquares = 0, count = 0;
  for (let y = 1; y < smallHeight-1; y++) {
    for (let x = 1; x < smallWidth-1; x++) {
      const i = y*smallWidth+x;
      const value = 4*data[i] - data[i-1] - data[i+1]
        - data[i-smallWidth] - data[i+smallWidth];
      lapTotal += value; lapSquares += value*value; count++;
    }
  }
  const brightness = total / gray.length;
  const round = roundOneDecimal;
  const measured = {width, height, pixels: width*height,
    sharpness: round(count ? Math.max(0, lapSquares/count-(lapTotal/count)**2) : 0),
    brightness: round(brightness),
    contrast: round(Math.sqrt(Math.max(0, squares/gray.length-brightness**2)))};
  const edge = Math.min(width, height), problems = [];
  if (edge < 200) problems.push({level: 'block', reason: 'small'});
  else if (edge < 300) problems.push({level: 'warn', reason: 'small'});
  if (measured.brightness < 15) problems.push({level: 'block', reason: 'dark'});
  else if (measured.brightness < 25) problems.push({level: 'warn', reason: 'dark'});
  if (edge >= 200 && measured.sharpness < 50) problems.push({level: 'warn', reason: 'blurry'});
  if (measured.contrast < 10) problems.push({level: 'warn', reason: 'flat'});
  const blocked = problems.some(problem => problem.level === 'block');
  return {ok: !blocked, level: blocked ? 'block' : problems.length ? 'warn' : '', problems, measured};
}
