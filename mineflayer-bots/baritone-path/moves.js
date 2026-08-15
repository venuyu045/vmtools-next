/**
 * moves.js — baritone Moves 枚举的 JS 版（移动类型 + 合法性 + 成本）
 *
 * 状态空间 = 3D 方块格 (x, y, z)，y 为 bot「脚所在格」：bot 站在 (x, y-1, z) 方块顶。
 * 每个 Move 定义：目标偏移 + 合法条件（canWalkOn/canWalkThrough）+ 成本。
 * 移植自 baritone Moves / MovementTraverse / MovementAscend / MovementDescend /
 * MovementDiagonal / MovementParkour / MovementPillar / MovementDownward。
 *
 * 成本常量（baritone ActionCosts）：
 *   WALK_ONE_BLOCK_COST = 20，斜走 = 20*√2 ≈ 28.284，爬升 = 20，跳跃有额外惩罚。
 */

const { Vec3 } = require('vec3');
// 与 world.js 的方块分类共用
const { classify } = require('./world');

const WALK_ONE_BLOCK_COST = 20;
const WALK_ONE_BLOCK_COST_DIAG = 20 * Math.SQRT2;
const ASCEND_COST = 20;
const DESCEND_COST = 20;
const PARKOUR_JUMP_COST = 20 * 3;
const COST_INF = Infinity;

/**
 * 构造一个 Move 描述。
 * @param {string} name
 * @param {number} dx @param {number} dy @param {number} dz 目标偏移（相对 bot 脚格）
 * @param {function} valid (world, x, y, z) → boolean  从 (x,y,z) 出发该移动是否合法
 * @param {function} cost  (world, x, y, z) → number    移动成本（INF=不可达）
 */
function makeMove(name, dx, dy, dz, valid, cost) {
  return { name, dx, dy, dz, valid, cost };
}

/** 判断 dest 站立面 (dx, y-1, dz) 能站 + 身体空间 (dx,y,dz)/(dx,y+1,dz) 能穿过 */
function standableAt(world, dx, y, dz) {
  if (!world.canWalkOn(dx, y - 1, dz)) return false;
  if (!world.canWalkThrough(dx, y, dz)) return false;
  if (!world.canWalkThrough(dx, y + 1, dz)) return false;
  return true;
}

/** 水平基础合法性：dest 站立面能站 + 空间能穿过（同层行走） */
function traverseValid(world, x, y, z, dx, dz) {
  return standableAt(world, x + dx, y, z + dz);
}

/** 爬升合法：目标 (dx, y+1, dz) 站立面能站 + 身体空间能穿过 + 源上方空间能穿过 */
function ascendValid(world, x, y, z, dx, dz) {
  const nx = x + dx, nz = z + dz;
  if (!world.canWalkOn(nx, y, nz)) return false;               // 目标站立面（y 层）
  if (!world.canWalkThrough(nx, y + 1, nz)) return false;      // 目标身体空间
  if (!world.canWalkThrough(nx, y + 2, nz)) return false;      // 目标头空间
  if (!world.canWalkThrough(x, y + 1, z)) return false;        // 源上方（跳起空间）
  if (!world.canWalkThrough(x, y + 2, z)) return false;
  return true;
}

/** 下降合法：目标 (dx, y-1, dz) 站立面能站 + 空间能穿过 + 落差 ≤ 1（超过走 DESCEND 多格） */
function descendValid(world, x, y, z, dx, dz) {
  const nx = x + dx, nz = z + dz;
  if (!world.canWalkOn(nx, y - 2, nz)) return false;           // 目标站立面（y-1 层）
  if (!world.canWalkThrough(nx, y - 1, nz)) return false;      // 目标身体空间
  if (!world.canWalkThrough(nx, y, nz)) return false;          // 目标头空间
  return true;
}

/** 斜走合法：两个相邻水平格都满足 traverse（baritone 对角线要求两侧都能走） */
function diagonalValid(world, x, y, z, dx, dz) {
  const nx = x + dx, nz = z + dz;
  if (!standableAt(world, nx, y, nz)) return false;            // 对角目标
  if (!standableAt(world, x + dx, y, z)) return false;         // X 侧邻格（防穿角）
  if (!standableAt(world, x, y, nz)) return false;             // Z 侧邻格
  return true;
}

/**
 * 跳跃合法（baritone MovementParkour）：跨过 1~3 格空隙落在对岸。
 * @param {number} gap 跳跃距离（1-3 格：跳过的空格数）
 */
function parkourValid(world, x, y, z, dx, dz, gap) {
  const nx = x + dx * gap, nz = z + dz * gap;
  // 落点站立面能站
  if (!world.canWalkOn(nx, y - 1, nz)) return false;
  // 起跳点边缘空间 + 空中路径 + 落点空间
  const stepX = Math.sign(dx), stepZ = Math.sign(dz);
  for (let i = 1; i <= gap; i++) {
    const mx = x + stepX * i, mz = z + stepZ * i;
    if (!world.canWalkThrough(mx, y, mz)) return false;
    if (!world.canWalkThrough(mx, y + 1, mz)) return false;
  }
  // 起跳空间（bot 所在格上方）
  if (!world.canWalkThrough(x, y + 1, z)) return false;
  return true;
}

/** 搭柱合法（PILLAR）：源上方空间能穿过 + 目标上方能穿过（从脚下方块上搭） */
function pillarValid(world, x, y, z) {
  // bot 站在 (x,y-1,z)，向上搭需要：bot 所在格上方能穿过（bot 跳起）
  if (!world.canWalkThrough(x, y + 1, z)) return false;
  if (!world.canWalkThrough(x, y + 2, z)) return false;
  return true;
}

/** 垂直下降合法（DOWNWARD）：下方一格能穿过 + 再下方能站 */
function downwardValid(world, x, y, z) {
  if (!world.canWalkThrough(x, y - 1, z)) return false;
  if (!world.canWalkOn(x, y - 2, z)) return false;
  return true;
}

/** 全部 Moves（对齐 baritone Moves 枚举；24 种，不含 BRIDGE/DOWNWARD 特殊分支） */
function allMoves() {
  const D = [[1, 0], [-1, 0], [0, 1], [0, -1]]; // E/W/S/N
  const D2 = [[1, 1], [1, -1], [-1, 1], [-1, -1]]; // 对角
  const moves = [];
  for (const [dx, dz] of D) {
    moves.push(makeMove('TRAVERSE_' + dirName(dx, dz), dx, 0, dz,
      (w, x, y, z) => traverseValid(w, x, y, z, dx, dz),
      () => WALK_ONE_BLOCK_COST));
    moves.push(makeMove('ASCEND_' + dirName(dx, dz), dx, 1, dz,
      (w, x, y, z) => ascendValid(w, x, y, z, dx, dz),
      () => ASCEND_COST));
    moves.push(makeMove('DESCEND_' + dirName(dx, dz), dx, -1, dz,
      (w, x, y, z) => descendValid(w, x, y, z, dx, dz),
      () => DESCEND_COST));
    // PARKOUR：1/2/3 格跨距（baritone 动态跳跃距离，拆成固定跨距便于 A* 展开）
    for (const gap of [1, 2, 3]) {
      moves.push(makeMove(`PARKOUR${gap}_` + dirName(dx, dz), dx * gap, 0, dz * gap,
        (w, x, y, z, gx, gz) => parkourValid(w, x, y, z, dx, dz, gap),
        () => PARKOUR_JUMP_COST + gap * 10));
    }
  }
  for (const [dx, dz] of D2) {
    moves.push(makeMove('DIAGONAL_' + dirName(dx, dz), dx, 0, dz,
      (w, x, y, z) => diagonalValid(w, x, y, z, dx, dz),
      () => WALK_ONE_BLOCK_COST_DIAG));
  }
  moves.push(makeMove('PILLAR', 0, 1, 0, pillarValid, () => ASCEND_COST + 10));
  moves.push(makeMove('DOWNWARD', 0, -1, 0, downwardValid, () => DESCEND_COST));
  return moves;
}

function dirName(dx, dz) {
  if (dx === 0 && dz === -1) return 'N';
  if (dx === 0 && dz === 1) return 'S';
  if (dx === 1 && dz === 0) return 'E';
  if (dx === -1 && dz === 0) return 'W';
  if (dx === 1 && dz === 1) return 'SE';
  if (dx === 1 && dz === -1) return 'NE';
  if (dx === -1 && dz === 1) return 'SW';
  if (dx === -1 && dz === -1) return 'NW';
  return '?';
}

module.exports = { allMoves, WALK_ONE_BLOCK_COST, COST_INF };