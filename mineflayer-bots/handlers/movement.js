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
const { GoalNear, GoalBlock } = require('mineflayer-pathfinder').goals;

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
  async function move_to({ x, y, z, max_offset = 3, timeout_ms = 15000 }) {
    return new Promise((resolve, reject) => {
      const goal = new GoalNear(x, y, z, max_offset);
      let finished = false;
      let timer = null;

      const cleanup = () => {
        bot.removeListener('goal_reached', onGoalReached);
        bot.removeListener('path_stop', onStopped);
        bot.removeListener('path_timeout', onTimeout);
      };
      const finish = (result) => {
        if (finished) return;
        finished = true;
        if (timer) clearTimeout(timer);
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
      }, timeout_ms);

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

return { move_to, look_at, get_player_state, cancel_pathing, is_player_nearby, set_control_state, look, jump, sneak };
}

module.exports = { createMovementHandlers };
