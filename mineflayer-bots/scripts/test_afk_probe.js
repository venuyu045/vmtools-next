#!/usr/bin/env node
/**
 * test_afk_probe.js — 探测服务器 /afkfarm /afk /afk super 指令行为（临时测试脚本）
 *
 * 用法：node test_afk_probe.js <round> <cmds...>
 *   round: 第几轮进出（仅用于日志标注）
 *   cmds:  依次要发送的指令（默认 /afkfarm /afk /afk super）
 *
 * 每次登录后按顺序发送指令，每条指令后等待 WAIT_MS 观察服务器响应，
 * 全部完成后自动退出（= 出服），用于"多进出几次"探测。
 */
const MF_DIR = '/data/user/0/com.ai.assistance.operit/files/workspace/vmtools/vmtools-next/mineflayer-bots/node_modules';

// ── 版本白名单扩展（与 bot_main.js 一致，26.1 协议） ──
// ⚠️ 必须在 require('mineflayer') 之前执行：loader.js 在模块加载时
//    解构拷贝 latestSupportedVersion，事后改 version.js 无效。
try {
  const mfVersion = require(MF_DIR + '/mineflayer/lib/version');
  for (const v of ['26.1']) {
    if (!mfVersion.testedVersions.includes(v)) mfVersion.testedVersions.push(v);
  }
  mfVersion.latestSupportedVersion = mfVersion.testedVersions[mfVersion.testedVersions.length - 1];
} catch (e) {
  console.error('version whitelist patch failed:', e.message);
}

const mineflayer = require(MF_DIR + '/mineflayer');

const HOST = 'sy.server.mangocraft.cn';
const PORT = 35553;
const USER = '3535917632@qq.com';      // yggdrasil 账号（邮箱）
const PASS = 'jxy080405';
const AUTH_ROOT = 'https://skin.prinzeugen.net/api/yggdrasil'; // 与生产拼接一致

const WAIT_MS = parseInt(process.env.WAIT_MS || '10000', 10);

const round = process.argv[2] || '1';
const cmds = process.argv.slice(3);
if (cmds.length === 0) cmds.push('/afkfarm', '/afk', '/afk super');

function log(tag, msg) {
  console.log(`[${new Date().toISOString().slice(11, 19)}][R${round}][${tag}] ${msg}`);
}

log('INFO', `connecting ${HOST}:${PORT} as ${USER} (auth=yggdrasil@${AUTH_ROOT})`);
log('INFO', `cmds to test: ${JSON.stringify(cmds)}`);

const bot = mineflayer.createBot({
  host: HOST,
  port: PORT,
  username: USER,
  password: PASS,
  auth: 'mojang',
  authServer: AUTH_ROOT + '/authserver',
  sessionServer: AUTH_ROOT + '/sessionserver',
  version: '26.1',
  hideErrors: false,
  logErrors: true,
  respawn: true,
});

bot.on('message', (jsonMsg) => {
  try {
    const text = (jsonMsg && typeof jsonMsg.toMotd === 'function')
      ? jsonMsg.toMotd()
      : (typeof jsonMsg.toString === 'function' ? jsonMsg.toString() : String(jsonMsg));
    if (text) log('CHAT', text.replace(/\u00a7./g, ''));
  } catch (e) {
    log('CHAT_ERR', e.message);
  }
});

bot.once('spawn', () => {
  log('SPAWN', `in-game as ${bot.username} @ ${JSON.stringify(bot.entity.position)}`);
  // 先观察 3s（服务器可能自动推送 AFK 提示/欢迎语），再依次发指令
  setTimeout(() => runCmds(0), 3000);
});

function runCmds(i) {
  if (i >= cmds.length) {
    log('DONE', 'all cmds sent, quitting (out)');
    setTimeout(() => { try { bot.end('probe done'); } catch (e) {} }, 1000);
    return;
  }
  const cmd = cmds[i];
  log('SEND', `>>> ${cmd}`);
  try { bot.chat(cmd); } catch (e) { log('SEND_ERR', e.message); }
  setTimeout(() => runCmds(i + 1), WAIT_MS);
}

bot.on('kicked', (reason) => log('KICKED', String(reason)));
bot.on('error', (err) => log('ERROR', err.message));
bot.on('end', (reason) => {
  log('END', String(reason));
  process.exit(0);
});

// 总超时兜底：120s 强制退出
setTimeout(() => {
  log('TIMEOUT', '120s total timeout, force quit');
  try { bot.end('timeout'); } catch (e) {}
  setTimeout(() => process.exit(0), 2000);
}, 120000);
