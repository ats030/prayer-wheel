// Adapted from Pillow 12.2.0 src/libImaging/Resample.c (MIT-CMU).
// Copyright © 1997-2011 Secret Labs AB; © 1995-2011 Fredrik Lundh and contributors;
// © 2010 Jeffrey 'Alex' Clark and contributors. See /vendor/photo/PILLOW-LICENSE.txt.
const precision = 2 ** 22;
function cubic(distance) {
  const x = Math.abs(distance);
  if (x < 1) return ((1.5*x-2.5)*x)*x+1;
  if (x < 2) return (((x-5)*x+8)*x-4)*-0.5;
  return 0;
}
function coefficients(input, output) {
  const scale = input/output, filterScale = Math.max(1, scale), support = 2*filterScale;
  return Array.from({length: output}, (_, index) => {
    const center = (index+0.5)*scale;
    const start = Math.max(0, Math.trunc(center-support+0.5));
    const end = Math.min(input, Math.trunc(center+support+0.5));
    const weights = Array.from({length: end-start}, (_, j) => cubic((j+start-center+0.5)/filterScale));
    const sum = weights.reduce((a,b) => a+b, 0);
    return {start, weights: weights.map(w => {
      const normalized = sum ? w/sum : w;
      return Math.trunc(normalized*precision+(normalized < 0 ? -0.5 : 0.5));
    })};
  });
}
const clip = sum => Math.max(0, Math.min(255, Math.floor(sum/precision)));
export function resizeGray(gray, width, height, outputWidth, outputHeight) {
  if (width === outputWidth && height === outputHeight) return gray;
  const horizontal = coefficients(width, outputWidth);
  const intermediate = new Uint8Array(outputWidth*height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < outputWidth; x++) {
      const {start, weights} = horizontal[x];
      let sum = precision/2;
      for (let j = 0; j < weights.length; j++) sum += gray[y*width+start+j]*weights[j];
      intermediate[y*outputWidth+x] = clip(sum);
    }
  }
  const vertical = coefficients(height, outputHeight);
  const output = new Uint8Array(outputWidth*outputHeight);
  for (let y = 0; y < outputHeight; y++) {
    const {start, weights} = vertical[y];
    for (let x = 0; x < outputWidth; x++) {
      let sum = precision/2;
      for (let j = 0; j < weights.length; j++) sum += intermediate[(start+j)*outputWidth+x]*weights[j];
      output[y*outputWidth+x] = clip(sum);
    }
  }
  return output;
}
