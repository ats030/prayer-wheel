import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const MIME_TYPES = {
  '.js': 'application/javascript',
  '.mjs': 'application/javascript',
  '.json': 'application/json',
  '.html': 'text/html',
  '.css': 'text/css',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

const server = http.createServer((req, res) => {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Expires', '0');

  let filePath = path.join(__dirname, '.' + req.url);
  if (req.url === '/' || req.url === '') {
    filePath = path.join(__dirname, 'index.html');
  }

  const ext = path.extname(filePath);
  let contentType = MIME_TYPES[ext] || 'text/plain';
  if (ext === '.js') {
    contentType = 'application/javascript; charset=utf-8';
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }

    res.writeHead(200, { 'Content-Type': contentType });
    res.end(content);
  });
});

server.listen(8525, '127.0.0.1', () => {
  console.log('Server running on http://127.0.0.1:8525 (no cache)');
});

