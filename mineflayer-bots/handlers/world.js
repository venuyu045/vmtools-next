/**
 * world.js — 世界查询 handler
 *
 * 方法：
 *   get_server_info()        → 返回服务器信息
 *   find_blocks(matching, max_count?) → 查找匹配的方块
 */

const { Vec3 } = require('vec3');

/**
 * @param {import('mineflayer').Bot} bot
 */
function createWorldHandlers(bot) {

  function get_server_info({} = {}) {
    return {
      success: true,
      server: bot._client?.socket?.remoteAddress || 'unknown',
      game_mode: bot.game?.gameMode || 'unknown',
      dimension: bot.game?.dimension || 'unknown',
      difficulty: bot.game?.difficulty || 'unknown',
      players: Object.keys(bot.players || {}).length,
      server_brand: bot.game?.serverBrand || 'unknown',
    };
  }

  function find_blocks({ matching, max_count = 100 } = {}) {
    try {
      if (!bot.entity) {
        return { success: false, error: 'Bot not spawned' };
      }
      if (!matching) {
        return { success: false, error: 'matching is required' };
      }

      // bot.findBlocks 需要 matching 为数字 ID 或函数
      let matchingFn;
      if (typeof matching === 'string') {
        // 按名称匹配
        matchingFn = (block) => block.name === matching;
      } else if (typeof matching === 'number') {
        matchingFn = (block) => block.type === matching;
      } else {
        return { success: false, error: 'matching must be string (name) or number (type id)' };
      }

      const matches = bot.findBlocks({
        matching: matchingFn,
        maxDistance: 64,
        count: max_count,
      });

      return { success: true, count: matches.length, blocks: matches };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  return { get_server_info, find_blocks };
}

module.exports = { createWorldHandlers };
