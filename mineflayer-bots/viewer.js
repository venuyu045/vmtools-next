/**
 * viewer.js — prismarine-viewer 实时 3D 查看器集成模块
 *
 * 为单个 mineflayer bot 启动实时 3D 查看器（浏览器端渲染 bot 周围世界）。
 * 逻辑对齐官方 prismarine-viewer/lib/mineflayer.js，但额外支持：
 *   - host 绑定（生产建议 127.0.0.1，经 vmtools FastAPI 反代访问，防公网无鉴权暴露）
 *   - prefix 路径前缀（反代挂载用，如 /viewer/mf-006/）
 *
 * 用法：
 *   const startViewer = require('./viewer');
 *   startViewer(bot, { port: 3007, host: '0.0.0.0', firstPerson: false, viewDistance: 6 });
 *   // 停止：bot.viewer.close()
 */
const path = require('path');
const compression = require('compression');
// WorldView 在 prismarine-viewer 的 viewer 子模块导出（顶层没有，官方写法 require('../viewer')）
const { WorldView } = require('prismarine-viewer').viewer;

// ── viewer 登录鉴权（2026-08-09 新增） ────────────────────────────────
// 后端在启动 bot 时注入 VMT_VIEWER_SECRET（= server.secret_key）；未设置时视为
// 本地开发模式，跳过鉴权（保持向后兼容）。
// 鉴权流程：前端 iframe 打开 /viewer/?t=<后端签发的 aud=viewer JWT> →
// 页面入口校验通过后种 HttpOnly cookie（viewer_token）→ iframe 内静态资源与
// socket.io 连接自动携带 cookie → socket.io 中间件校验 cookie 放行（世界数据防线）。
const VIEWER_SECRET = process.env.VMT_VIEWER_SECRET || '';
const VIEWER_COOKIE = 'viewer_token';
const VIEWER_TOKEN_TTL_MS = 10 * 60 * 1000; // 与后端签发有效期一致（10 分钟）

function verifyViewerToken (token) {
  if (!VIEWER_SECRET || !token) return false;
  try {
    const jwt = require('jsonwebtoken');
    jwt.verify(token, VIEWER_SECRET, { audience: 'viewer' });
    return true;
  } catch (e) {
    return false;
  }
}

function parseCookies (header) {
  const out = {};
  for (const part of String(header || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) {
      try {
        out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
      } catch (e) { /* ignore bad cookie */ }
    }
  }
  return out;
}

// ── 服务端预渲染（2026-08-09 方案②）────────────────────────────────────
// 用 worker_threads 跑「打包的 worker.js」（与浏览器端同一套渲染代码），
// 提前计算 bot 周围核心区的 section geometry 并缓存（LRU）。
// 浏览器连接时把缓存推给它（useGeometry），浏览器 worker 直接用、跳过本地计算
// → 多人打开秒见核心区（2 核 2G 服务器：LRU 上限 ~512 section ≈ 50-100MB 可承受）。
const fs = require('fs');
const { Worker } = require('worker_threads');
const prerenderCache = new Map(); // key = `${x},${y},${z}`（section 起点，16 倍数）→ geometry
const PRERENDER_MAX_SECTIONS = 512;
let prerenderWorker = null;
let prerenderBs = null;

function initPrerender (pkgRoot) {
  if (prerenderWorker) return;
  try {
    prerenderBs = JSON.parse(fs.readFileSync(path.join(pkgRoot, 'public/blocksStates/26.1.json'), 'utf8'));
    prerenderWorker = new Worker(path.join(pkgRoot, 'public/worker.js'));
    // 关键：worker 线程任何错误必须捕获，否则 Node 会崩整个 bot 进程（历史教训）
    prerenderWorker.on('error', (err) => {
      console.error('[viewer] prerender worker error:', err && err.message);
      prerenderWorker = null;
    });
    prerenderWorker.on('exit', (code) => {
      if (code !== 0) console.error('[viewer] prerender worker exited:', code);
      prerenderWorker = null;
    });
    prerenderWorker.on('message', (msg) => {
      if (msg && msg.type === 'geometry' && msg.geometry) {
        prerenderCache.set(msg.key, msg.geometry);
        while (prerenderCache.size > PRERENDER_MAX_SECTIONS) {
          prerenderCache.delete(prerenderCache.keys().next().value); // 淘汰最旧（LRU 近似）
        }
      }
    });
    prerenderWorker.postMessage({ type: 'version', version: '26.1' });
    prerenderWorker.postMessage({ type: 'blockStates', json: prerenderBs });
    console.log('[viewer] prerender worker initialized');
  } catch (err) {
    console.error('[viewer] prerender init failed:', err);
    prerenderWorker = null;
  }
}

function prerenderChunk (x, z, chunkJson) {
  if (!prerenderWorker || !chunkJson) return;
  try {
    prerenderWorker.postMessage({ type: 'chunk', x, z, chunk: chunkJson });
    // 标记该 chunk 所有 y 层 section dirty（worker 会自动跳过不存在的 section）
    for (let sy = 0; sy < 384; sy += 16) {
      prerenderWorker.postMessage({ type: 'dirty', x, y: sy, z, value: true });
    }
  } catch (err) { /* 预渲染失败不影响 viewer 主流程 */ }
}

module.exports = function startViewer(bot, options = {}) {
  const {
    viewDistance = 6,
    firstPerson = false,
    port = 3000,
    host = '0.0.0.0',
    prefix = '',
  } = options;

  const pkgRoot = path.dirname(require.resolve('prismarine-viewer'));
  const express = require('express');
  const app = express();
  const http = require('http').createServer(app);
  const io = require('socket.io')(http, { path: prefix + '/socket.io' });

  // 静态资源：prismarine-viewer 包内 public（webpack 构建的浏览器端）
  function setupRoutes(expressApp, routePrefix = '') {
    expressApp.use(compression());
    // 页面入口鉴权：GET {prefix}/ 校验 ?t=<viewer-token> 或 cookie，
    // 通过后种 HttpOnly cookie（iframe 内静态资源与 socket.io 自动携带）。
    // 仅精确匹配入口路径；index.js/worker.js 等静态资源是公开 MC 资产，
    // 世界数据走 socket.io（其握手单独校验），因此无需逐资源拦截。
    if (VIEWER_SECRET) {
      expressApp.get(routePrefix + '/', (req, res, next) => {
        const token = req.query.t || parseCookies(req.headers.cookie)[VIEWER_COOKIE] || '';
        if (verifyViewerToken(token)) {
          try {
            res.cookie(VIEWER_COOKIE, token, {
              httpOnly: true,
              sameSite: 'lax',
              maxAge: VIEWER_TOKEN_TTL_MS,
              path: routePrefix || '/',
            });
          } catch (e) { /* cookie 设置失败不阻塞页面 */ }
          return next();
        }
        return res.status(401).type('text/plain').send('Unauthorized: 请先登录 vmtools 后打开预览');
      });
    }
    // 强制 no-cache：worker.js / blocksStates/*.json / textures/*.png 等大文件更新后，
    // 浏览器必须重新拉取，避免旧缓存导致「方块缺失/紫色」误判（历史教训见交接文档 3.13）
    expressApp.use(routePrefix + '/', express.static(path.join(pkgRoot, 'public'), {
      setHeaders: (res) => {
        res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
        res.setHeader('Pragma', 'no-cache');
        res.setHeader('Expires', '0');
      }
    }));
  }
  setupRoutes(app, prefix);

  // socket.io 握手鉴权：世界数据经此通道推送，必须校验 cookie 里的 viewer token
  if (VIEWER_SECRET) {
    io.use((socket, next) => {
      const cookies = parseCookies(socket.handshake.headers.cookie || '');
      if (verifyViewerToken(cookies[VIEWER_COOKIE] || '')) {
        return next();
      }
      return next(new Error('unauthorized: viewer token missing or invalid'));
    });
  }

  const sockets = [];
  const primitives = {};

  bot.viewer = new (require('events').EventEmitter)();

  // ── 服务端预渲染：独立小范围 WorldView（不连浏览器），loadChunk 时预渲染 geometry ──
  // 只算 bot 周围核心区（viewDistance 取 min(配置,2)≈5×5 chunk），LRU 缓存上限见 PRERENDER_MAX_SECTIONS
  const prerenderEmitter = new (require('events').EventEmitter)();
  let prerenderWorldView = null;
  try {
    prerenderWorldView = new WorldView(bot.world, Math.min(viewDistance, 2), bot.entity.position, prerenderEmitter);
    prerenderEmitter.on('loadChunk', ({ x, z, chunk }) => prerenderChunk(x, z, chunk));
    prerenderWorldView.init(bot.entity.position).catch(() => {});
    initPrerender(pkgRoot);
    // 预渲染位置跟随 bot（独立于浏览器连接，close 时移除）
    const onMove = () => { if (prerenderWorldView) prerenderWorldView.updatePosition(bot.entity.position); };
    bot.on('move', onMove);
    bot.viewer.prerenderCleanup = () => { bot.removeListener('move', onMove); };
    console.log('[viewer] prerender WorldView active');
  } catch (err) {
    console.error('[viewer] prerender WorldView init failed:', err);
  }


  bot.viewer.erase = (id) => {
    delete primitives[id];
    for (const socket of sockets) {
      socket.emit('primitive', { id });
    }
  };

  bot.viewer.drawBoxGrid = (id, start, end, color = 'aqua') => {
    primitives[id] = { type: 'boxgrid', id, start, end, color };
    for (const socket of sockets) {
      socket.emit('primitive', primitives[id]);
    }
  };

  bot.viewer.drawLine = (id, points, color = 0xff0000) => {
    primitives[id] = { type: 'line', id, points, color };
    for (const socket of sockets) {
      socket.emit('primitive', primitives[id]);
    }
  };

  bot.viewer.drawPoints = (id, points, color = 0xff0000, size = 5) => {
    primitives[id] = { type: 'points', id, points, color, size };
    for (const socket of sockets) {
      socket.emit('primitive', primitives[id]);
    }
  };

  io.on('connection', (socket) => {
    // 单连接初始化异常不得拖垮整个 bot 进程（历史教训：未捕获异常 → 进程崩溃 → 循环重启）
    try {
      socket.emit('version', bot.version);
      sockets.push(socket);

      // 推送服务端预渲染的 core 区 geometry（浏览器 worker 直接用，跳过本地计算）
      // 2026-08-09：preRendered 声明缺失已修复（2e5c554），重新启用
      for (const [key, geometry] of prerenderCache) {
        socket.emit('useGeometry', { key, geometry });
      }

      const worldView = new WorldView(bot.world, viewDistance, bot.entity.position, socket);
      worldView.init(bot.entity.position);

      worldView.on('blockClicked', (block, face, button) => {
        bot.viewer.emit('blockClicked', block, face, button);
      });

      for (const id in primitives) {
        socket.emit('primitive', primitives[id]);
      }

      function botPosition() {
        const packet = { pos: bot.entity.position, yaw: bot.entity.yaw, addMesh: true };
        if (firstPerson) {
          packet.pitch = bot.entity.pitch;
        }
        socket.emit('position', packet);
        worldView.updatePosition(bot.entity.position);
      }

      bot.on('move', botPosition);
      worldView.listenToBot(bot);
      socket.on('disconnect', () => {
        bot.removeListener('move', botPosition);
        worldView.removeListenersFromBot(bot);
        sockets.splice(sockets.indexOf(socket), 1);
      });
    } catch (err) {
      console.error('[viewer] connection handler error:', err);
      try { socket.disconnect(true); } catch (e) { /* ignore */ }
    }
  });

  http.listen(port, host, () => {
    console.log(`[viewer] Prismarine viewer web server running on ${host}:${port}`);
  });

  bot.viewer.close = () => {
    try { if (bot.viewer.prerenderCleanup) bot.viewer.prerenderCleanup(); } catch (e) { /* ignore */ }
    try { if (prerenderWorker) prerenderWorker.terminate(); } catch (e) { /* ignore */ }
    prerenderWorker = null;
    try { http.close(); } catch (e) { /* ignore */ }
    for (const socket of sockets) {
      try { socket.disconnect(); } catch (e) { /* ignore */ }
    }
  };

  return bot.viewer;
};
