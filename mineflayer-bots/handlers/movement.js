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
  async function move_to({ x, y, z, max_offset = 3, timeout_ms = 15000 }) {
    return new Promise((resolve, reject) => {
      const goal = new GoalNear(x, y, z, max_offset);
      const timeout = setTimeout(() => {
        bot.pathfinder.stop();
        pathfindingResolver = null;
        resolve({ success: false, reason: 'timeout', position: getPos() });
      }, timeout_ms);

      pathfindingResolver = (result) => {
        clearTimeout(timeout);
        pathfindingResolver = null;
        resolve(result);
      };

      // 监听路径事件
      const onGoalReached = () => {
        const r = pathfindingResolver;
        if (r) r({ success: true, position: getPos() });
      };
      const onStopped = () => {
        const r = pathfindingResolver;
        if (r) r({ success: false, reason: 'stopped', position: getPos() });
      };
      const onTimeout = () => {
        const r = pathfindingResolver;
        if (r) r({ success: false, reason: 'timeout', position: getPos() });
      };

      bot.once('goal_reached', onGoalReached);
      bot.once('path_stop', onStopped);
      bot.once('path_timeout', onTimeout);

      try {
        bot.pathfinder.setGoal(goal);
      } catch (err) {
        clearTimeout(timeout);
        bot.removeListener('goal_reached', onGoalReached);
        bot.removeListener('path_stop', onStopped);
        bot.removeListener('path_timeout', onTimeout);
        reject(err);
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

  return { move_to, look_at, get_player_state, cancel_pathing, is_player_nearby };
}

module.exports = { createMovementHandlers };
