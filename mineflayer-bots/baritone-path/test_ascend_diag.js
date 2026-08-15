/**
 * test_ascend_diag.js — 复现真机场景：bot(-3212,69,5397)→目标(-3211,70,5398)
 * 需 TRAVERSE_E + ASCEND_S 组合（对角爬升：x+1,z+1,y+1 分两步）。
 */
const { World } = require('./world');
const { findPath } = require('./astar');

function makeWorld() {
  const blocks = new Map();
  // 68 层平台（x -3214..-3210, z 5395..5399）
  for (let x = -3214; x <= -3210; x++) for (let z = 5395; z <= 5399; z++) {
    blocks.set(`${x},68,${z}`, 'white_concrete');
  }
  // 69 层地图画（已放一行：z=5398 从 -3214 到 -3210）
  for (let x = -3214; x <= -3210; x++) {
    blocks.set(`${x},69,5398`, 'black_concrete');
  }
  const mockBot = {
    blockAt(pos) {
      const { x, y, z } = pos;
      if (y <= 67) return { name: 'stone', boundingBox: 'block' };
      const key = `${x},${y},${z}`;
      if (blocks.has(key)) return { name: blocks.get(key), boundingBox: 'block' };
      return { name: 'air', boundingBox: 'empty' };
    },
  };
  return new World(mockBot);
}

function assert(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); process.exitCode = 1; }
  else console.log('PASS:', msg);
}

const w = makeWorld();
// bot 站 (-3212,69,5397)（68层顶），目标 (-3211,70,5398)（站69层方块顶）
const path = findPath(w, { x: -3212, y: 69, z: 5397 }, -3211, 70, 5398, 1);
assert(path && path.length > 0, `对角爬升 path len=${path ? path.length : 0}`);
if (path) {
  console.log('路径:', path.map(p => `${p.name}→(${p.to.x},${p.to.y},${p.to.z})`).join(' '));
  const last = path[path.length - 1].to;
  assert(last.x === -3211 && last.z === 5398, `终点(${last.x},${last.y},${last.z}) 应为(-3211,70,5398)`);
  const hasAscend = path.some(p => p.name.startsWith('ASCEND'));
  assert(hasAscend, '含 ASCEND');
}
console.log(process.exitCode ? '❌ 失败' : '✅ 通过');