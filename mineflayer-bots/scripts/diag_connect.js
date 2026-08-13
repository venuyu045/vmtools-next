#!/usr/bin/env node
/* 临时诊断：minecraft-protocol 直连握手探测（离线模式，不认证） */
const base = '/data/user/0/com.ai.assistance.operit/files/workspace/vmtools/vmtools-next/mineflayer-bots/node_modules';
const mc = require(base + '/minecraft-protocol');

const client = mc.createClient({
  host: 'sy.server.mangocraft.cn',
  port: 35553,
  username: 'Venus_Yu045',
  version: '26.1',
  auth: 'offline',
});

client.on('connect', () => console.log('EV connect'));
client.on('login', (d) => console.log('EV login', JSON.stringify(d).slice(0, 300)));
client.on('error', (e) => console.log('EV error', e.message));
client.on('end', (r) => {
  console.log('EV end', r);
  process.exit(0);
});
client.on('packet', (d, meta) => {
  const name = meta && meta.name;
  if (['login', 'success', 'disconnect', 'kick_disconnect'].includes(name)) {
    console.log('PKT', name, JSON.stringify(d).slice(0, 400));
  }
});
setTimeout(() => {
  console.log('TIMEOUT state=', client.state);
  try { client.end('timeout'); } catch (e) {}
  setTimeout(() => process.exit(0), 1500);
}, 20000);
