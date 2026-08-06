#!/usr/bin/env node

/**
 * bot_main.js — mineflayer bot 进程入口
 *
 * 用法:
 *   node bot_main.js \
 *     --ws-port 44444 \
 *     --mc-host localhost \
 *     --mc-port 25565 \
 *     --username VMBot \
 *     --auth offline \
 *     --version 1.21.11 \
 *     --status-interval 5000
 *
 * auth 模式：offline | microsoft | yggdrasil
 * yggdrasil 模��需设置 --auth-server-url 或 AUTH_SERVER_URL 环境变量
 * yggdrasil 默认使用 MC_USERNAME 和 MC_PASSWORD 作为登录凭据
 *
 * 由 MineflayerProcessManager 从 Python 端启动。
 */

const { createBotProcess } = require('./mineflayer_bot');

// ── ANSI 颜色（终端显示用，与 mineflayer_bot.js 一致） ──
const ANSI = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  dim: '\x1b[90m',
};

// ── 解析命令行参数 ──
function parseArgs() {
  const args = {};
  const raw = process.argv.slice(2);
  for (let i = 0; i < raw.length; i++) {
    const key = raw[i].replace(/^--/, '');
    const val = raw[++i];
    if (val !== undefined) {
      // 尝试数字转换
      const num = Number(val);
      args[key.replace(/-/g, '_')] = isNaN(num) ? val : num;
    }
  }
  return args;
}

async function main() {
  const args = parseArgs();

  const options = {
    wsPort: args.ws_port || parseInt(process.env.WS_PORT || '44444', 10),
    mcHost: args.mc_host || process.env.MC_HOST || '127.0.0.1',
    mcPort: args.mc_port || parseInt(process.env.MC_PORT || '25565', 10),
    username: args.username || process.env.MC_USERNAME || 'VMBot',
    password: args.password || process.env.MC_PASSWORD || '',
    auth: args.auth || process.env.MC_AUTH || 'offline',
    version: args.version || process.env.MC_VERSION || '1.21.11',
    statusInterval: args.status_interval || parseInt(process.env.STATUS_INTERVAL || '5000', 10),
    authServerUrl: args.auth_server_url || process.env.AUTH_SERVER_URL || '',
  };

  console.log(`${ANSI.dim}[bot_main]${ANSI.reset} starting mineflayer bot...`);
  console.log(`${ANSI.dim}[bot_main]${ANSI.reset} ws_port=${options.wsPort} mc_host=${options.mcHost}:${options.mcPort}`);
  console.log(`${ANSI.dim}[bot_main]${ANSI.reset} username=${options.username} auth=${options.auth} version=${options.version}`);
  if (options.authServerUrl) {
    console.log(`${ANSI.dim}[bot_main]${ANSI.reset} auth_server_url=${options.authServerUrl}`);
  }

  try {
    const botProcess = await createBotProcess(options);

    // 优雅退出
    const shutdown = async (signal) => {
      console.log(`${ANSI.yellow}[bot_main]${ANSI.reset} received ${signal}, shutting down...`);
      await botProcess.stop();
      process.exit(0);
    };
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));

    // 告诉父进程（Python）已经准备好了
    console.log(`${ANSI.green}[bot_main] READY${ANSI.reset}`);

  } catch (err) {
    console.error(`${ANSI.red}[bot_main] FAILED:${ANSI.reset} ${err.message}`);
    process.exit(1);
  }
}

main();
