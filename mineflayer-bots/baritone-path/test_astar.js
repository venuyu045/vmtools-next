/**
 * test_astar.js — baritone 移植寻路单测（模拟世界：平地走 / 爬升 / 跳跃）
 */
const { World } = require('./world');
const { findPath } = require('./astar');

/** 构造一个模拟世界：y≤67 是石头大地，y=68..69 可按需填充方块 */
function makeMockWorld(fill) {
  // fill: (x,y,z) => name | null（null=空气）
  const blocks = new Map();
  const mockBot = {
    blockAt(pos) {
      const { x, y, z } = pos;
      // 大地：y<=67 全是石头
      if (y <= 67) return { name: 'stone', boundingBox: 'block' };
      const key = `${x},${y},${z}`;
      const name = fill.get ? (fill.get(key) || 'air') : 'air';
      if (name === 'air') return { name: 'air', boundingBox: 'empty' };
      return { name, boundingBox: 'block' };
    },
  };
  return new World(mockBot);
}

function assert(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); process.exitCode = 1; }
  else console.log('PASS:', msg);
}

// ── 测试1：平地走（y=69 层铺满方块，bot 站 68 层顶=脚69）──
{
  const fill = new Map();
  for (let x = -2; x <= 6; x++) for (let z = -2; z <= 6; z++) {
    fill.set(`${x},69,${z}`, 'white_concrete'); // 69 层方块（bot 脚下=68层方块顶69）
    fill.set(`${x},68,${z}`, 'white_concrete'); // 68 层平台
  }
  const w = makeMockWorld(fill);
  // bot 脚格 (0,69,0)（站 68 层顶），目标 (0,69,4)
  const path = findPath(w, { x: 0, y: 69, z: 0 }, 0, 69, 4, 1);
  assert(path && path.length > 0, `平地走 path len=${path ? path.length : 0}`);
  if (path) {
    const last = path[path.length - 1].to;
    assert(Math.abs(last.z - 4) <= 1, `平地走终点 z=${last.z}（应≈4）`);
  }
}

// ── 测试2：爬升 1 格（69 层东侧有 1 格高台阶，bot 需 ASCEND）──
{
  const fill = new Map();
  for (let x = -2; x <= 6; x++) for (let z = -2; z <= 6; z++) {
    fill.set(`${x},68,${z}`, 'white_concrete');
  }
  // 东侧台阶：x>=2 的 69 层有方块（bot 从 (0,69,0) 到 (4,70,0) 需爬升）
  for (let x = 2; x <= 6; x++) for (let z = -2; z <= 6; z++) {
    fill.set(`${x},69,${z}`, 'white_concrete');
  }
  const w = makeMockWorld(fill);
  const path = findPath(w, { x: 0, y: 69, z: 0 }, 4, 70, 0, 1);
  assert(path && path.length > 0, `爬升 path len=${path ? path.length : 0}`);
  if (path) {
    const hasAscend = path.some(p => p.name.startsWith('ASCEND'));
    assert(hasAscend, `爬升含 ASCEND 移动: ${path.map(p => p.name).join('→')}`);
  }
}

// ── 测试3：跳跃（69 层中间 2 格空隙，bot 需 PARKOUR）──
{
  const fill = new Map();
  for (let x = -2; x <= 6; x++) for (let z = -2; z <= 6; z++) {
    if (z >= 3 && z <= 4) continue; // 空隙 z=3..4
    fill.set(`${x},68,${z}`, 'white_concrete');
    fill.set(`${x},69,${z}`, 'white_concrete');
  }
  const w = makeMockWorld(fill);
  // bot (0,69,0) → (0,69,6)：中间 z=3,4 是空隙，需跳跃
  const path = findPath(w, { x: 0, y: 69, z: 0 }, 0, 69, 6, 1);
  assert(path && path.length > 0, `跳跃 path len=${path ? path.length : 0}`);
  if (path) {
    const hasParkour = path.some(p => p.name.startsWith('PARKOUR'));
    assert(hasParkour, `跳跃含 PARKOUR: ${path.map(p => p.name).join('→')}`);
  }
}

console.log(process.exitCode ? '❌ 有失败' : '✅ 全部通过');