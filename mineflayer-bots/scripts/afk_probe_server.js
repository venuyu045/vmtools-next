#!/usr/bin/env node
/**
 * afk_probe_server.js — 服务器端 AFK 指令探测脚本（临时，测试完删除）
 *
 * 用法：node afk_probe_server.js <round> [cmds...]
 *   round: 进出轮次（仅日志标注）
 *   cmds:  依次发送的指令（默认 /afkfarm /afk /afk super）
 *
 * 登录成功后先观察 3s，再逐条发指令（每条间隔 WAIT_MS），全部完成后
 * bot.end() 出服。所有聊天/系统消息（服务器对指令的响应）打印到 stdout。
 */
const MF_DIR = '/opt/vmtools-next/vmtools-next/mineflayer-bots/node_modules';

// ── 版本白名单扩展（必须在 require mineflayer 之前） ──
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
const USER = '3535917632@qq.com';
const PASS = 'jxy080405';
const AUTH_ROOT = 'https://skin.prinzeugen.net/api/yggdrasil';
const WAIT_MS = parseInt(process.env.WAIT_MS || '12000', 10);

const round = process.argv[2] || '1';
const cmds = process.argv.slice(3);
if (cmds.length === 0) cmds.push('/afkfarm', '/afk', '/afk super');

function log(tag, msg) {
  console.log(`[${new Date().toISOString().slice(11, 19)}][R${round}][${tag}] ${msg}`);
}

log('INFO', `connecting ${HOST}:${PORT} as ${USER} (yggdrasil@${AUTH_ROOT})`);
log('INFO', `cmds: ${JSON.stringify(cmds)}`);

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

setTimeout(() => {
  log('TIMEOUT', '150s total timeout, force quit');
  try { bot.end('timeout'); } catch (e) {}
  setTimeout(() => process.exit(0), 2000);
}, 150000);