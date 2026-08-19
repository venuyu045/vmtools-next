/**
 * apply_particle_patch.js — 修复 26.1 协议 world_particles 粒子包解析失败（幂等）
 *
 * 背景（2026-08-19）：服务器（Velocity 26.2 / 后端 26.1/775）经 Via 转发的
 * world_particles 粒子数据与 minecraft-data 26.1 定义的 Particle 结构不匹配，
 * protodef 解析在 Particle 内部 f32 处 PartialReadError → TCP 包流损坏 →
 * 客户端无法解析 keepalive → 30s 后被服务器踢（disconnect.timeout）。
 *
 * 修复：把 packet_world_particles 的 particle 字段类型改为 restBuffer——
 * 包整体仍按长度切帧，粒子内部数据不再解析（读剩余字节原样保留）。
 * 副作用：bot.on('world_particles') 事件里 particle 是 Buffer（原本是对象）；
 * 项目后端/handlers 均未使用粒子数据，无影响。
 *
 * 用法：node scripts/apply_particle_patch.js（部署时在 mineflayer-bots 目录执行）
 * 幂等：检测到已是 restBuffer 则跳过。
 */
const fs = require('fs');
const path = require('path');

const target = path.join(__dirname, '..', 'node_modules', 'minecraft-data',
  'minecraft-data', 'data', 'pc', '26.1', 'protocol.json');

if (!fs.existsSync(target)) {
  console.log('[particle-patch] 26.1 protocol.json not found, skip');
  process.exit(0);
}

try {
  const data = JSON.parse(fs.readFileSync(target, 'utf8'));
  const pkt = data.play && data.play.toClient && data.play.toClient.types &&
    data.play.toClient.types.packet_world_particles;
  if (!pkt || !Array.isArray(pkt[1])) {
    console.log('[particle-patch] packet_world_particles not found, skip');
    process.exit(0);
  }
  const fields = pkt[1];
  const particleField = fields.find(f => f && f.name === 'particle');
  if (!particleField) {
    console.log('[particle-patch] particle field not found, skip');
    process.exit(0);
  }
  if (particleField.type === 'restBuffer') {
    console.log('[particle-patch] already patched (restBuffer), skip');
    process.exit(0);
  }
  particleField.type = 'restBuffer';
  fs.writeFileSync(target, JSON.stringify(data));
  console.log('[particle-patch] OK: packet_world_particles.particle → restBuffer');
} catch (e) {
  console.error('[particle-patch] FAILED:', e.message);
  process.exit(1);
}
