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
  const start = botFoot(bot);
  if (!start) return { success: false, reason: 'no_position' };

  // 2026-08-16 P0-1：chunk 走廊预检——等待起点→目标矩形走廊内【全部】chunk 加载
  // （原仅检查目标 chunk）。配合 world.js 未加载块保守判定（未加载不可走），
  // 避免 A* 在空 chunk 上规划踩空路径；路径中途 chunk 未加载 → 直接 no_path
  // 而非生成不可行路径。
  try {
    if (typeof bot.world.hasChunk === 'function') {
      const cx0 = Math.floor(Math.min(start.x, goalX) / 16);
      const cx1 = Math.floor(Math.max(start.x, goalX) / 16);
      const cz0 = Math.floor(Math.min(start.z, goalZ) / 16);
      const cz1 = Math.floor(Math.max(start.z, goalZ) / 16);
      const needed = (cx1 - cx0 + 1) * (cz1 - cz0 + 1);
      let loaded = 0;
      for (let i = 0; i < 25; i++) { // 最多等 5s（25×200ms）
        loaded = 0;
        for (let cx = cx0; cx <= cx1; cx++) {
          for (let cz = cz0; cz <= cz1; cz++) {
            if (bot.world.hasChunk(cx, cz)) loaded++;
          }
        }
        if (loaded >= needed) break;
        await sleep(200);
      }
      if (loaded < needed) {
        log(`[baritone] 走廊 chunk 未全部加载（${loaded}/${needed}），等待后仍缺失`);
      }
    }
  } catch (e) { /* 无法检查 chunk 则跳过（回退旧行为） */ }

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

  // 逐段执行（2026-08-18 疾跑：剩余路径 >8 段疾跑，接近目标（≤8 段）转走路——
    // 阈值从 5 提到 8：短距离寻路（补洞/行间几~十几格）疾跑收益低且放大滑行误差）
    // ⚠️ 2026-08-19：超长寻路（>100 段）不疾跑——高速移动触发服务器大量区块加载/
    // 实体同步 → TPS 骤降 → keepalive 超时踢出（实测 330 格寻路掉线 disconnect.timeout）。
    // 另：每 50 段暂停 300ms 让服务器/事件循环喘息，降低瞬时负载。
  let lastPos = start;
  const longPath = path.length > 100;
  for (let i = 0; i < path.length; i++) {
    if (Date.now() > deadline) {
      return { success: false, reason: 'timeout', position: lastPos, path: path.slice(0, i) };
    }
    const mv = path[i];
    const remaining = path.length - i; // 剩余段数（每段 1 格）
    // 长路径走中速（不疾跑）；短/中路径按剩余段数疾跑
    const shouldSprint = !longPath && remaining > 8;
    if (i > 0 && i % 50 === 0) {
      await sleep(300); // 2026-08-19：长寻路定期喘息，防服务器 TPS 骤降
      log(`[baritone] 长寻路喘息 @${i}/${path.length}`);
    }
    log(`[baritone] 执行 ${i + 1}/${path.length} ${mv.name} → (${mv.to.x},${mv.to.y},${mv.to.z})${shouldSprint ? ' [sprint]' : ''}`);
    const r = await executeMovement(bot, mv, { onLog, sprint: shouldSprint });
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
    const r2 = await executeMovement(bot, mv, { onLog, sprint: shouldSprint });
    if (r2.success) { lastPos = r2.position; world.clearCache(); continue; }
    return { success: false, reason: r.reason || 'move_failed', position: lastPos, path: path.slice(0, i) };
  }

  const finalPos = botFoot(bot);
  return { success: true, reason: 'done', path, position: finalPos };
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

module.exports = { pathTo };