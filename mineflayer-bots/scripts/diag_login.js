#!/usr/bin/env node
/* 临时诊断：yggdrasil 完整登录握手探测（3535917632@qq.com + prinzeugen） */
const base = '/data/user/0/com.ai.assistance.operit/files/workspace/vmtools/vmtools-next/mineflayer-bots/node_modules';
const mc = require(base + '/minecraft-protocol');

const AUTH_ROOT = 'https://skin.prinzeugen.net/api/yggdrasil';

const client = mc.createClient({
  host: 'sy.server.mangocraft.cn',
  port: 35553,
  username: '3535917632@qq.com',
  password: 'jxy080405',
  auth: 'mojang',
  authServer: AUTH_ROOT + '/authserver',
  sessionServer: AUTH_ROOT + '/sessionserver',
  version: '26.1',
  profilesFolder: false,
});

client.on('connect', () => console.log('EV connect'));
client.on('login', (d) => console.log('EV login', JSON.stringify(d).slice(0, 500)));
client.on('error', (e) => console.log('EV error', e.message));
client.on('end', (r) => {
  console.log('EV end', r);
  process.exit(0);
});
client.on('packet', (d, meta) => {
  const name = meta && meta.name;
  if (['login', 'success', 'disconnect', 'kick_disconnect', 'login_start', 'encryption_begin'].includes(name)) {
    console.log('PKT', name, JSON.stringify(d).slice(0, 500));
  }
});
setTimeout(() => {
  console.log('TIMEOUT state=', client.state);
  try { client.end('timeout'); } catch (e) {}
  setTimeout(() => process.exit(0), 1500);
}, 25000);