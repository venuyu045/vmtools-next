/**
 * executor.js — baritone PathExecutor 的 JS 版（逐 Movement 控制键执行）
 *
 * 每个 Movement 用 mineflayer 控制键模拟（forward/jump/strafe/sneak）：
 *   TRAVERSE  → 按住 forward 直到水平到位
 *   ASCEND    → 接近目标时 jump（跳跃 1 格爬升）—— 解决 mineflayer-pathfinder「不会跳」
 *   DESCEND   → forward（自然走下来）
 *   DIAGONAL  → forward + strafe（斜走）
 *   PARKOUR   → jump + forward（跑酷跨隙）
 *   DOWNWARD  → forward（落入下一格）
 *   PILLAR / BRIDGE → 需要放置方块：返回 needPlace 标记，由调用方用 scaffold/place 兜底
 *
 * 到位判定（每 50ms）：bot 脚格 = floor(position)；水平格一致且 y 偏差 ≤1 → 下一段。
 */

const { Vec3 } = require('vec3');

const TICK_MS = 50;
const MOVE_TIMEOUT_MS = 8000;   // 单段移动超时
const ARRIVE_XY = 0.6;          // 水平到位容差（格）
const ARRIVE_Y = 1.0;           // 垂直到位容差（格）

function botFoot(bot) {
  const p = bot.entity ? bot.entity.position : null;
  if (!p) return null;
  return { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z), px: p.x, py: p.y, pz: p.z };
}

function dist2D(px, pz, tx, tz) { return Math.hypot(px - tx, pz - tz); }

/**
 * 执行一个 movement（阻塞直到到位/超时/失败）。
 * @returns {{success:boolean, reason?:string, position?:object}}
 */
async function executeMovement(bot, mv, opts = {}) {
  const { onLog } = opts;
  const log = (msg) => { if (onLog) onLog(msg); };

  // 需要搭块的移动 → 交给调用方 scaffold 兜底
  if (mv.name.startsWith('PILLAR') || mv.name.startsWith('BRIDGE')) {
    return { success: false, reason: 'need_place:' + mv.name, position: botFoot(bot) };
  }

  const to = mv.to;
  const dx = to.x - mv.from.x, dz = to.z - mv.from.z;
  const isAscend = mv.dy > 0;
  const isDescend = mv.dy < 0;
  const isDiagonal = mv.name.startsWith('DIAGONAL');
  const isParkour = mv.name.startsWith('PARKOUR');

  // 计算控制输入
  const controls = { forward: false, back: false, left: false, right: false, jump: false, sneak: false };
  if (dz < 0) controls.forward = true;          // 北（-z）→ forward
  else if (dz > 0) controls.back = true;        // 南（+z）→ back（面向北时）——见下
  if (dx > 0) controls.right = true;            // 东（+x）→ strafe right
  else if (dx < 0) controls.left = true;        // 西（-x）→ strafe left
  // 注：bot 面朝北（yaw≈0）时 forward=北、back=南、right=东、left=西。

  // 先面向移动方向（简化：直接 lookAt 目标格，保证 forward 语义正确）
  try {
    const fromPos = bot.entity.position;
    const targetLook = new Vec3(to.x + 0.5, fromPos.y, to.z + 0.5);
    await bot.lookAt(targetLook);
    await sleep(120);
  } catch (e) { /* lookAt 失败继续 */ }

  let arrived = false;
  let lastPos = botFoot(bot);
  let stillMs = 0;
  const start = Date.now();

  const setCtrl = (patch) => {
    for (const k of Object.keys(controls)) {
      const v = patch[k] !== undefined ? patch[k] : false;
      if (bot.controlState[k] !== v) bot.setControlState(k, v);
      controls[k] = v;
    }
  };

  try {
    // 启动：前进（+ 爬升/跳跃时机由接近度触发）
    if (isAscend || isParkour) {
      // 先走一段再跳：等水平接近目标 0.8 格时按 jump
      setCtrl({ forward: dz < 0, back: dz > 0, right: dx > 0, left: dx < 0 });
    } else if (isDescend || isDiagonal) {
      setCtrl({ forward: dz < 0, back: dz > 0, right: dx > 0, left: dx < 0 });
    } else {
      setCtrl({ forward: dz < 0, back: dz > 0, right: dx > 0, left: dx < 0 });
    }

    while (Date.now() - start < MOVE_TIMEOUT_MS) {
      await sleep(TICK_MS);
      const f = botFoot(bot);
      if (!f) continue;
      const horizontalOK = dist2D(f.px, f.pz, to.x, to.z) <= ARRIVE_XY;
      const yOK = Math.abs(f.py - to.y) <= ARRIVE_Y;

      // 爬升：水平接近目标时持续跳跃直到 y 到位
      if (isAscend || isParkour) {
        const hDist = dist2D(f.px, f.pz, to.x, to.z);
        if (hDist < 1.1 && !yOK) {
          setCtrl({ jump: true });
        } else if (yOK) {
          setCtrl({ jump: false });
        } else {
          setCtrl({ jump: false });
        }
      }

      if (horizontalOK && yOK) { arrived = true; break; }

      // 卡住检测：2s 内位置几乎没变
      if (lastPos) {
        const moved = Math.hypot(f.px - lastPos.px, f.py - lastPos.py, f.pz - lastPos.pz);
        if (moved < 0.05) {
          stillMs += TICK_MS;
          if (stillMs > 2000) break;
        } else {
          stillMs = 0;
        }
      }
      lastPos = f;
    }
  } finally {
    setCtrl({ forward: false, back: false, left: false, right: false, jump: false, sneak: false });
  }

  if (arrived) {
    return { success: true, position: botFoot(bot) };
  }
  return { success: false, reason: 'move_timeout:' + mv.name, position: botFoot(bot) };
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

module.exports = { executeMovement, botFoot };