/** debug_astar.js — 打印 A* 展开过程，定位为什么找不到对角爬升 */
const { World } = require('./world');
const { allMoves, COST_INF } = require('./moves');
const { BinaryHeap } = require('./astar');

const blocks = new Map();
for (let x = -3214; x <= -3210; x++) for (let z = 5395; z <= 5399; z++) {
  blocks.set(`${x},68,${z}`, 'white_concrete');
}
for (let x = -3214; x <= -3210; x++) blocks.set(`${x},69,5398`, 'black_concrete');
const mockBot = {
  blockAt(pos) {
    const { x, y, z } = pos;
    if (y <= 67) return { name: 'stone', boundingBox: 'block' };
    const key = `${x},${y},${z}`;
    if (blocks.has(key)) return { name: blocks.get(key), boundingBox: 'block' };
    return { name: 'air', boundingBox: 'empty' };
  },
};
const w = new World(mockBot);
const moves = allMoves();
const key = (x, y, z) => x + ',' + y + ',' + z;
const goalX = -3211, goalY = 70, goalZ = 5398;
const maxOffset = 1;

const sx = -3212, sy = 69, sz = 5397;
const open = new BinaryHeap();
const closed = new Map();
const hf = (x, y, z) => (Math.abs(goalX - x) + Math.abs(goalZ - z)) * 20 + Math.abs(goalY - y) * 20;
open.push({ x: sx, y: sy, z: sz, g: 0, h: hf(sx, sy, sz), f: hf(sx, sy, sz), move: null, parent: null });
closed.set(key(sx, sy, sz), true);

let nodes = 0;
while (!open.isEmpty() && nodes < 100) {
  const cur = open.pop();
  nodes++;
  const dxg = Math.abs(cur.x - goalX), dzg = Math.abs(cur.z - goalZ);
  if (dxg <= maxOffset && dzg <= maxOffset && Math.abs(cur.y - goalY) <= 3) {
    console.log(`✓ 目标到达 (${cur.x},${cur.y},${cur.z}) nodes=${nodes}`);
    break;
  }
  let validCount = 0;
  for (const m of moves) {
    const nx = cur.x + m.dx, ny = cur.y + m.dy, nz = cur.z + m.dz;
    if (!m.valid(w, cur.x, cur.y, cur.z, 0, 0)) continue;
    validCount++;
    const k = key(nx, ny, nz);
    if (closed.has(k)) continue;
    closed.set(k, true);
    const ng = cur.g + m.cost(w, cur.x, cur.y, cur.z);
    open.push({ x: nx, y: ny, z: nz, g: ng, h: hf(nx, ny, nz), f: ng + hf(nx, ny, nz), move: m, parent: cur });
  }
  if (nodes <= 5) console.log(`pop(${cur.x},${cur.y},${cur.z}) validMoves=${validCount}`);
}
console.log('nodes 展开:', nodes, 'open剩余:', open.size);