// Match Python round(value, 1) on the actual binary64 value, including ties.
// Multiplying a Number by ten first can itself round across a decimal boundary.
export function roundOneDecimal(value) {
  if (!Number.isFinite(value)) throw new Error('Expected finite quality metric');
  const storage = new DataView(new ArrayBuffer(8));
  storage.setFloat64(0, Math.abs(value));
  const bits = storage.getBigUint64(0);
  const exponent = Number((bits >> 52n) & 2047n);
  let numerator = bits & ((1n << 52n)-1n);
  if (exponent) numerator += 1n << 52n;
  const power = (exponent || 1)-1023-52;
  numerator *= 10n;
  let denominator = 1n;
  if (power >= 0) numerator <<= BigInt(power);
  else denominator <<= BigInt(-power);
  let rounded = numerator / denominator;
  const remainder = numerator % denominator;
  if (remainder*2n > denominator || (remainder*2n === denominator && rounded%2n)) rounded++;
  return (value < 0 ? -1 : 1)*Number(rounded)/10;
}
