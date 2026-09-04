/**
 * VOICEVOX API Client for Audio Generation
 * Generates audio files for game texts using VOICEVOX Engine
 */

const fs = require('fs');
const path = require('path');

// Configuration
const VOICEVOX_HOST = 'http://127.0.0.1';
const VOICEVOX_PORT = 50021;
const BASE_URL = `${VOICEVOX_HOST}:${VOICEVOX_PORT}`;
const OUTPUT_DIR = '/home/ats030/app/dekita/audio';

// Audio configurations
const AUDIO_FILES = [
  { filename: 'color-question.mp3', text: 'これ なん の いろかな？', speaker: 0 },
  { filename: 'match-instruction.mp3', text: 'ペアを見つけてね', speaker: 0 },
  { filename: 'maze-hachi.mp3', text: 'はちさんが おはなまで いけるかな？', speaker: 0 },
  { filename: 'maze-usagi.mp3', text: 'うさぎさんが にんじんまで いけるかな？', speaker: 0 },
  { filename: 'maze-neko.mp3', text: 'ねこさんが おさかなまで いけるかな？', speaker: 0 },
  { filename: 'maze-saru.mp3', text: 'さるさんが バナナまで いけるかな？', speaker: 0 },
  { filename: 'maze-win10.mp3', text: 'やったー！10てん！', speaker: 0 },
];

// Retry configuration
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;
const REQUEST_DELAY_MS = 500;

// Logging helpers
const log = {
  info: (msg) => console.log(`[INFO] ${msg}`),
  success: (msg) => console.log(`[SUCCESS] ${msg}`),
  error: (msg) => console.error(`[ERROR] ${msg}`),
  progress: (current, total, msg) => console.log(`[PROGRESS] ${current}/${total}: ${msg}`),
};

// Ensure output directory exists
function ensureOutputDir() {
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    log.info(`Created output directory: ${OUTPUT_DIR}`);
  }
}

// Check if VOICEVOX engine is accessible
async function checkEngine() {
  try {
    const response = await fetch(`${BASE_URL}/version`, { method: 'GET' });
    if (!response.ok) {
      throw new Error(`Engine returned status ${response.status}`);
    }
    const data = await response.json();
    log.info(`VOICEVOX Engine is running: ${JSON.stringify(data)}`);
    return true;
  } catch (error) {
    log.error(`Failed to connect to VOICEVOX Engine: ${error.message}`);
    return false;
  }
}

// Convert text to kana or audio using VOICEVOX API
async function generateAudio(text, speaker = 0, retryCount = 0) {
  try {
    // Step 1: Acquire phonemes (QST)
    const qstResponse = await fetch(`${BASE_URL}/audio_query?speaker=${speaker}&text=${encodeURIComponent(text)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!qstResponse.ok) {
      throw new Error(`Audio query failed: ${qstResponse.status} ${qstResponse.statusText}`);
    }

    const audioQuery = await qstResponse.json();

    // Step 2: Generate audio from query
    const audioResponse = await fetch(`${BASE_URL}/synthesis?speaker=${speaker}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(audioQuery),
    });

    if (!audioResponse.ok) {
      throw new Error(`Synthesis failed: ${audioResponse.status} ${audioResponse.statusText}`);
    }

    // Convert response to ArrayBuffer
    const audioBuffer = await audioResponse.arrayBuffer();
    return Buffer.from(audioBuffer);

  } catch (error) {
    if (retryCount < MAX_RETRIES) {
      log.info(`Retry ${retryCount + 1}/${MAX_RETRIES} for: ${text}`);
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
      return generateAudio(text, speaker, retryCount + 1);
    }
    throw error;
  }
}

// Save audio buffer to file
function saveToFile(buffer, filename) {
  const filePath = path.join(OUTPUT_DIR, filename);
  fs.writeFileSync(filePath, buffer);
  return filePath;
}

// Main execution
async function main() {
  log.info('VOICEVOX Audio Generation Script Started');
  console.log('---');

  // Check engine first
  if (!await checkEngine()) {
    log.error('Cannot proceed without VOICEVOX Engine');
    process.exit(1);
  }

  ensureOutputDir();

  const stats = {
    total: AUDIO_FILES.length,
    succeeded: 0,
    failed: 0,
    failedFiles: [],
  };

  console.log(`\nGenerating ${stats.total} audio files...\n`);

  for (let i = 0; i < AUDIO_FILES.length; i++) {
    const fileConfig = AUDIO_FILES[i];
    const { filename, text, speaker } = fileConfig;

    log.progress(i + 1, stats.total, `Processing: ${filename} (${text})`);

    try {
      // Add delay between requests (except first one)
      if (i > 0) {
        await new Promise((resolve) => setTimeout(resolve, REQUEST_DELAY_MS));
      }

      const audioBuffer = await generateAudio(text, speaker);

      const filePath = saveToFile(audioBuffer, filename);
      const fileSize = (audioBuffer.byteLength / 1024).toFixed(2);

      log.success(`Generated: ${filename} (${fileSize} KB)`);
      stats.succeeded++;

    } catch (error) {
      log.error(`Failed to generate: ${filename} - ${error.message}`);
      stats.failed++;
      stats.failedFiles.push({ filename, text, error: error.message });
    }
  }

  // Print summary
  console.log('\n---');
  console.log(' Generation Summary ');
  console.log('---------------------');
  console.log(`Total:   ${stats.total}`);
  console.log(`Succeeded: ${stats.succeeded}`);
  console.log(`Failed:    ${stats.failed}`);
  console.log(`Output:    ${OUTPUT_DIR}`);

  if (stats.failedFiles.length > 0) {
    console.log('\nFailed files:');
    stats.failedFiles.forEach((f) => console.log(`  - ${f.filename}: ${f.error}`));
    process.exit(1);
  }

  log.info('All audio files generated successfully!');
}

// Run main
main().catch((error) => {
  log.error(`Unexpected error: ${error.message}`);
  process.exit(1);
});
