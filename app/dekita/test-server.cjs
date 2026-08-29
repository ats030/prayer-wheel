const http = require('http');

http.createServer((req, res) => res.end('OK')).listen(8525, '0.0.0.0', () => {
  console.log('Server running on 0.0.0.0:8525');
  console.log('Server PID:', process.pid);
});
