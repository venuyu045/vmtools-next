/**
 * world.js — baritone 风格世界模型（从 mineflayer bot 读取方块）
 *
 * 移植自 baritone MovementHelper（canWalkOn / canWalkThrough / fullyPassable）：
 * 用格子世界抽象判定「某格能否站立 / 能否穿过」，供寻路器与移动执行使用。
 * 方块分类（地图画/平台场景）：
 *   - solid     ：有碰撞箱的实体方块（混凝土/石头/泥土等）→ 可站立
 *   - passable  ：可穿过的方块（空气/草丛/地毯等）
 *   - liquid    ：水/岩浆（游泳；站立判定特殊）
 *   - climbable ：梯子/藤蔓（攀爬）
 */

// 液体方块名（含后缀 _water/_lava 或纯水）
const LIQUID_RE = /(water|flowing_water|lava|flowing_lava|bubble_column)/;
// 明确可站立的方块（有完整碰撞箱的实体方块）；未命中时按 boundingBox 判断
const SOLID_HINTS = new Set([
  'grass_block', 'dirt', 'stone', 'cobblestone', 'andesite', 'granite', 'diorite',
  'sand', 'sandstone', 'gravel', 'clay', 'terracotta', 'white_terracotta',
  'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks',
  'oak_log', 'spruce_log', 'birch_log', 'jungle_log',
  'white_concrete', 'orange_concrete', 'magenta_concrete', 'light_blue_concrete',
  'yellow_concrete', 'lime_concrete', 'pink_concrete', 'gray_concrete',
  'light_gray_concrete', 'cyan_concrete', 'purple_concrete', 'blue_concrete',
  'brown_concrete', 'green_concrete', 'red_concrete', 'black_concrete',
  'white_wool', 'orange_wool', 'magenta_wool', 'light_blue_wool',
  'yellow_wool', 'lime_wool', 'pink_wool', 'gray_wool',
  'light_gray_wool', 'cyan_wool', 'purple_wool', 'blue_wool',
  'brown_wool', 'green_wool', 'red_wool', 'black_wool',
  'glass', 'obsidian', 'netherrack', 'bricks', 'stone_bricks',
  'smooth_stone', 'polished_andesite', 'quartz_block', 'iron_block',
  'gold_block', 'diamond_block', 'emerald_block', 'coal_block',
  'deepslate', 'cobbled_deepslate', 'tuff', 'calcite', 'dripstone_block',
  'mud', 'packed_mud', 'mud_bricks', 'mangrove_planks', 'mangrove_log',
  'crimson_planks', 'warped_planks', 'crimson_nylium', 'warped_nylium',
  'end_stone', 'purpur_block', 'purpur_pillar', 'prismarine', 'sea_lantern',
]);
// 明确可穿过的方块（空气/非实体）
const PASSABLE_HINTS = new Set([
  'air', 'cave_air', 'void_air', 'grass', 'tall_grass', 'fern', 'large_fern',
  'dead_bush', 'poppy', 'dandelion', 'torch', 'wall_torch', 'redstone_torch',
  'redstone_wire', 'carpet', 'white_carpet', 'snow', 'sugar_cane',
  'bamboo', 'bamboo_sapling', 'vine', 'ladder', 'rail', 'water', 'lava',
  'bubble_column', 'cobweb', 'end_rod', 'flower_pot', 'lever', 'button',
  'stone_button', 'tripwire', 'tripwire_hook', 'redstone',
]);

function isLiquid(name) { return LIQUID_RE.test(name || ''); }
function isClimbable(name) { return name === 'ladder' || name === 'vine'; }

/**
 * 解析方块为 world 可用的分类对象。
 * @param {object|null} block mineflayer block（或 null=未知/未加载）
 * @returns {{name:string, solid:boolean, passable:boolean, liquid:boolean, climbable:boolean, loaded:boolean}}
 */
function classify(block) {
  if (!block) {
    return { name: null, solid: false, passable: true, liquid: false, climbable: false, loaded: false };
  }
  const name = block.name || '';
  const bb = block.boundingBox || 'block';
  let solid = false;
  let passable = false;
  if (SOLID_HINTS.has(name)) {
    solid = true;
  } else if (PASSABLE_HINTS.has(name)) {
    passable = true;
  } else {
    // 兜底：mineflayer boundingBox 语义（'block'=完整方块,'empty'=可穿过,'liquid'=液体）
    if (isLiquid(name)) {
      passable = true; // 液体视为可穿过（游泳/不阻挡寻路，成本惩罚）
    } else if (bb === 'empty' || bb === 'cross' || bb === 'non-full') {
      passable = true;
    } else if (bb === 'block') {
      solid = true;
    } else {
      passable = true; // 未知类型默认可穿过（避免误判为墙）
    }
  }
  return {
    name,
    solid,
    passable,
    liquid: isLiquid(name),
    climbable: isClimbable(name),
    loaded: true,
  };
}

/**
 * world 实例：绑定 bot，提供 blockAt / canWalkOn / canWalkThrough。
 * 带 LRU 缓存（同一坐标短时重复读取免 WS/实体查询开销）。
 */
class World {
  constructor(bot) {
    this.bot = bot;
    this._cache = new Map();
    this._cacheMax = 4096;
  }

  _key(x, y, z) { return x + ',' + y + ',' + z; }

  clearCache() { this._cache.clear(); }

  blockAt(x, y, z) {
    const key = this._key(x, y, z);
    if (this._cache.has(key)) return this._cache.get(key);
    let b = null;
    try {
      b = this.bot.blockAt(new (require('vec3'))(x, y, z));
    } catch (e) { /* 未加载/异常 */ }
    const c = classify(b);
    if (this._cache.size > this._cacheMax) this._cache.clear();
    this._cache.set(key, c);
    return c;
  }

  /** 目标格 (x,y,z) 的方块顶能否站立（站在该方块上） */
  canWalkOn(x, y, z) {
    const b = this.blockAt(x, y, z);
    // 2026-08-16 P0-1：未加载块保守判定——不再乐观放行（原 return true 会让 A*
    // 在空 chunk 上规划踩空路径）。配合 pathfinder.js 走廊预检（确保路径区域
    // chunk 已加载），正常路径仍可用；未加载区域强制不可走 → A* 绕开或 no_path
    // → 由调用方等 chunk 后重试。
    if (!b.loaded) return false;
    return b.solid;
  }

  /** 目标格 (x,y,z) 的方块能否穿过（身体/头空间） */
  canWalkThrough(x, y, z) {
    const b = this.blockAt(x, y, z);
    if (!b.loaded) return false;
    return b.passable;
  }

  /** 完全可穿过（可跳跃通过；液体/爬行物不算） */
  fullyPassable(x, y, z) {
    const b = this.blockAt(x, y, z);
    if (!b.loaded) return true;
    return b.passable && !b.liquid && !b.climbable;
  }

  /** chunk 是否已加载（粗略：blockAt 有数据） */
  isLoaded(x, z) {
    return this.blockAt(x, 0, z).loaded;
  }

  /**
   * 水平移动的「标准 2 高」合法性检查（baritone MovementTraverse/MovementHelper）：
   * 目标站立面 (dx, y-1, dz) 能站 + 身体空间 (dx,y,dz) 与 (dx,y+1,dz) 能穿过。
   */
  canTraverse(dx, dy, dz, fromY) {
    const standY = dy - 1;
    if (!this.canWalkOn(dx, standY, dz)) return false;
    if (!this.canWalkThrough(dx, dy, dz)) return false;
    if (!this.canWalkThrough(dx, dy + 1, dz)) return false;
    return true;
  }
}

module.exports = { World, classify, isLiquid };
