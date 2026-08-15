/**
 * executor.js — baritone PathExecutor 的 JS 版（逐 Movement 控制键执行）
 *
 * 每个 Movement 用 mineflayer 控制键模拟：
 *   - 先 lookAt 目标格（保证 forward 语义=朝目标），再按住 forward 前进
 *   - ASCEND / PARKOUR：水平接近目标时按 jump（跳跃爬升/跨隙）——解决「不会跳」
 *   - DESCEND / DOWNWARD：forward（自然下落/走下）
 *   - PILLAR / BRIDGE → 返回 needPlace 由调用方 scaffold 兜底
 *
 * 到位判定（每 50ms）：bot 脚格 = floor(position) 与目标格一致（水平），
 * 且 y 偏差 ≤1 → 下一段。（2026-08-15 P5：用格坐标而非浮点距离，防 0.707>0.6 误判）
 */

const { Vec3 } = require('vec3');

const TICK_MS = 50;
const MOVE_TIMEOUT_MS = 8000;   // 单段移动超时
const ARRIVE_Y = 1.0;           // 垂直到位容差（格）

function botFoot(bot) {
  const p = bot.entity ? bot.entity.position : null;
  if (!p) return null;
  return { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z), px: p.x, py: p.y, pz: p.z };
}

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
  const isAscend = mv.dy > 0;
  const isParkour = mv.name.startsWith('PARKOUR');
  const isDescend = mv.dy < 0;

  // 1) 面向目标格（forward 语义=朝目标）
  try {
    const fromPos = bot.entity.position;
    await bot.lookAt(new Vec3(to.x + 0.5, fromPos.y, to.z + 0.5));
    await sleep(120);
  } catch (e) { /* lookAt 失败继续 */ }

  let arrived = false;
  let lastPos = botFoot(bot);
  let stillMs = 0;
  const start = Date.now();

  const ctrl = { forward: false, back: false, left: false, right: false, jump: false, sneak: false };
  const setCtrl = (patch) => {
    for (const k of Object.keys(ctrl)) {
      const v = patch[k] !== undefined ? patch[k] : false;
      if (bot.controlState[k] !== v) bot.setControlState(k, v);
      ctrl[k] = v;
    }
  };

  try {
    // 2) 前进（+ 爬升/跳跃由接近度触发）
    setCtrl({ forward: true });

    while (Date.now() - start < MOVE_TIMEOUT_MS) {
      await sleep(TICK_MS);
      const f = botFoot(bot);
      if (!f) continue;
      // 到位判定：格坐标一致（水平）+ y 偏差 ≤1
      const horizontalOK = f.x === to.x && f.z === to.z;
      const yOK = Math.abs(f.py - to.y) <= ARRIVE_Y;

      // 爬升/跳跃：水平接近目标时持续跳跃直到 y 到位
      if (isAscend || isParkour) {
        const hDist = Math.hypot(f.px - to.x, f.pz - to.z);
        if (hDist < 1.1 && !yOK) {
          setCtrl({ jump: true });
        } else if (yOK) {
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