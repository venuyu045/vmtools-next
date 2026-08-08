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
const { WorldView } = require('prismarine-viewer');

module.exports = function startViewer(bot, options = {}) {
  const {
    viewDistance = 6,
    firstPerson = false,
    port = 3000,
    host = '0.0.0.0',
    prefix = '',
  } = options;

  const express = require('express');
  const app = express();
  const http = require('http').createServer(app);
  const io = require('socket.io')(http, { path: prefix + '/socket.io' });

  // 静态资源：prismarine-viewer 包内 public（webpack 构建的浏览器端）
  function setupRoutes(expressApp, routePrefix = '') {
    const pkgRoot = path.dirname(require.resolve('prismarine-viewer'));
    expressApp.use(compression());
    expressApp.use(routePrefix + '/', express.static(path.join(pkgRoot, 'public')));
  }
  setupRoutes(app, prefix);

  const sockets = [];
  const primitives = {};

  bot.viewer = new (require('events').EventEmitter)();

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
    socket.emit('version', bot.version);
    sockets.push(socket);

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
  });

  http.listen(port, host, () => {
    console.log(`[viewer] Prismarine viewer web server running on ${host}:${port}`);
  });

  bot.viewer.close = () => {
    try { http.close(); } catch (e) { /* ignore */ }
    for (const socket of sockets) {
      try { socket.disconnect(); } catch (e) { /* ignore */ }
    }
  };

  return bot.viewer;
};
