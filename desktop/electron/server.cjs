// Serves the built renderer and forwards /api to the PockPock backend, so the window has one
// loopback origin: the backend's same-PC check passes and no CORS is needed. Streams (SSE)
// are piped through unbuffered.
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.json': 'application/json',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
  '.map': 'application/json',
}

// Headers that would make the backend think the request came through a proxy from elsewhere.
const DROPPED_HEADERS = new Set(['x-forwarded-for', 'x-forwarded-host', 'x-real-ip', 'forwarded', 'connection'])

function proxy(request, response, backend) {
  const headers = {}
  for (const [key, value] of Object.entries(request.headers)) {
    if (!DROPPED_HEADERS.has(key.toLowerCase())) headers[key] = value
  }
  headers.host = `${backend.hostname}:${backend.port}`
  const upstream = http.request({
    hostname: backend.hostname,
    port: backend.port,
    method: request.method,
    path: request.url,
    headers,
  }, (reply) => {
    response.writeHead(reply.statusCode || 502, reply.headers)
    reply.pipe(response)
  })
  upstream.on('error', () => {
    if (!response.headersSent) {
      response.writeHead(502, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ detail: 'The PockPock backend is not running.' }))
    } else {
      response.destroy()
    }
  })
  // Closing the window or pressing Stop must abort the backend request too.
  response.on('close', () => { if (!response.writableFinished) upstream.destroy() })
  request.pipe(upstream)
}

function serveStatic(request, response, root) {
  let pathname = decodeURIComponent(new URL(request.url, 'http://local').pathname)
  if (pathname === '/') pathname = '/index.html'
  const file = path.resolve(root, `.${pathname}`)
  if (file !== root && !file.startsWith(root + path.sep)) {
    response.writeHead(403).end()
    return
  }
  fs.readFile(file, (error, data) => {
    if (error) {
      // Single-page app: unknown paths get the shell.
      fs.readFile(path.join(root, 'index.html'), (fallbackError, html) => {
        if (fallbackError) { response.writeHead(404).end('Not built. Run npm run build in desktop/.'); return }
        response.writeHead(200, { 'Content-Type': TYPES['.html'], 'Cache-Control': 'no-store' }).end(html)
      })
      return
    }
    response.writeHead(200, {
      'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': pathname === '/index.html' ? 'no-store' : 'public, max-age=31536000, immutable',
      'X-Content-Type-Options': 'nosniff',
    }).end(data)
  })
}

/** Starts the server on 127.0.0.1. Tries `preferredPort` first so browser storage stays stable. */
function startServer({ root, backendUrl, preferredPort }) {
  const backend = new URL(backendUrl)
  const resolvedRoot = path.resolve(root)
  const server = http.createServer((request, response) => {
    if (request.url && request.url.startsWith('/api/')) proxy(request, response, backend)
    else if (request.method === 'GET' || request.method === 'HEAD') serveStatic(request, response, resolvedRoot)
    else response.writeHead(405).end()
  })
  return new Promise((resolve, reject) => {
    const listen = (port) => {
      server.once('error', (error) => {
        if (port !== 0 && error.code === 'EADDRINUSE') listen(0)
        else reject(error)
      })
      server.listen(port, '127.0.0.1', () => resolve({ server, port: server.address().port }))
    }
    listen(preferredPort)
  })
}

module.exports = { startServer }
