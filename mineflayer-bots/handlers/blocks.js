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

// 液体方块不能作为放置参考面（对齐 printer PrinterUtils.canBeClicked：无碰撞箱不可点击）
function isLiquidBlock(block) {
  const name = block?.name || '';
  return name.includes('water') || name.includes('lava') || name.includes('bubble_column');
}

// ── 2026-08-15 第二批（对齐 litematica-printer Action.getValidSide）──
// 交互方块（点击触发 GUI/交互，需潜行；作为参考面时排在最后，防误开箱子/工作台）
function isInteractiveBlock(block) {
  if (!block) return false;
  const name = block.name || '';
  return /chest|barrel|furnace|blast_furnace|smoker|brewing|hopper|dispenser|dropper|crafting_table|enchanting|anvil|door|trapdoor|fence_gate|note_block|jukebox|beacon|lectern|shulker|ender_chest|grindstone|smithing|stonecutter|loom|cartography|composter|cake|dragon_egg|bell|campfire|respawn|lodestone|daylight|cauldron|button|lever|chiseled_bookshelf|decorated_pot/.test(name);
}

// 参考方块有效性：非空气非液体即可。
// ⚠️ 2026-08-15 修正：去掉"不可替换"正则判定——宽泛子串正则（grass/redstone/root
// 等）会误伤 grass_block / redstone_block 等实心平台方块，导致 DOWN 参考被跳过、
// 平台上第一行放置全失败（No reference block）。对齐 printer canBeClicked 的
// 宽松语义：有方块（非空气非液体）即可作为放置参考；交互方块由调用方排序规避。
function isUsableReference(block) {
  if (!block || block.type === 0) return false;
  if (isLiquidBlock(block)) return false;
  return true;
}

// 下落方块（对齐 printer FALLING_CHECK：下方无支撑时放置后立即下落错位）
function isFallingBlockName(name) {
  return name.includes('sand') || name === 'gravel' || name.includes('concrete_powder');
}

function isAirLikeName(name) {
  return !name || name === 'air' || name === 'void_air' || name === 'cave_air';
}

/**
 * @param {import('mineflayer').Bot} bot
 */
function createBlockHandlers(bot) {

  // ── 本地强制更新方块（2026-08-15 P3：服务器放置成功但客户端 blockAt 未同步）──
  // 服务器接受放置后，用 prismarine-block 构造方块并 bot.world.setBlock 写入本地，
  // 让后续 verify / baritone A* 能读到正确状态（否则全是旧 air）。
  async function forceLocalBlock(pos, heldItem) {
    try {
      if (!heldItem || !pos) return;
      const Block = require('prismarine-block')(bot.version);
      const reg = bot.registry;
      const def = reg.blocksByName[heldItem.name];
      if (!def) return;
      // 构造本地方块（biome=0, metadata=0；世界刷新后服务器会覆盖为真实值）
      const nb = new Block(def.id, 0, 0, reg);
      nb.position = pos;
      bot.world.setBlock(pos, nb);
      // 同时广播 blockUpdate（让依赖该事件的逻辑感知）
      bot.emit('blockUpdate', nb, null);
    } catch (e) { /* 本地更新失败忽略 */ }
  }

  // ── 放置方块 ──
  // face: UP/DOWN/NORTH/SOUTH/WEST/EAST（点击参考方块的哪个面）
  //       AUTO = 自动选面：遍历候选面找第一个非空气、非液体的参考方块
  //              （对齐 litematica-printer Action.getValidSide 的简化版）
  // 自动选面候选优先级（地图画场景：bot 站行北缘 → 优先北面参考，其次下方地面，
  // 南面/行内/上方兜底）：
  //   SOUTH（ref=北面 z-1）→ DOWN（ref=下方）→ NORTH（ref=南面）
  //   → WEST/EAST（ref=行内 x±1）→ UP（ref=上方）
  async function place_block({ x, y, z, face = 'UP', trust_down = false } = {}) {
    try {
      const pos = new Vec3(x, y, z);
      const options = { trust_down };
      let faceVec = FACE_VECTORS[face] || FACE_VECTORS.UP;
      let refPos = pos.minus(faceVec);
      let refBlock = bot.blockAt(refPos);

      // 0. FALLING_CHECK（2026-08-15 第二批，对齐 litematica-printer）：
      //    下落方块（沙/砾石/混凝土粉末）下方无支撑时放置后立即下落错位 → 跳过并提示。
      const targetBlock = bot.blockAt(pos);
      const targetName = (targetBlock && targetBlock.name) || '';
      if (isFallingBlockName(targetName)) {
        const below = bot.blockAt(pos.offset(0, -1, 0));
        const belowName = (below && below.name) || 'air';
        if (isAirLikeName(belowName) || isLiquidBlock(below)) {
          return { success: false, error: `下落方块无支撑（${targetName} 下方为 ${belowName}），跳过` };
        }
      }

      // 1. 自动选面：face='AUTO' 或指定面参考不可用时，遍历候选面。
      //    2026-08-15 第二批升级（对齐 printer getValidSide）：
      //    - 参考必须「非空气非液体且不可替换」（isUsableReference，半砖/楼梯/按钮不再误当参考）
      //    - 优先「非交互方块」面（北面是箱子/工作台时不再误开 GUI，自动跳到其他面）
      const CANDIDATE_FACES = ['SOUTH', 'DOWN', 'NORTH', 'WEST', 'EAST', 'UP'];
      if (face === 'AUTO' || !isUsableReference(refBlock)) {
        let chosen = null;    // 首选：非交互方块面
        let fallback = null;  // 兜底：第一个可用面（可能是交互方块）
        for (const f of CANDIDATE_FACES) {
          const fv = FACE_VECTORS[f];
          const rp = pos.minus(fv);
          const rb = bot.blockAt(rp);
          if (!isUsableReference(rb)) continue;
          if (!fallback) fallback = { fv, rp, rb };
          if (!isInteractiveBlock(rb)) {
            chosen = { fv, rp, rb };
            break;
          }
        }
        const finalRef = chosen || fallback;
        if (finalRef) {
          faceVec = finalRef.fv;
          refPos = finalRef.rp;
          refBlock = finalRef.rb;
        }
      }

      if (!isUsableReference(refBlock)) {
        // 2026-08-15 修复：参考全失效可能是 chunk 未加载（传送后/跨 chunk 边界，
        // bot 刚落地 blockAt 读到 null/空气）→ 等 1.5s 重读一次（chunk 加载中），
        // 仍失效才走垫块兜底。
        await new Promise(r => setTimeout(r, 1500));
        refBlock = bot.blockAt(refPos);
        if (!isUsableReference(refBlock)) {
          // 重扫候选面（chunk 加载后可能已有参考）
          let chosen = null;
          let fallback = null;
          for (const f of CANDIDATE_FACES) {
            const fv = FACE_VECTORS[f];
            const rp = pos.minus(fv);
            const rb = bot.blockAt(rp);
            if (!isUsableReference(rb)) continue;
            if (!fallback) fallback = { fv, rp, rb };
            if (!isInteractiveBlock(rb)) { chosen = { fv, rp, rb }; break; }
          }
          const finalRef = chosen || fallback;
          if (finalRef) {
            faceVec = finalRef.fv;
            refPos = finalRef.rp;
            refBlock = finalRef.rb;
          }
        }
      }

      if (!isUsableReference(refBlock)) {
        // 2026-08-15 P3 关键：地图画场景 trust_down=true —— 目标正下方是平台
        // （服务器端真实存在），但客户端 blockAt 可能读到旧 air（重连后 Via chunk
        // 数据过期）→ 参考检测误判失效。信任服务器：直接以目标下方为参考发送
        // 放置请求（mineflayer placeBlock 用 refBlock.position，服务器端决定成败）。
        if (options.trust_down) {
          refPos = new Vec3(pos.x, pos.y - 1, pos.z);
          const rb = bot.blockAt(refPos);
          // 即使 rb 是 air 也构造参考（仅用 position），服务器端下方有平台即成功
          refBlock = rb || { position: refPos };
          faceVec = FACE_VECTORS.UP;
          if (rb && isUsableReference(rb)) {
            // 下方确实有参考（客户端读到）→ 直接放置
            // （继续走下方放置逻辑）
          }
          // 客户端读到 air：仍尝试放置（服务器端决定）；失败走垫块兜底
          try {
            if (bot.heldItem) {
              // 2026-08-15 P3：用 _genericPlace 直接发送放置请求（不等待 blockUpdate——
              // 经 Via 服务器放置成功但客户端可能收不到块更新，waitForUpdate 5s 必超时误判失败）
              await bot._genericPlace(refBlock, faceVec, { swingArm: 'right' });
              await forceLocalBlock(pos, bot.heldItem);
              console.log(`[place-diag] trust_down OK placed ${x},${y},${z}`);
              return { success: true, block: { x, y, z }, placed_with: bot.heldItem.name, face: 'DOWN' };
            }
          } catch (e) { /* trust_down 放置失败 → 走垫块 */ }
          // 信任失败（服务器端下方确无方块）→ 真实垫块兜底
          const padded = await padUnderTarget(pos);
          if (!padded) {
            return { success: false, error: `No reference block near ${pos}（自动垫块失败）` };
          }
          refPos = new Vec3(pos.x, pos.y - 1, pos.z);
          refBlock = bot.blockAt(refPos);
          faceVec = FACE_VECTORS.UP;
          if (!isUsableReference(refBlock)) {
            return { success: false, error: `垫块后仍无参考（${pos}）` };
          }
        } else {
          // 2026-08-15 修复「No reference block near」：目标方块周围全是空气
          // （地图画建在平台边缘/悬空处，目标正下方无地面支撑）——参考面全失效。
          // 用背包方块先垫到目标正下方（参考 = bot 脚下/附近的相邻实心方块），
          // 再以垫块为参考放置目标（对齐 litematica-printer PLACE_IN_AIR + Baritone
          // 自动搭支撑的简化实现）。
          const padded = await padUnderTarget(pos);
          if (!padded) {
            return { success: false, error: `No reference block near ${pos}（自动垫块失败）` };
          }
          // 垫块成功后：以垫块为参考（UP 面）放置目标
          refPos = new Vec3(pos.x, pos.y - 1, pos.z);
          refBlock = bot.blockAt(refPos);
          faceVec = FACE_VECTORS.UP;
          if (!isUsableReference(refBlock)) {
            return { success: false, error: `垫块后仍无参考（${pos}）` };
          }
        }
      }

      // 2. 检查手持物品
      if (!bot.heldItem) {
        return { success: false, error: 'No item in hand' };
      }

      // 3. 放置方块（2026-08-15 P3 关键：统一用 _genericPlace 直接发送放置请求——
      //    mineflayer 的 placeBlock 会 waitForUpdate 5s，经 Via 服务器放置成功但
      //    客户端收不到 blockUpdate → 必超时抛错误判失败。发出即成功（信任服务器），
      //    forceLocalBlock 本地标记供 verify/A* 读取。
      try {
        const bp = bot.entity?.position;
        console.log(`[place-diag] target=(${x},${y},${z}) ref=${refBlock.name || '?'}@(${refPos.x},${refPos.y},${refPos.z}) face=${faceVec} held=${bot.heldItem.name}x${bot.heldItem.count} botPos=(${bp ? bp.x.toFixed(2) : '?'},${bp ? bp.y.toFixed(2) : '?'},${bp ? bp.z.toFixed(2) : '?'}) ground=${bot.entity?.onGround}`);
      } catch (e) { /* 日志失败忽略 */ }
      await bot._genericPlace(refBlock, faceVec, { swingArm: 'right' });
      // 本地强制同步（服务器已放置，客户端 blockAt 可能未更新）
      try { await forceLocalBlock(pos, bot.heldItem); } catch (e) { /* 忽略 */ }
      console.log(`[place-diag] OK placed ${x},${y},${z}`);
      return { success: true, block: { x, y, z }, placed_with: bot.heldItem.name, face };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 自动垫参考块（2026-08-15：目标周围无参考面时，用背包方块垫到目标下方）──
  // 目标 (x,y,z) 正下方是空气/水时，找 bot 可触及的相邻实心方块作参考，把背包
  // 方块放到 (x,y-1,z)，让目标有 DOWN 参考面。返回 true 表示垫块成功。
  async function padUnderTarget(pos) {
    try {
      const blockItem = bot.inventory.items()
        .filter(i => i.name && i.name !== 'air' && i.count > 0)
        .sort((a, b) => (b.count || 0) - (a.count || 0))[0];
      if (!blockItem) return false;
      await bot.equip(blockItem, 'hand');
      await new Promise(r => setTimeout(r, 300));

      const below = new Vec3(pos.x, pos.y - 1, pos.z);
      // 候选参考面（从 bot 当前站位/目标下方附近找实心方块，点击其相邻面）
      const botPos = bot.entity?.position;
      const candidates = [];
      if (botPos) {
        const bx = Math.floor(botPos.x), by = Math.floor(botPos.y), bz = Math.floor(botPos.z);
        // bot 脚下及其 8 邻域（水平面），点击朝向 below 的方向
        for (let dx = -1; dx <= 1; dx++) {
          for (let dz = -1; dz <= 1; dz++) {
            const p = new Vec3(bx + dx, by - 1, bz + dz);
            if (p.distanceTo(below) <= 2.5) candidates.push(p);
          }
        }
        // bot 站立格同层（水平 8 邻域），可能用于垫目标正下方侧面
        for (let dx = -1; dx <= 1; dx++) {
          for (let dz = -1; dz <= 1; dz++) {
            const p = new Vec3(bx + dx, by, bz + dz);
            if (p.distanceTo(below) <= 2.5) candidates.push(p);
          }
        }
      }
      // 直接目标下方附近的方块（below 的 6 邻域）
      for (const d of [new Vec3(1,0,0), new Vec3(-1,0,0), new Vec3(0,0,1), new Vec3(0,0,-1), new Vec3(0,-1,0), new Vec3(0,1,0)]) {
        candidates.push(below.plus(d));
      }
      for (const ref of candidates) {
        const rb = bot.blockAt(ref);
        if (!rb || rb.type === 0 || isLiquidBlock(rb)) continue;
        const faceVec = below.minus(ref); // 从 ref 指向 below 的方向
        if (faceVec.x * faceVec.x + faceVec.y * faceVec.y + faceVec.z * faceVec.z !== 1) continue;
        try {
          await bot.placeBlock(rb, faceVec);
          await new Promise(r => setTimeout(r, 400));
          const placed = bot.blockAt(below);
          if (placed && placed.type !== 0) {
            // 2026-08-15 P3：垫块成功后本地同步（客户端 blockAt 可能未更新，
            // 否则垫块后参考检测仍读 air → 放置失败）
            try {
              const held = bot.heldItem;
              if (held) await forceLocalBlock(below, held);
            } catch (e) { /* 忽略 */ }
            return true;
          }
        } catch (e) { /* 尝试下一个候选 */ }
      }
      return false;
    } catch (err) {
      return false;
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
            // 注意：palette 是 stateId 数字数组，需 registry.blocksByStateId 转名字；
            // 若解析不出任何名字（registry 结构不匹配），保守处理为"含目标"逐格确认，
            // 避免误跳过导致漏扫（正确性优先于性能）。
            let hasMatch = false;
            let resolvedAny = false;
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
                if (nm) resolvedAny = true;
                if (matchSet) {
                  if (matchSet.has(base)) { hasMatch = true; break; }
                } else if (base && base !== 'air' && base !== 'cave_air' && base !== 'void_air') {
                  hasMatch = true; break;
                }
              }
              if (!resolvedAny) hasMatch = true;  // 全解析失败 → 保守逐格确认
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
