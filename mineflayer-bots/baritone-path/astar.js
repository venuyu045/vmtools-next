/**
 * astar.js — baritone AStarPathFinder 的 JS 版（二叉堆开放集 + 展开 Moves）
 *
 * 移植自 baritone AStarPathFinder / BinaryHeapOpenSet / PathNode：
 *   - 开放集用二叉堆（f = g + h 最小优先）
 *   - 从起点展开全部 Moves（24 种），valid 通过且 cost < INF 的加入开放集
 *   - 目标判定（GoalNear）：水平距离 ≤ maxOffset 且 y 偏差 ≤ yTol
 * 返回：movement 序列 [{name, dx, dy, dz, from, to}]。
 */

const { allMoves, COST_INF } = require('./moves');

/** 最小二叉堆（f 值最小优先） */
class BinaryHeap {
  constructor() { this._a = []; }
  get size() { return this._a.length; }
  isEmpty() { return this._a.length === 0; }
  push(node) {
    const a = this._a;
    a.push(node);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p].f <= a[i].f) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop() {
    const a = this._a;
    if (a.length === 0) return null;
    const top = a[0];
    const last = a.pop();
    if (a.length > 0) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = 2 * i + 2;
        let m = i;
        if (l < a.length && a[l].f < a[m].f) m = l;
        if (r < a.length && a[r].f < a[m].f) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

/** 曼哈顿启发（可采纳：水平 20/格，垂直 20/格） */
function heuristic(dx, dy, dz) {
  return (Math.abs(dx) + Math.abs(dz)) * 20 + Math.abs(dy) * 20;
}

/**
 * A* 寻路。
 * @param {World} world
 * @param {{x:number,y:number,z:number}} start bot 脚格（bot 站在 (x,y-1,z)）
 * @param {number} goalX @param {number} goalY @param {number} goalZ 目标（方块坐标）
 * @param {number} maxOffset 水平容差
 * @param {number} maxNodes 搜索节点上限（防爆炸）
 * @returns {null|Array<{name,dx,dy,dz,from,to}>}
 */
function findPath(world, start, goalX, goalY, goalZ, maxOffset = 1, maxNodes = 20000) {
  const moves = allMoves();
  const open = new BinaryHeap();
  const closed = new Map();
  const key = (x, y, z) => x + ',' + y + ',' + z;

  const sx = Math.floor(start.x), sy = Math.floor(start.y), sz = Math.floor(start.z);
  const startNode = {
    x: sx, y: sy, z: sz,
    g: 0,
    h: heuristic(goalX - sx, goalY - sy, goalZ - sz),
    f: heuristic(goalX - sx, goalY - sy, goalZ - sz),
    move: null,
    parent: null,
  };
  open.push(startNode);
  closed.set(key(sx, sy, sz), startNode);

  let nodes = 0;
  while (!open.isEmpty() && nodes < maxNodes) {
    const cur = open.pop();
    nodes++;
    // 目标判定（2026-08-15 P5 修正）：
    //   maxOffset===1（精确站立）→ 必须与目标格一致（水平），y 偏差 ≤1——
    //   原 `|x-goalX|<=1` 让起点(-3212)距目标(-3211)差1格也被判"已到"，
    //   导致爬升目标(-3211,70,5398)被跳过（真机 BT_MOVE2 already_there 误判）。
    //   maxOffset>1（宽松定位，如初始/走回）→ 保持容差。
    const dxg = Math.abs(cur.x - goalX), dzg = Math.abs(cur.z - goalZ);
    const yTol = maxOffset === 1 ? 1 : 3;
    const hTol = maxOffset === 1 ? 0 : maxOffset;
    if (dxg <= hTol && dzg <= hTol && Math.abs(cur.y - goalY) <= yTol) {
      return reconstruct(cur);
    }
    for (const m of moves) {
      const nx = cur.x + m.dx, ny = cur.y + m.dy, nz = cur.z + m.dz;
      if (!m.valid(world, cur.x, cur.y, cur.z, 0, 0)) continue; // valid 签名兼容
      const cost = m.cost(world, cur.x, cur.y, cur.z);
      if (cost >= COST_INF) continue;
      const k = key(nx, ny, nz);
      const ng = cur.g + cost;
      const existing = closed.get(k);
      if (existing && existing.g <= ng) continue;
      const nh = heuristic(goalX - nx, goalY - ny, goalZ - nz);
      const node = {
        x: nx, y: ny, z: nz,
        g: ng, h: nh, f: ng + nh,
        move: m, parent: cur,
      };
      if (existing) {
        existing.g = ng; existing.f = ng + nh; existing.move = m; existing.parent = cur;
        // 堆不更新（简化：重新压入），可能重复——由 closed 检查去重
        open.push(existing);
      } else {
        closed.set(k, node);
        open.push(node);
      }
    }
  }
  return null; // 未找到
}

function reconstruct(end) {
  const path = [];
  let n = end;
  while (n && n.move) {
    path.unshift({
      name: n.move.name,
      dx: n.move.dx, dy: n.move.dy, dz: n.move.dz,
      from: { x: n.parent.x, y: n.parent.y, z: n.parent.z },
      to: { x: n.x, y: n.y, z: n.z },
    });
    n = n.parent;
  }
  return path;
}

module.exports = { findPath, BinaryHeap };