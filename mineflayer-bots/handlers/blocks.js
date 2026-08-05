/**
 * blocks.js — 方块操作 handler
 *
 * 方法：
 *   place_block(x, y, z, face?)              → 放置方块
 *   dig_block(x, y, z)                       → 挖掘方块
 *   get_world_block_at(x, y, z)              → 获取方块信息
 *   scan_nearby_blocks(radius?, max_count?, matching?) → 扫描附近方块
 */

const { Vec3 } = require('vec3');

// 放置面的方向向量映射
const FACE_VECTORS = {
  'DOWN':  new Vec3(0, -1, 0),
  'UP':    new Vec3(0, 1, 0),
  'NORTH': new Vec3(0, 0, -1),
  'SOUTH': new Vec3(0, 0, 1),
  'WEST':  new Vec3(-1, 0, 0),
  'EAST':  new Vec3(1, 0, 0),
};

/**
 * @param {import('mineflayer').Bot} bot
 */
function createBlockHandlers(bot) {

  // ── 放置方块 ──
  async function place_block({ x, y, z, face = 'UP' } = {}) {
    try {
      const pos = new Vec3(x, y, z);
      const faceVec = FACE_VECTORS[face] || FACE_VECTORS.UP;

      // 1. 获取参考方块位置（放置面的反方向）
      const refPos = pos.minus(faceVec);
      const refBlock = bot.blockAt(refPos);

      if (!refBlock) {
        return { success: false, error: `No reference block at ${refPos}` };
      }

      // 2. 检查手持物品
      if (!bot.heldItem) {
        return { success: false, error: 'No item in hand' };
      }

      // 3. 放置方块
      await bot.placeBlock(refBlock, faceVec);
      return { success: true, block: { x, y, z }, placed_with: bot.heldItem.name };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 挖掘方块 ──
  async function dig_block({ x, y, z } = {}) {
    try {
      const pos = new Vec3(x, y, z);
      const block = bot.blockAt(pos);

      if (!block || block.type === 0) {
        return { success: false, error: `No block at (${x},${y},${z})` };
      }

      await bot.dig(block);
      return { success: true, dug: { name: block.name, type: block.type }, position: { x, y, z } };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 获取方块信息 ──
  function get_world_block_at({ x, y, z } = {}) {
    try {
      const pos = new Vec3(x, y, z);
      const block = bot.blockAt(pos);
      if (!block || block.type === 0) {
        return { success: true, exists: false, name: 'air', type: 0 };
      }
      return {
        success: true,
        exists: true,
        name: block.name,
        type: block.type,
        state_id: block.stateId,
        metadata: block.metadata,
        light: block.light,
        sky_light: block.skyLight,
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 扫描附近方块 ──
  function scan_nearby_blocks({ radius = 16, max_count = 100, matching = null } = {}) {
    try {
      if (!bot.entity) {
        return { success: false, error: 'Bot not spawned' };
      }
      const pos = bot.entity.position;

      const blocks = [];
      // 遍历包围盒
      const minX = Math.floor(pos.x - radius);
      const maxX = Math.ceil(pos.x + radius);
      const minY = Math.max(0, Math.floor(pos.y - radius));
      const maxY = Math.min(255, Math.ceil(pos.y + radius));
      const minZ = Math.floor(pos.z - radius);
      const maxZ = Math.ceil(pos.z + radius);

      for (let bx = minX; bx <= maxX && blocks.length < max_count; bx++) {
        for (let by = minY; by <= maxY && blocks.length < max_count; by++) {
          for (let bz = minZ; bz <= maxZ && blocks.length < max_count; bz++) {
            const block = bot.blockAt(new Vec3(bx, by, bz));
            if (!block || block.type === 0) continue;

            // 如果指定了 matching 过滤（支持逗号分隔的多个方块名，如 "chest,barrel"）
            if (matching) {
              const names = String(matching).split(',').map(s => s.trim()).filter(Boolean);
              if (names.length > 0 && !names.includes(block.name)) continue;
            }

            blocks.push({
              x: bx, y: by, z: bz,
              name: block.name,
              type: block.type,
            });
          }
        }
      }

      return { success: true, count: blocks.length, blocks };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  return { place_block, dig_block, get_world_block_at, scan_nearby_blocks };
}

module.exports = { createBlockHandlers };
