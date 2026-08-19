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
const { createServuxHandlers } = require('./handlers/servux');
const { createCombatHandlers } = require('./handlers/combat');
const { createSleepHandlers } = require('./handlers/sleep');
const {
  createSuccessResponse,
  createErrorResponse,
  createEvent,
  createStatusUpdate,
} = require('./ws_protocol');

// ── ANSI 颜色（终端显示用） ──
// Node console 输出到管道（PIPE）时会自动禁用颜色，这里手动嵌入 ANSI 码，
// 让 MF 终端（xterm 渲染 stdout）像 MCC 终端一样显示彩色内容。
const ANSI = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  dim: '\x1b[90m',
  bold: '\x1b[1m',
};

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
 * @param {number} [options.viewerPort=0] — 实时 3D 查看器端口（>0 才启动，0=关闭）
 * @param {string} [options.viewerHost='0.0.0.0'] — 查看器监听地址（生产建议 127.0.0.1 + 反代）
 * @param {boolean} [options.viewerFirstPerson=false] — 第一人称视角（false=跟随/鸟瞰）
 * @param {number} [options.viewerDistance=6] — 查看器视距（chunk 数）
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
    viewerPort = 0,
  viewerHost = '0.0.0.0',
  viewerPrefix = '',
  viewerFirstPerson = false,
  viewerDistance = 6,
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
    // ⚠️ 2026-08-19：禁用客户端 keepalive 超时踢出（默认 30s）。
    // 根因：地图画长寻路（330 格）高速移动触发服务器大量区块加载/实体同步 →
    // 服务器 TPS 骤降 → 30s 内未发 keepalive → 客户端被判超时踢出（实测
    // "client timed out after 30000 milliseconds" + disconnect.timeout）。
    // keepAlive=false 后：TCP 断开/被踢仍即时触发 end（进程管理器自动重启），
    // 仅不再因服务器瞬卡而误踢——对 bot 更稳。
    keepAlive: false,
  };

  // ── 认证方式处理 ──
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
  // 仅绑定 127.0.0.1：WS 桥无鉴权，若监听 0.0.0.0 则任何能连通 44444-44500
  // 端口的网络实体都能完全控制 bot（移动/存取物品/发聊天/执行游戏命令）。
  const wss = new WebSocketServer({ port: wsPort, host: '127.0.0.1' });

  // ⚠️ connection 监听必须在 wss 创建后【立即】注册，不能等 login！
  // 原因：bot 登录（yggdrasil 认证）需要时间，而 Python 端进程管理器在 bot
  // 进程一启动就会尝试连接 WS。若 connection 监听注册在 login 回调内，
  // 登录前建立的连接将【没有 message 监听器】——只能收到广播
  // （bot_ready/status/bot_chat），发出的请求无人处理，Python 端会
  // 30s 超时（历史事故：chat_responder 插件 send_chat 超时）。
  // 登录前 methodMap 为空，请求会快速返回 Unknown method；登录后正常。
  wss.on('connection', (ws) => {
    ws.on('message', (data) => handleWsMessage(ws, data));
    ws.on('close', () => { /* 不处理，用 ping 检测存活 */ });
    ws.on('error', () => { /* 忽略 */ });
  });

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
      const respJson = JSON.stringify(createSuccessResponse(request_id, result));
      // ── 2026-08-16 诊断：记录超大响应（284MB message too big 排查）──
      if (respJson.length > 200 * 1024) {
        console.log(`[WS-BIG-RESP] method=${method} size=${(respJson.length / 1024 / 1024).toFixed(2)}MB req=${request_id} head=${respJson.slice(0, 300)}`);
      }
      ws.send(respJson);
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
        console.error(`${ANSI.yellow}[pathfinder]${ANSI.reset} setup failed:`, err.message);
      }
    });

    bot.on('spawn', () => {
      // 登录成功标志（同 login 事件）：WS 服务在 login 后才开启，若 Python 端
      // 恰好没抓到 login 的 stdout 行（缓冲/竞态），spawn 是第二次确定性信号。
      if (!bot.username) return;
      console.log(`${ANSI.green}[bot] LOGIN_OK${ANSI.reset}`, bot.username);
      console.log(`${ANSI.green}[bot] spawned at${ANSI.reset}`, bot.entity.position);
      broadcast(createEvent('bot_spawned', {
        position: {
          x: bot.entity.position.x,
          y: bot.entity.position.y,
          z: bot.entity.position.z,
        },
      }));

      // ── 可选：启动实时 3D 查看器（--viewer-port > 0 时） ──
      // 每个 MF 实例独立进程，viewer 按实例独立启动互不干扰；
      // 默认关闭（viewerPort=0），由 Python 端启动命令按需传入。
      if (viewerPort > 0 && !bot.viewer) {
        try {
          const startViewer = require('./viewer');
          startViewer(bot, {
      port: viewerPort,
      host: viewerHost,
      prefix: viewerPrefix,
      firstPerson: viewerFirstPerson,
      viewDistance: viewerDistance,
    });
          console.log(`${ANSI.cyan}[viewer]${ANSI.reset} 3D viewer listening on ${viewerHost}:${viewerPort}`);
        } catch (err) {
          console.error(`${ANSI.red}[viewer]${ANSI.reset} failed to start:`, err.message);
        }
      }
    });

    bot.on('death', () => {
      console.log(`${ANSI.red}[bot] died${ANSI.reset}`);
      broadcast(createEvent('bot_death', {}));
    });

    bot.on('health', () => {
      // 生命值变化，状态推送会在定时器中覆盖
    });

    bot.on('kicked', (reason) => {
      // reason 可能是字符串或 {text, extra...} 对象——String() 会输出 [object Object]
      // 导致后端看不到真实踢出原因（如「登录过于频繁」）。优先取 text 字段。
      let rs = reason;
      if (typeof reason === 'object' && reason !== null) {
        rs = reason.text || JSON.stringify(reason);
      }
      console.log(`${ANSI.red}[bot] kicked:${ANSI.reset}`, rs);
      broadcast(createEvent('bot_kicked', { reason: String(rs) }));
    });

    bot.on('error', (err) => {
      console.error(`${ANSI.red}[bot] error:${ANSI.reset}`, err.message);
      broadcast(createEvent('bot_error', { error: err.message }));
    });

    bot.on('end', (reason) => {
      let rs = reason;
      if (typeof reason === 'object' && reason !== null) {
        rs = reason.text || JSON.stringify(reason);
      }
      console.log(`${ANSI.yellow}[bot] disconnected:${ANSI.reset}`, rs);
      broadcast(createEvent('bot_disconnected', { reason: String(rs) }));
      // 游戏连接已断开：进程不退出会导致 Python 端 _watch_exit_loop 永远等不到
      // 退出码而无法自动重启（历史 bug：bot 卡在"假在线"状态）。这里延迟退出，
      // 让 Python 端进程管理器检测到退出后按 desired_state 自动重启（含退避）。
      if (!isStopping) {
        setTimeout(() => process.exit(0), 1500);
      }
    });

    bot.on('chat', (username, message) => {
      if (username !== bot.username) {
        broadcast(createEvent('bot_chat', { username, message }));
      }
    });

    // ── 服务器聊天/系统消息 → stdout（MF 终端可见，绿色） ──
    // mineflayer 在 1.19+ 签名聊天协议下 `chat` 事件并不可靠（签名玩家消息
    // 只走 system_chat/player_chat 包），`message` 事件覆盖所有服务器聊天内容
    // （玩家消息 + 系统消息 + 命令回显）。
    // 注意用 toMotd() 而非 toString()：prismarine-chat 的 toString() 会剥掉
    // 全部 § 颜色码（return message.replace(/§[0-9a-flnmokr]/g, '')），导致
    // 服务器彩色文字在终端里丢失配色；toMotd() 保留 § 码，由前端
    // MccWebTerminal 的 mcFormatToAnsi 转 ANSI 后按服务器配色渲染。
    bot.on('message', (jsonMsg) => {
      try {
        const text = (jsonMsg && typeof jsonMsg.toMotd === 'function')
          ? jsonMsg.toMotd()
          : (typeof jsonMsg.toString === 'function' ? jsonMsg.toString() : String(jsonMsg));
        if (text) {
          console.log(`${ANSI.green}[chat]${ANSI.reset} ${text}`);
          // 服务器消息（含命令回显/系统提示）同时广播为 bot_message 事件，
          // 供后端插件订阅（如 auto_afkfarm/auto_afk_super 检测指令响应）。
          // 保留 toMotd 原始文本（含 § 码），插件端自行剥离。
          broadcast(createEvent('bot_message', { message: text }));
        }
      } catch (err) {
        // 忽略单条消息解析失败，不影响后续
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
      console.log(`${ANSI.green}[bot] LOGIN_OK${ANSI.reset}`, bot.username);
      // 登录成功标志：由 Python 端通过 stdout 解析，作为 bot 已进入服务器且
      // 已经通过 yggdrasil 认证的确定性信号（mineflayer 没有独立的 login 事件标志，
      // 只有这里能可靠区分「进程存活」与「真正登录成功」）。
      console.log(`${ANSI.green}[bot] logged in as${ANSI.reset}`, bot.username);

      // ── 4. 创建 handlers 并注册 ──
      const servuxHandlers = createServuxHandlers(bot);
      servuxHandlers._register(); // 注册 custom_payload 监听
      handlers = {
        ...createMovementHandlers(bot),
        ...createBlockHandlers(bot),
        // 传入 broadcast/createEvent：容器 windowOpen/Close 自动注册事件推给 Python 端
        ...createInventoryHandlers(bot, { broadcast, createEvent }),
        ...createWorldHandlers(bot),
        ...createChatHandlers(bot),
        ...servuxHandlers,
        // 战斗 handler 需要广播能力（耐久低事件），传入 broadcast/createEvent 闭包
        ...createCombatHandlers(bot, { broadcast, createEvent }),
        // 睡觉 handler（永昼：夜晚自动睡觉跳过黑夜，2026-08-16）
        ...createSleepHandlers(bot, { broadcast, createEvent }),
      };

      // 注册所有方法
      for (const [name, fn] of Object.entries(handlers)) {
        methodMap[name] = fn;
      }

      // ── 5. WebSocket 服务器 connection 监听已在 wss 创建时注册 ──
      //    登录成功后向所有已连接客户端广播 bot_ready（含登录前建立的连接）。
      broadcast(createEvent('bot_ready', {
        username: bot.username,
        ws_port: wsPort,
      }));

      // ── 6. 启动状态推送定时器 ──
      statusTimer = setInterval(() => {
        broadcast(createStatusUpdate(bot));
      }, statusInterval);

      console.log(`${ANSI.cyan}[ws]${ANSI.reset} WebSocket server listening on port ${wsPort}`);
      console.log(`${ANSI.green}[bot] connected to${ANSI.reset} ${mcHost}:${mcPort} as ${bot.username}`);

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
    // ── 2026-08-16 诊断：记录超大广播（284MB message too big 排查）──
    if (json.length > 200 * 1024) {
      console.log(`[WS-BIG-BROADCAST] event=${data && data.event} type=${data && data.type} size=${(json.length / 1024 / 1024).toFixed(2)}MB head=${json.slice(0, 300)}`);
    }
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

  // 关闭 3D 查看器（若已启动）
  try {
    if (bot?.viewer?.close) {
      bot.viewer.close();
    }
  } catch { /* ignore */ }

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
