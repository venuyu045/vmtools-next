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
  // 性能优化：按 chunk 的 section palette 快速过滤——只对含目标方块的 section
  // 逐格确认坐标，仓库类容器集中场景提速数十倍。
  // 支持两种范围模式：
  //   1) radius：以 bot 为中心 ±radius 包围盒（默认）
  //   2) box：显式 box_min_x/box_max_x/... 按给定范围遍历（适合 zone 已知场景，
  //      避免绕 bot 中心遍历大量无关区块）。max_count 默认 500000，支持超大仓库。
  function scan_nearby_blocks({ radius = 16, max_count = 500000, matching = null,
                                 box_min_x, box_max_x, box_min_y, box_max_y, box_min_z, box_max_z } = {}) {
    try {
      if (!bot.entity) {
        return { success: false, error: 'Bot not spawned' };
      }
      const pos = bot.entity.position;

      const blocks = [];
      let minX, maxX, minY, maxY, minZ, maxZ;
      if (box_min_x !== undefined) {
        minX = Math.floor(box_min_x); maxX = Math.ceil(box_max_x);
        minY = Math.max(0, Math.floor(box_min_y)); maxY = Math.min(255, Math.ceil(box_max_y));
        minZ = Math.floor(box_min_z); maxZ = Math.ceil(box_max_z);
      } else {
        minX = Math.floor(pos.x - radius);
        maxX = Math.ceil(pos.x + radius);
        minY = Math.max(0, Math.floor(pos.y - radius));
        maxY = Math.min(255, Math.ceil(pos.y + radius));
        minZ = Math.floor(pos.z - radius);
        maxZ = Math.ceil(pos.z + radius);
      }

      // matching 名集合（去命名空间前缀，兼容 "minecraft:chest" / "chest"）
      let matchSet = null;
      if (matching) {
        const names = String(matching).split(',').map(s => s.trim()).filter(Boolean);
        if (names.length > 0) {
          matchSet = new Set(names.map(n => String(n).includes(':') ? String(n).split(':')[1] : n));
        }
      }

      const registry = bot.registry || {};
      const blocksByStateId = registry.blocksByStateId || {};

      const chunkMinX = Math.floor(minX / 16), chunkMaxX = Math.floor(maxX / 16);
      const chunkMinZ = Math.floor(minZ / 16), chunkMaxZ = Math.floor(maxZ / 16);

      for (let cx = chunkMinX; cx <= chunkMaxX && blocks.length < max_count; cx++) {
        for (let cz = chunkMinZ; cz <= chunkMaxZ && blocks.length < max_count; cz++) {
          let col = null;
          try { col = bot.world.getColumn(cx, cz); } catch (e) { col = null; }
          if (!col && bot.world.columns) col = bot.world.columns[`${cx},${cz}`];
          if (!col) continue;

          const sections = col.sections || [];
          for (let si = 0; si < sections.length && blocks.length < max_count; si++) {
            const section = sections[si];
            if (!section) continue;

            // palette 快速过滤：该区块段不含目标方块则整段跳过
            let hasMatch = false;
            try {
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
                if (matchSet) {
                  if (matchSet.has(base)) { hasMatch = true; break; }
                } else if (base && base !== 'air' && base !== 'cave_air' && base !== 'void_air') {
                  hasMatch = true; break;
                }
              }
            } catch { hasMatch = true; }

            if (!hasMatch) continue;

            // 逐格确认该 section 与扫描范围的交集
            const baseX = cx * 16, baseZ = cz * 16, secY = si * 16;
            const lx0 = Math.max(0, minX - baseX), lx1 = Math.min(15, maxX - baseX);
            const ly0 = Math.max(0, minY - secY), ly1 = Math.min(15, maxY - secY);
            const lz0 = Math.max(0, minZ - baseZ), lz1 = Math.min(15, maxZ - baseZ);
            for (let ly = ly0; ly <= ly1 && blocks.length < max_count; ly++) {
              for (let lx = lx0; lx <= lx1 && blocks.length < max_count; lx++) {
                for (let lz = lz0; lz <= lz1 && blocks.length < max_count; lz++) {
                  const wx = baseX + lx, wy = secY + ly, wz = baseZ + lz;
                  let blk = null;
                  try { blk = bot.blockAt(new Vec3(wx, wy, wz)); } catch {}
                  if (!blk || blk.type === 0) continue;
                  const bname = String(blk.name || '');
                  const bbase = bname.includes(':') ? bname.split(':')[1] : bname;
                  if (matchSet && !matchSet.has(bbase)) continue;
                  blocks.push({ x: wx, y: wy, z: wz, name: blk.name, type: blk.type });
                }
              }
            }
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
  function scan_loaded_containers({ max_count = 100000 } = {}) {
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
          // bot.blockAt 读已加载区块方块（mineflayer 公开 API，数据可靠）
          for (let ly = 0; ly < 16 && blocks.length < max_count; ly++) {
            for (let lx = 0; lx < 16 && blocks.length < max_count; lx++) {
              for (let lz = 0; lz < 16 && blocks.length < max_count; lz++) {
                const wx = baseX + lx, wy = secY + ly, wz = baseZ + lz;
                let blk = null;
                try { blk = bot.blockAt(new Vec3(wx, wy, wz)); } catch {}
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
