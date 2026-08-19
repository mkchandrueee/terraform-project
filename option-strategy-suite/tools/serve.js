#!/usr/bin/env node
/* Static file server for the suite. Zero dependencies, so Node alone is enough
 * on any platform — no Python, no npx download.
 *
 *   node tools/serve.js            → http://127.0.0.1:8787
 *   node tools/serve.js 3000       → another port
 *   node tools/serve.js 8787 lan   → also reachable from your phone on the same wifi
 */

'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const PORT = Number(process.argv[2]) || 8787;
const LAN = (process.argv[3] || '').toLowerCase() === 'lan';
const HOST = LAN ? '0.0.0.0' : '127.0.0.1';
const ROOT = path.resolve(__dirname, '..');

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.md': 'text/markdown; charset=utf-8'
};

function lanAddress() {
  const nets = os.networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name] || []) {
      if (net.family === 'IPv4' && !net.internal) return net.address;
    }
  }
  return null;
}

const server = http.createServer((req, res) => {
  let pathname;
  try {
    /* Strip the query, then decode. Not `new URL(req.url, base)`: a request
       path beginning with "//" is protocol-relative to that parser and throws,
       so "//" would 400 instead of serving the page. */
    pathname = decodeURIComponent((req.url || '/').split(/[?#]/)[0]);
  } catch (e) {
    res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' }).end('bad request');
    return;
  }

  pathname = '/' + pathname.replace(/^\/+/, '');
  if (pathname.endsWith('/')) pathname += 'index.html';

  /* Resolve, then confirm the result is still inside ROOT — blocks ../ escapes. */
  const filePath = path.resolve(ROOT, '.' + pathname);
  if (filePath !== ROOT && !filePath.startsWith(ROOT + path.sep)) {
    res.writeHead(403).end('forbidden');
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('404 — ' + pathname);
      return;
    }
    res.writeHead(200, {
      'Content-Type': TYPES[path.extname(filePath).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': 'no-cache'
    });
    res.end(data);
  });
});

server.listen(PORT, HOST, () => {
  console.log('NIFTY Option Strategy Suite');
  console.log('  serving   ' + ROOT);
  console.log('  open      http://127.0.0.1:' + PORT);
  if (LAN) {
    const ip = lanAddress();
    if (ip) console.log('  on wifi   http://' + ip + ':' + PORT);
  }
  console.log('  stop      Ctrl+C');
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`Port ${PORT} is already in use. Try: node tools/serve.js ${PORT + 1}`);
  } else {
    console.error(err.message);
  }
  process.exit(1);
});
