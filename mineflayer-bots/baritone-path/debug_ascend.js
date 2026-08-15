/** debug_ascend.js — 诊断 ASCEND_S 从 (-3212,69,5397) 出发的合法性 */
const { World } = require('./world');
const { allMoves } = require('./moves');

const blocks = new Map();
for (let x = -3214; x <= -3210; x++) for (let z = 5395; z <= 5399; z++) {
  blocks.set(`${x},68,${z}`, 'white_concrete');
}
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
const w = new World(mockBot);

// 检查关键方块
console.log('canWalkOn(-3211,68,5397):', w.canWalkOn(-3211, 68, 5397));
console.log('canWalkThrough(-3211,69,5397):', w.canWalkThrough(-3211, 69, 5397));
console.log('canWalkOn(-3211,69,5398):', w.canWalkOn(-3211, 69, 5398));
console.log('canWalkThrough(-3211,70,5398):', w.canWalkThrough(-3211, 70, 5398));
console.log('canWalkThrough(-3211,71,5398):', w.canWalkThrough(-3211, 71, 5398));
console.log('canWalkThrough(-3211,70,5397):', w.canWalkThrough(-3211, 70, 5397));
console.log('canWalkThrough(-3211,71,5397):', w.canWalkThrough(-3211, 71, 5397));

// 直接测 moves
const moves = allMoves();
for (const m of moves) {
  if (m.name === 'TRAVERSE_E') console.log('TRAVERSE_E valid:', m.valid(w, -3212, 69, 5397, 0, 0));
  if (m.name === 'ASCEND_S') console.log('ASCEND_S valid:', m.valid(w, -3212, 69, 5397, 0, 0));
  if (m.name === 'ASCEND_E') console.log('ASCEND_E valid:', m.valid(w, -3212, 69, 5397, 0, 0));
  if (m.name === 'ASCEND_SE') console.log('ASCEND_SE (should not exist)');
}
// TRAVERSE_E 后 ASCEND_S
console.log('TRAVERSE_E→(-3211,69,5397) 后 ASCEND_S valid:',
  moves.find(m => m.name === 'ASCEND_S').valid(w, -3211, 69, 5397, 0, 0));