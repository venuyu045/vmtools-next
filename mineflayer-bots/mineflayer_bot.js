/**
 * mineflayer_bot.js — 核心 bot 模块
 *
 * 创建 mineflayer bot + WebSocket 服务器，处理消息分发和事件推送。
 *
 * 用法：
 *   const { createBotProcess } = require('./mineflayer_bot');
 *   const botProcess = await createBotProcess(options);
 *   await botProcess.start();
 */

const mineflayer = require('mineflayer');
const { WebSocketServer } = require('ws');
const { v4: uuidv4 } = require('uuid');

const { createMovementHandlers } = require('./handlers/movement');
const { createBlockHandlers } = require('./handlers/blocks');
const { createInventoryHandlers } = require('./handlers/inventory');
const { createWorldHandlers } = require('./handlers/world');
const { createChatHandlers } = require('./handlers/chat');
const {
  createSuccessResponse,
  createErrorResponse,
  createEvent,
  createStatusUpdate,
} = require('./ws_protocol');

// ── 方法 → handler 映射 ──
const METHOD_MAP = Symbol('methodMap');

/**
 * 创建并启动一个 mineflayer bot 实例。
 * @param {object} options
 * @param {number} options.wsPort        — WebSocket 服务器端口
 * @param {string} options.mcHost        — Minecraft 服务器地址
 * @param {number} options.mcPort        — Minecraft 服务器端口
 * @param {string} options.username      — Bot 用户名
 * @param {string} [options.password]    — 密码（正版登录）
 * @param {'offline'|'microsoft'|'yggdrasil'} [options.auth='offline'] — 认证方式
 * @param {string} [options.authServerUrl] — Yggdrasil 认证服务器 URL（auth='yggdrasil' 时必填）
 * @param {string} [options.version='1.21.11'] — Minecraft 版本
 * @param {number} [options.statusInterval=5000] — 状态推送间隔 (ms)
 * @returns {Promise<object>} { bot, wss, stop, onEvent }
 */
async function createBotProcess(options) {
  const {
    wsPort,
    mcHost = '127.0.0.1',
    mcPort = 25565,
    username = 'VMBot',
    password = '',
    auth = 'offline',
    version = '1.21.11',
    statusInterval = 5000,
  } = options;

  // ── 1. 创建 mineflayer bot ──
  const botOpts = {
    host: mcHost,
    port: mcPort,
    username,
    version,
    hideErrors: false,
    logErrors: true,
    respawn: true,
  };

  // ── 认���方式处理 ──
  if (auth === 'yggdrasil') {
    const authServerUrl = options.authServerUrl || process.env.AUTH_SERVER_URL || '';
    if (!authServerUrl) {
      throw new Error('auth=yggdrasil 但未设置 authServerUrl 或 AUTH_SERVER_URL');
    }
    const root = authServerUrl.replace(/\/+$/, '');
    botOpts.auth = 'mojang';                        // 触发 yggdrasil auth 流程
    botOpts.authServer = root + '/authserver';      // → POST {root}/authserver/authenticate
    botOpts.sessionServer = root + '/sessionserver'; // → POST {root}/sessionserver/session/minecraft/join
    botOpts.profilesFolder = false;                  // 不存本地 launcher 配置
    if (password) botOpts.password = password;
  } else if (auth === 'offline' && password) {
    botOpts.auth = 'offline';
    // mineflayer 离线模式忽略 password
  } else if (password) {
    botOpts.auth = 'mojang';
    botOpts.password = password;
  } else {
    botOpts.auth = auth || 'offline';
  }

  // ── 2. 创建 WebSocket 服务器 ──
  const wss = new WebSocketServer({ port: wsPort });

  // 事件回调列表
  const eventListeners = new Set();

  // ── 3. 方法路由表 ──
  const methodMap = {};

  // 存储 bot 引用和 handler 引用
  let bot = null;
  let handlers = null;
  let statusTimer = null;
  let isStopping = false;

  // ── 核心函数: 处理 WS 消息 ──
  function handleWsMessage(ws, raw) {
    let msg;
    try {
      msg = JSON.parse(raw.toString());
    } catch {
      return;
    }

    if (msg.type === 'request') {
      handleRequest(ws, msg);
    }
    // 忽略 type: 'ping' 等（WS 层自动处理心跳）
  }

  async function handleRequest(ws, request) {
    const { request_id, method, params = {} } = request;
    if (!method) {
      ws.send(JSON.stringify(createErrorResponse(request_id, 'No method specified')));
      return;
    }

    const handler = methodMap[method];
    if (!handler) {
      ws.send(JSON.stringify(createErrorResponse(request_id, `Unknown method: ${method}`)));
      return;
    }

    try {
      const result = await handler(params);
      ws.send(JSON.stringify(createSuccessResponse(request_id, result)));
    } catch (err) {
      ws.send(JSON.stringify(createErrorResponse(request_id, err.message)));
    }
  }

  // ── 注册方法到路由表 ──
  function registerMethods(prefix, handlerObj) {
    for (const [methodName, fn] of Object.entries(handlerObj)) {
      methodMap[methodName] = fn;
    }
  }

  // ── 创建 bot ──
  return new Promise((resolve, reject) => {
    bot = mineflayer.createBot(botOpts);

    // ── 事件绑定 ──
    bot.once('inject_allowed', () => {
      // 加载 pathfinder
      const { setupPathfinder } = require('./pathfinder_setup');
      try {
        setupPathfinder(bot);
      } catch (err) {
        console.error('[pathfinder] setup failed:', err.message);
      }
    });

    bot.on('spawn', () => {
      console.log('[bot] spawned at', bot.entity.position);
      broadcast(createEvent('bot_spawned', {
        position: {
          x: bot.entity.position.x,
          y: bot.entity.position.y,
          z: bot.entity.position.z,
        },
      }));
    });

    bot.on('death', () => {
      console.log('[bot] died');
      broadcast(createEvent('bot_death', {}));
    });

    bot.on('kicked', (reason) => {
      console.log('[bot] kicked:', reason);
      broadcast(createEvent('bot_kicked', { reason: String(reason) }));
    });

    bot.on('error', (err) => {
      console.error('[bot] error:', err.message);
      broadcast(createEvent('bot_error', { error: err.message }));
    });

    bot.on('end', (reason) => {
      console.log('[bot] disconnected:', reason);
      broadcast(createEvent('bot_disconnected', { reason }));
      // 不在这里 stop WS，让进程管理器处理重启
    });

    bot.on('chat', (username, message) => {
      if (username !== bot.username) {
        broadcast(createEvent('bot_chat', { username, message }));
      }
    });

    bot.on('playerJoined', (player) => {
      broadcast(createEvent('player_joined', { username: player.username }));
    });

    bot.on('playerLeft', (player) => {
      broadcast(createEvent('player_left', { username: player.username }));
    });

    bot.on('health', () => {
      // 生命值变化，状态推送会在定时器中覆盖
    });

    // ── 连接成功 ──
    bot.once('login', () => {
      console.log('[bot] logged in as', bot.username);

      // ── 4. 创建 handlers 并注册 ──
      handlers = {
        ...createMovementHandlers(bot),
        ...createBlockHandlers(bot),
        ...createInventoryHandlers(bot),
        ...createWorldHandlers(bot),
        ...createChatHandlers(bot),
      };

      // 注册所有方法
      for (const [name, fn] of Object.entries(handlers)) {
        methodMap[name] = fn;
      }

      // ── 5. 启动 WebSocket 服务器 ──
      wss.on('connection', (ws) => {
        ws.on('message', (data) => handleWsMessage(ws, data));
        ws.on('close', () => { /* 不处理，用 ping 检测存活 */ });
        ws.on('error', () => { /* 忽略 */ });

        // 发送连接成功消息
        ws.send(JSON.stringify(createEvent('bot_ready', {
          username: bot.username,
          ws_port: wsPort,
        })));
      });

      // ── 6. 启动状态推送定时器 ──
      statusTimer = setInterval(() => {
        broadcast(createStatusUpdate(bot));
      }, statusInterval);

      console.log(`[ws] WebSocket server listening on port ${wsPort}`);
      console.log(`[bot] connected to ${mcHost}:${mcPort} as ${bot.username}`);

      resolve({
        bot,
        wss,
        methodMap,
        broadcast,
        stop: () => stopBotProcess(bot, wss, statusTimer),
        onEvent: (cb) => eventListeners.add(cb),
      });
    });

    // ── 连接失败 ──
    bot.on('error', (err) => {
      reject(new Error(`Bot failed to connect: ${err.message}`));
    });

    // 超时处理
    setTimeout(() => {
      if (!bot?.username) {
        bot.end?.(new Error('Connection timeout'));
        reject(new Error('Bot connection timeout'));
      }
    }, 30000);
  });

  // ── 广播消息到所有 WebSocket 客户端 ──
  function broadcast(data) {
    const json = JSON.stringify(data);
    for (const ws of wss.clients) {
      if (ws.readyState === 1) { // WebSocket.OPEN
        ws.send(json);
      }
    }
  }
}

// ── 停止 bot 进程 ──
async function stopBotProcess(bot, wss, statusTimer) {
  if (statusTimer) clearInterval(statusTimer);

  // 关闭所有容器
  try {
    if (bot?.currentWindow) {
      bot.currentWindow.close();
    }
  } catch { /* ignore */ }

  // 停止 pathfinder
  try {
    bot?.pathfinder?.stop();
  } catch { /* ignore */ }

  // 断开连接
  try {
    bot?.end('Process shutting down');
  } catch { /* ignore */ }

  // 关闭 WS 服务器
  try {
    wss?.close();
  } catch { /* ignore */ }

  // 等待资源释放
  await new Promise(r => setTimeout(r, 500));
}

module.exports = { createBotProcess };
