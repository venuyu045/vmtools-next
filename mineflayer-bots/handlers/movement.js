/**
 * movement.js — 移动/寻路/位置查询 handler
 *
 * 方法：
 *   move_to(x, y, z, max_offset?, timeout_ms?)  → 使用 pathfinder 寻路到目标
 *   look_at(x, y, z)                            → 看向坐标
 *   get_player_state()                          → 返回 bot 位置/状态
 *   cancel_pathing()                            → 取消当前寻路
 *   is_player_nearby(radius?)                   → 检查附近是否有玩家
 */

const { Vec3 } = require('vec3');
const { GoalNear, GoalBlock, GoalNearXZ } = require('mineflayer-pathfinder').goals;
const { pathTo } = require('../baritone-path/pathfinder');

/**
 * @param {import('mineflayer').Bot} bot
 * @returns {object} handlers 对象 { move_to, look_at, get_player_state, cancel_pathing, is_player_nearby }
 */
function createMovementHandlers(bot) {
  // 当前寻路的 resolve 引用（用于取消）
  let pathfindingResolver = null;

  // ── 寻路到附近 ──
  // ⚠️ listener 必须全部清理：建造循环每格调用一次 move_to，若
  // goal_reached/path_stop/path_timeout 的 once 监听残留，16384 格会
  // 泄漏数万个 listener（emit 遍历变慢、内存膨胀）。统一用 finish() 收口。
  async function move_to({ x, y, z, max_offset = 3, timeout_ms = 15000, ignore_y = false }) {
    return new Promise(async (resolve, reject) => {
      // N4 chunk 预检（2026-08-15 第二批，对齐 baritone PathExecutor chunk 边缘暂停）：
      // 目标 chunk 未加载时先等加载（最多 5s），避免"目标方块读取为空/寻路直接失败"。
      try {
        const chunkX = Math.floor(x / 16), chunkZ = Math.floor(z / 16);
        const hasChunk = typeof bot.world.hasChunk === 'function';
        if (hasChunk && !bot.world.hasChunk(chunkX, chunkZ)) {
          for (let i = 0; i < 25; i++) {
            await new Promise(r => setTimeout(r, 200));
            if (bot.world.hasChunk(chunkX, chunkZ)) break;
          }
        }
      } catch (e) { /* 无法检查 chunk 状态则跳过预检 */ }

      // N3 成本估算超时（2026-08-15 第二批，对齐 baritone PathExecutor）：
      // 近目标快超时、远目标给足；下限 5s、上限 = 调用方 timeout_ms。
      // 例：2 格距离 → 4.6s；50 格 → 20s（调用方上限）。
      let estTimeout = 15000;
      try {
        const p = bot.entity ? bot.entity.position : null;
        const dx = p ? Math.abs(x - p.x) : 0;
        const dz = p ? Math.abs(z - p.z) : 0;
        const dy = p ? Math.abs(y - p.y) : 0;
        const manhattan = dx + dz;
        estTimeout = 3000 + manhattan * 800 + (dy > 1 ? 2000 : 0);
      } catch (e) { /* 取不到位置则用默认估算 */ }
      const effectiveTimeout = Math.min(timeout_ms, Math.max(5000, estTimeout));

      const goal = ignore_y
        ? new GoalNearXZ(x, z, max_offset)
        : new GoalNear(x, y, z, max_offset);
      let finished = false;
      let timer = null;
      let stuckTimer = null;
      let startTimer = null;

      const cleanup = () => {
        bot.removeListener('goal_reached', onGoalReached);
        bot.removeListener('path_stop', onStopped);
        bot.removeListener('path_timeout', onTimeout);
        if (timer) clearTimeout(timer);
        if (stuckTimer) clearInterval(stuckTimer);
        if (startTimer) clearTimeout(startTimer);
      };
      const finish = (result) => {
        if (finished) return;
        finished = true;
        cleanup();
        pathfindingResolver = null;
        resolve(result);
      };
      const onGoalReached = () => finish({ success: true, position: getPos() });
      const onStopped = () => finish({ success: false, reason: 'stopped', position: getPos() });
      const onTimeout = () => finish({ success: false, reason: 'timeout', position: getPos() });

      bot.once('goal_reached', onGoalReached);
      bot.once('path_stop', onStopped);
      bot.once('path_timeout', onTimeout);

      timer = setTimeout(() => {
        bot.pathfinder.stop();
        finish({ success: false, reason: 'timeout', position: getPos() });
      }, effectiveTimeout);

      // N3 卡住检测：每 2s 采样位置，连续 3 次（6s）移动 <0.2 格且未达 goal → 主动放弃
      // （对齐 playercontrolpp BaritonePathingController STUCK_LIMIT，不等 20s 超时）
      let lastPos = bot.entity ? { x: bot.entity.position.x, z: bot.entity.position.z } : null;
      let stillTicks = 0;
      stuckTimer = setInterval(() => {
        if (finished) return;
        const pos = bot.entity ? bot.entity.position : null;
        if (!pos) return;
        if (lastPos) {
          const moved = Math.hypot(pos.x - lastPos.x, pos.z - lastPos.z);
          const d = Math.hypot(pos.x - x, pos.z - z);
          if (moved < 0.2 && d > max_offset) {
            stillTicks++;
            if (stillTicks >= 3) { // 6s 未移动
              bot.pathfinder.stop();
              finish({ success: false, reason: 'stuck', position: getPos() });
              return;
            }
          } else {
            stillTicks = 0;
          }
        }
        lastPos = { x: pos.x, z: pos.z };
      }, 2000);

      // N3 未开始检测：setGoal 后 3s 内 pathfinder 无进展（isMoving false 且距离>max_offset）
      // → 提前放弃（对齐 playercontrolpp PATHING_NOT_STARTED 40 tick）
      startTimer = setTimeout(() => {
        if (finished) return;
        let moving = true;
        try { moving = bot.pathfinder.isMoving(); } catch (e) { moving = true; }
        const pos = bot.entity ? bot.entity.position : null;
        const d = pos ? Math.hypot(pos.x - x, pos.z - z) : 9999;
        if (!moving && d > max_offset) {
          bot.pathfinder.stop();
          finish({ success: false, reason: 'path_not_started', position: getPos() });
        }
      }, 3000);

      try {
        bot.pathfinder.setGoal(goal);
      } catch (err) {
        finish({ success: false, reason: `setGoal error: ${err.message}`, position: getPos() });
      }
    });
  }

  // ── 看向坐标 ──
  async function look_at({ x, y, z }) {
    try {
      await bot.lookAt(new Vec3(x, y, z));
      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 获取玩家状态 ──
  function get_player_state({} = {}) {
    if (!bot.entity) {
      return { success: true, location: null, health: 0, food: 0, dimension: 'unknown' };
    }
    return {
      success: true,
      location: {
        x: bot.entity.position.x,
        y: bot.entity.position.y,
        z: bot.entity.position.z,
      },
      yaw: bot.entity.yaw,
      pitch: bot.entity.pitch,
      health: bot.health || 20,
      food: bot.food || 20,
      dimension: bot.game?.dimension || 'unknown',
      game_mode: bot.game?.gameMode || 'unknown',
      is_on_ground: bot.entity.onGround,
      ping: bot.player?.ping ?? -1,  // 往返延迟(ms)，供建造侧 RTT 自适应限速
      // 2026-08-16：手持物品名（供建造侧校验 _current_item 缓存是否失效——
      // 手持被服务器/操作改变时缓存误判导致"手持错误物品放置"）
      held_item: bot.heldItem ? bot.heldItem.name : null,
    };
  }

  // ── 取消寻路 ──
  function cancel_pathing({} = {}) {
    bot.pathfinder.stop();
    if (pathfindingResolver) {
      pathfindingResolver({ success: false, reason: 'cancelled' });
      pathfindingResolver = null;
    }
    return { success: true };
  }

  // ── 检查附近玩家 ──
  function is_player_nearby({ radius = 10 } = {}) {
    if (!bot.entity) return { success: true, nearby: false, players: [] };
    const pos = bot.entity.position;
    const nearby = Object.values(bot.players || {})
      .filter(p => p.entity && p.username !== bot.username)
      .filter(p => {
        const d = p.entity.position.distanceTo(pos);
        return d <= radius;
      })
      .map(p => ({
        username: p.username,
        distance: p.entity.position.distanceTo(pos),
        position: { x: p.entity.position.x, y: p.entity.position.y, z: p.entity.position.z },
      }));
    return { success: true, nearby: nearby.length > 0, players: nearby };
  }

  // ── 内部工具 ──
  function getPos() {
    if (!bot.entity) return null;
    return { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z };
  }

  // ── 移动控制（玩家操控：前后左右/跳跃/蹲下/视角） ──
// mineflayer setControlState：持续按住某个控制键直到再次调用关闭。
// 前端按下 → state=true，松开 → state=false（WebSocket 往返延迟低，可接受）。

const CONTROL_KEYS = ['forward', 'back', 'left', 'right', 'jump', 'sneak', 'sprint'];

function set_control_state({ control, state = true } = {}) {
  try {
    if (!control || !CONTROL_KEYS.includes(control)) {
      return { success: false, error: `control must be one of: ${CONTROL_KEYS.join(', ')}` };
    }
    bot.setControlState(control, !!state);
    return { success: true, control, state: !!state };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ── 视角控制（平滑转向） ──
// yaw/pitch 为弧度（mineflayer 语义：yaw -π~π，pitch -π/2~π/2）。
// 前端摇杆累计目标角度后调用；force=false 由客户端平滑转向（服务器限制转向速度）。
function look({ yaw, pitch = null, force = false } = {}) {
  try {
    if (typeof yaw !== 'number' || isNaN(yaw)) {
      return { success: false, error: 'yaw (radians) is required' };
    }
    if (pitch !== null && (typeof pitch !== 'number' || isNaN(pitch))) {
      return { success: false, error: 'pitch (radians) must be a number' };
    }
    const targetPitch = pitch !== null ? Math.max(-Math.PI / 2, Math.min(Math.PI / 2, pitch)) : null;
    bot.look(yaw, targetPitch, !!force);
    return { success: true, yaw, pitch: targetPitch, force: !!force };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ── 跳跃一次（按住 jump 约 150ms 后松开） ──
async function jump({} = {}) {
  try {
    bot.setControlState('jump', true);
    await new Promise(r => setTimeout(r, 150));
    bot.setControlState('jump', false);
    return { success: true };
  } catch (err) {
    bot.setControlState('jump', false);
    return { success: false, error: err.message };
  }
}

// ── 蹲下/站起（toggle 或显式 state） ──
function sneak({ state = null } = {}) {
  try {
    const target = state === null ? !bot.controlState.sneak : !!state;
    bot.setControlState('sneak', target);
    return { success: true, sneaking: target };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ── 行内小步直走（2026-08-15 第三批：消除每格寻路，大图性能关键）──
// 行内相邻格是直线 1 格位移，用控制键直走替代 pathfinder setGoal（每格一次
// pathfinder 计算在 512²/1024² 图上会爆炸）。撞墙/卡地形（3s 位置不动）→ 返回
// 失败，调用方回退 pathfinder。仅用于距离 ≤3 的直线相邻格（不处理 y 落差）。
async function walk_toward({ x, z, timeout_ms = 8000 } = {}) {
  return new Promise((resolve) => {
    const pos = bot.entity ? bot.entity.position : null;
    if (!pos) return resolve({ success: false, reason: 'no_entity' });
    const dx = x - pos.x, dz = z - pos.z;
    const dist = Math.hypot(dx, dz);
    if (dist > 3.0) return resolve({ success: false, reason: 'too_far' });

    // 2026-08-16 P0-1 护栏：目标格脚下必须是实体（air/water/lava → 拒绝直走，
    // 防「行内直走掉下平台」复现——调用方回退 pathfinder 找安全路径）。
    // bot 脚部 y = pos.y；目标站立格 (floor(x), floor(pos.y), floor(z)) 脚下
    // (floor(x), floor(pos.y)-1, floor(z)) 需实体。
    try {
      const foot = bot.blockAt(new Vec3(Math.floor(x), Math.floor(pos.y) - 1, Math.floor(z)));
      if (!foot || foot.type === 0 || /water|lava|bubble_column/.test(foot.name || '')) {
        return resolve({ success: false, reason: 'unsafe_foot' });
      }
    } catch (e) {
      return resolve({ success: false, reason: 'foot_check_error' });
    }

    let finished = false;
    const cleanup = () => {
      bot.setControlState('forward', false);
      if (interval) clearInterval(interval);
      if (timeoutHandle) clearTimeout(timeoutHandle);
      finished = true;
    };
    const finish = (result) => {
      if (finished) return;
      cleanup();
      resolve(result);
    };

    // 朝向目标（lookAt 自动算 yaw/pitch，force=true 立即转向）
    bot.lookAt(new Vec3(x, bot.entity.position.y, z), true).catch(() => {});
    bot.setControlState('forward', true);

    let lastPos = { x: pos.x, z: pos.z };
    let stillTicks = 0;
    const start = Date.now();

    const check = () => {
      if (finished) return;
      const p = bot.entity ? bot.entity.position : null;
      if (!p) return finish({ success: false, reason: 'no_entity' });
      const d = Math.hypot(p.x - x, p.z - z);
      // ⚠️ 2026-08-19 修复：目标 (x,z) 是方块整数坐标，bot 站在目标方块中心时
      // 距离 = √(0.5²+0.5²) ≈ 0.707 > 0.5——原 `d <= 0.5` 永不命中 → 行内直走
      // 总是走到 8s 超时才失败 → 每格回退全量寻路（大图性能灾难）。
      // 放宽到 ≤1.0（方块中心距 0.707 + 容差，覆盖到位）。
      if (d <= 1.0) return finish({ success: true, position: { x: p.x, y: p.y, z: p.z } });
      const moved = Math.hypot(p.x - lastPos.x, p.z - lastPos.z);
      if (moved < 0.15) {
        stillTicks++;
        if (stillTicks >= 6) return finish({ success: false, reason: 'stuck' }); // 3s 未移动
      } else {
        stillTicks = 0;
      }
      lastPos = { x: p.x, z: p.z };
      if (Date.now() - start > timeout_ms) return finish({ success: false, reason: 'timeout' });
    };
    const interval = setInterval(check, 500);
    const timeoutHandle = setTimeout(() => {
      if (!finished) finish({ success: false, reason: 'timeout' });
    }, timeout_ms + 500);
    check(); // 立即检查一次（可能已在目标点）
  });
}

  // ── baritone 移植寻路（2026-08-15：A* + Moves 模型 + 控制键执行）──
  // 替代 mineflayer-pathfinder：支持爬升(ASCEND)/跳跃(PARKOUR)/下降(DESCEND)，
  // 解决用户实测「bot 不会跳、蹲搭寻路有问题」。
  async function baritone_move({ x, y, z, max_offset = 1, timeout_ms = 60000 } = {}) {
    try {
      const r = await pathTo(bot, x, y, z, {
        maxOffset: max_offset,
        timeoutMs: timeout_ms,
        onLog: (m) => console.log(`[baritone] ${m}`),
      });
      if (r.success) {
        return { success: true, reason: r.reason || 'done', position: r.position };
      }
      return {
        success: false,
        reason: r.reason || 'baritone_failed',
        position: r.position,
        path: (r.path || []).map(p => p.name),
      };
    } catch (err) {
      return { success: false, reason: 'baritone_error:' + err.message };
    }
  }

  return { move_to, walk_toward, look_at, get_player_state, cancel_pathing, is_player_nearby, set_control_state, look, jump, sneak, baritone_move };
}

module.exports = { createMovementHandlers };
