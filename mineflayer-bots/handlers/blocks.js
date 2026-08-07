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

  // ── 容器方块名集合（仓库扫描用） ──
  const CONTAINER_NAMES = new Set([
    'chest', 'trapped_chest', 'barrel', 'hopper', 'dispenser', 'dropper',
    'furnace', 'blast_furnace', 'smoker', 'brewing_stand', 'ender_chest',
    'shulker_box', 'white_shulker_box', 'orange_shulker_box', 'magenta_shulker_box',
    'light_blue_shulker_box', 'yellow_shulker_box', 'lime_shulker_box',
    'pink_shulker_box', 'gray_shulker_box', 'light_gray_shulker_box',
    'cyan_shulker_box', 'purple_shulker_box', 'blue_shulker_box',
    'brown_shulker_box', 'green_shulker_box', 'red_shulker_box', 'black_shulker_box',
  ]);

  // ── 扫描已加载区块内的全部容器（不受 ±15 格限制） ──
  // 遍历 bot 已加载的所有区块（范围由服务器下发区块的视野决定，通常
  // view-distance 6~12 区块 = 96~192 格半径），用 section palette 快速过滤
  // 含容器的区块段，再逐格确认容器方块坐标。
  // 读取阶段仍走 Servux（服务端读 NBT，不受距离限制），这里只负责"发现坐标"。
  function scan_loaded_containers({ max_count = 10000 } = {}) {
    try {
      if (!bot.entity) {
        return { success: false, error: 'Bot not spawned' };
      }

      const blocks = [];
      // prismarine-world: columns 是 {"chunkX,chunkZ": chunk} 普通对象；
      // getColumns() 返回 [{chunkX, chunkZ, column}]（推荐），否则从 key 解析。
      let cols = [];
      try { cols = bot.world.getColumns() || []; } catch (e) { console.log('[scan_loaded] getColumns err:', e.message); }
      if (!cols.length && bot.world.columns) {
        cols = Object.entries(bot.world.columns).map(([key, column]) => {
          const parts = String(key).split(',');
          return { chunkX: Number(parts[0]), chunkZ: Number(parts[1]), column };
        });
      }
      let totalSections = 0;
      let samplePalette = '';
      let paletteKeys = '';
      let hitSections = 0;
      let blockNameSample = '';
      const _registry = bot.registry || {};
      const _bbsid = _registry.blocksByStateId || {};
      const _stateId85 = _bbsid[85] ? (_bbsid[85].name || '?') : '(none)';
      for (const { column: col } of cols) {
        const secs = (col && col.sections) || [];
        for (const s of secs) {
          if (!s) continue;
          totalSections++;
          if (!samplePalette && s.palette) {
            samplePalette = JSON.stringify(Array.isArray(s.palette) ? s.palette.slice(0, 3) : s.palette).slice(0, 200);
            paletteKeys = Object.keys(s).join(',');
          }
        }
      }
      console.log('[scan_loaded] cols=', cols.length, 'sections=', totalSections,
                  'palette=', samplePalette, 'sectionKeys=', paletteKeys,
                  'registryKeys=', Object.keys(_registry).slice(0, 12).join(','),
                  'stateId85=', _stateId85);

      for (const { chunkX, chunkZ, column: col } of cols) {
        if (!col || chunkX === undefined || chunkZ === undefined) continue;
        if (blocks.length >= max_count) break;

        const baseX = chunkX * 16;
        const baseZ = chunkZ * 16;
        const sections = col.sections || [];
        for (let si = 0; si < sections.length; si++) {
          const section = sections[si];
          if (!section) continue;
          if (blocks.length >= max_count) break;

          // palette 快速过滤：该区块段不含容器方块则整段跳过（避免逐格 getBlock）
          // prismarine-chunk palette 是 stateId 数字数组，需经 registry 转方块名
          let hasContainer = false;
          try {
            const registry = bot.registry || {};
            const blocksByStateId = registry.blocksByStateId || {};
            const palette = section.palette || [];
            for (const p of palette) {
              let nm = '';
              if (typeof p === 'number' || typeof p === 'bigint') {
                const b = blocksByStateId[Number(p)];
                nm = (b && b.name) || '';
              } else if (typeof p === 'string') {
                nm = p;
              } else if (p && (p.name || p.Name)) {
                nm = p.name || p.Name;
              }
              const base = String(nm).includes(':') ? String(nm).split(':')[1] : nm;
              if (CONTAINER_NAMES.has(base)) { hasContainer = true; hitSections++; break; }
            }
          } catch { hasContainer = true; }

          if (!hasContainer) continue;

          const secY = si * 16;
          // chunk.getBlock(x, y, z)：x/z 为区块内局部坐标(0-15)，y 为绝对高度
          for (let ly = 0; ly < 16 && blocks.length < max_count; ly++) {
            for (let lx = 0; lx < 16 && blocks.length < max_count; lx++) {
              for (let lz = 0; lz < 16 && blocks.length < max_count; lz++) {
                const wx = baseX + lx, wy = secY + ly, wz = baseZ + lz;
                let blk = null;
                try { blk = col.getBlock(new Vec3(lx, wy, lz)); } catch {}
                if (blk) {
                  const bname = String(blk.name || '');
                  if (!blockNameSample && bname) blockNameSample = bname;
                  const bbase = bname.includes(':') ? bname.split(':')[1] : bname;
                  if (CONTAINER_NAMES.has(bbase)) {
                    blocks.push({ x: wx, y: wy, z: wz, name: blk.name, type: blk.type });
                  }
                }
              }
            }
          }
        }
      }

      console.log('[scan_loaded] found=', blocks.length);
      return { success: true, count: blocks.length, blocks, debug: { cols: cols.length, sections: totalSections, hitSections, blockNameSample, palette: samplePalette, stateId85: _stateId85 } };
    } catch (err) {
      console.error('[scan_loaded] error:', err.message, err.stack);
      return { success: false, error: err.message };
    }
  }

  return { place_block, dig_block, get_world_block_at, scan_nearby_blocks, scan_loaded_containers };
}

module.exports = { createBlockHandlers };
