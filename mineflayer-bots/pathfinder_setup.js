/**
 * pathfinder_setup.js — mineflayer-pathfinder 配置
 *
 * 配置 Movements 参数（行走行为、能跳多高、能爬哪些方块等）。
 * 需要在 bot 生成后调用 setupMovements(bot) 应用配置。
 */

const { pathfinder, Movements } = require('mineflayer-pathfinder');

/**
 * 在 bot 上加载 pathfinder 插件并配置 Movements。
 * @param {import('mineflayer').Bot} bot
 */
function setupPathfinder(bot) {
  // 加载 pathfinder 插件
  bot.loadPlugin(pathfinder);

  // 创建默认 Movements
  const defaultMove = new Movements(bot);

  // ── 物理参数 ──
  defaultMove.allowParkour = false;          // 禁止跑酷（安全优先）
  defaultMove.allowParkourPlace = false;     // 禁止搭路
  defaultMove.allow1by1towers = false;       // 禁止 1x1 柱子上爬
  defaultMove.allowFreeMotion = false;       // 不启用自由运动模式

  // ── 可攀爬方块 ──
  // 默认情况下 pathfinder 自动检测梯子和藤蔓

  // ── 可跳跃高度 ──
  // 默认 1.5 格（一个完整方块），对于自动建造够了

  // ── 扫描范围 ──
  defaultMove.searchRadius = 100;            // 寻路搜索半径
  defaultMove.avoidCreepers = true;          // 避开苦力怕

  // 应用配置
  bot.pathfinder.setMovements(defaultMove);
}

module.exports = { setupPathfinder };
