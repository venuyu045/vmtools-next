/**
 * pathfinder.js — baritone 移植寻路对外接口
 *
 * pathTo(bot, goalX, goalY, goalZ, opts)：
 *   1. World 世界模型（blockAt 读取方块）
 *   2. A* 计算 movement 序列（baritone Moves 模型）
 *   3. PathExecutor 逐段执行（控制键：forward/jump/strafe）
 *   4. 遇到 PILLAR/BRIDGE（需搭块）→ scaffold_to 兜底（mineflayer 自带）
 *
 * 返回 { success, reason?, path?, position? }
 */

const { World } = require('./world');
const { findPath } = require('./astar');
const { executeMovement, botFoot } = require('./executor');

/**
 * 完整寻路执行。
 * @param {Bot} bot mineflayer bot
 * @param {number} goalX @param {number} goalY @param {number} goalZ 目标方块坐标
 * @param {object} opts { maxOffset=1, maxNodes=20000, timeoutMs=60000, onLog }
 */
async function pathTo(bot, goalX, goalY, goalZ, opts = {}) {
  const { maxOffset = 1, maxNodes = 20000, timeoutMs = 60000, onLog } = opts;
  const log = (m) => { if (onLog) onLog(m); };

  const world = new World(bot);
  // 2026-08-15 P5：寻路前清空方块缓存——世界会变化（bot 放置/平台实际存在但
  // 缓存可能是旧 air），A* 必须读到最新状态（否则 no_path 误判）
  world.clearCache();
  // 2026-08-15 P5：等待目标 chunk 加载（baritone A* 需要读目标区域方块，
  // chunk 未加载时 blockAt 全 null → 误判不可走）
  try {
    const cx = Math.floor(goalX / 16), cz = Math.floor(goalZ / 16);
    if (typeof bot.world.hasChunk === 'function' && !bot.world.hasChunk(cx, cz)) {
      for (let i = 0; i < 25; i++) {
        await sleep(200);
        if (bot.world.hasChunk(cx, cz)) break;
      }
    }
  } catch (e) { /* 无法检查 chunk 则跳过 */ }
  const start = botFoot(bot);
  if (!start) return { success: false, reason: 'no_position' };

  log(`[baritone] 寻路 from=(${start.x},${start.y},${start.z}) to=(${goalX},${goalY},${goalZ})`);

  // 距离估算超时
  const est = Math.max(5000, Math.min(timeoutMs,
    3000 + (Math.abs(goalX - start.x) + Math.abs(goalZ - start.z)) * 400));
  const deadline = Date.now() + est;

  const path = findPath(world, start, goalX, goalY, goalZ, maxOffset, maxNodes);
  if (!path || path.length === 0) {
    // 已在目标附近（A* 起终点即目标）——2026-08-15 P5 严格化：
    //   maxOffset===1 → bot 脚格必须与目标格一致（水平）且 y 偏差≤1；
    //   maxOffset>1 → 允许 ±maxOffset 格。
    const f = botFoot(bot);
    const yDiff = Math.abs(f.py - goalY);
    const hOk = maxOffset === 1
      ? (f.x === goalX && f.z === goalZ)
      : (Math.abs(f.x - goalX) <= maxOffset && Math.abs(f.z - goalZ) <= maxOffset);
    if (hOk && yDiff <= 1) {
      return { success: true, reason: 'already_there', path: [], position: f };
    }
    return { success: false, reason: 'no_path', position: start };
  }
  log(`[baritone] 路径 ${path.length} 段: ${path.map(p => p.name).join(' → ')}`);

  // 逐段执行
  let lastPos = start;
  for (let i = 0; i < path.length; i++) {
    if (Date.now() > deadline) {
      return { success: false, reason: 'timeout', position: lastPos, path: path.slice(0, i) };
    }
    const mv = path[i];
    log(`[baritone] 执行 ${i + 1}/${path.length} ${mv.name} → (${mv.to.x},${mv.to.y},${mv.to.z})`);
    const r = await executeMovement(bot, mv, { onLog });
    if (r.success) {
      lastPos = r.position;
      world.clearCache(); // 世界变化后清缓存（scaffold 放置了方块）
      continue;
    }
    if (r.reason && r.reason.startsWith('need_place:')) {
      // PILLAR/BRIDGE → mineflayer scaffold_to 兜底
      log(`[baritone] ${r.reason} → scaffold 兜底`);
      try {
        const sr = await bot.scaffoldTo(new (require('vec3'))(mv.to.x, mv.to.y, mv.to.z), {
          timeoutMs: 8000,
        });
        const f = botFoot(bot);
        if (sr && Math.hypot(f.px - mv.to.x, f.pz - mv.to.z) <= 0.6) {
          lastPos = f;
          world.clearCache();
          continue;
        }
      } catch (e) { /* scaffold 失败 */ }
      return { success: false, reason: r.reason, position: lastPos, path: path.slice(0, i) };
    }
    // 普通移动失败：重试一次（world 缓存可能过期）
    const r2 = await executeMovement(bot, mv, { onLog });
    if (r2.success) { lastPos = r2.position; world.clearCache(); continue; }
    return { success: false, reason: r.reason || 'move_failed', position: lastPos, path: path.slice(0, i) };
  }

  const finalPos = botFoot(bot);
  return { success: true, reason: 'done', path, position: finalPos };
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

module.exports = { pathTo };