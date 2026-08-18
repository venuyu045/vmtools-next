/**
 * sleep.js — 睡觉 handler（永昼：夜晚自动睡觉跳过黑夜，2026-08-16）
 *
 * 方法：
 *   get_time_status()                     → 世界时间/天气/维度/是否在睡
 *   find_bed({radius})                    → 找附近最近的床（findBlock）
 *   sleep_at({x, y, z, timeout_ms})       → 走到睡觉点的床旁并睡觉（等 sleep 事件）
 *   wake_up()                             → 手动唤醒
 *
 * 事件（broadcast）：
 *   sleep_state {is_sleeping, time_of_day, dimension, position, event}
 *     — bot 入睡（event=sleep）/ 醒来（event=wake）时推送，供前端/插件实时感知。
 *
 * 说明：
 * - mineflayer 内置 bed.js（node_modules/mineflayer/lib/plugins/bed.js）提供
 *   bot.sleep()/bot.wake()/bot.isABed()，要求：夜晚（timeOfDay 12541~23458）或雷暴、
 *   床 2 格点击范围内、未占用、附近无怪物（creative 除外）、仅主世界。
 * - bot.time 由 time.js 维护（timeOfDay 0~24000 / isDay / day / doDaylightCycle），
 *   「感知世界时间」完全可行。
 */
const { Vec3 } = require('vec3');
const { GoalNear } = require('mineflayer-pathfinder').goals;
const { pathTo } = require('../baritone-path/pathfinder');

/**
 * @param {import('mineflayer').Bot} bot
 * @param {{broadcast?: Function, createEvent?: Function}} ctx
 * @returns {object}
 */
function createSleepHandlers(bot, ctx = {}) {
  const { broadcast = null, createEvent = null } = ctx;

  // ── 2026-08-18 根治：修正 bot.time.timeOfDay 本身 ──
  // mineflayer time 插件在 'time' 事件里 `timeOfDay % 24000` 不做负数归一化 →
  // 服务器 timeOfDay(long) 溢出为负时 bot.time.timeOfDay 为负（实测 -4060）→
  // mineflayer bed.js 的 bot.sleep() 内部检查 `timeOfDay 12541~23458` 恒 False
  // → 「sleep_error: it's not night and it's not a thunderstorm」睡觉失败。
  // 这里注册监听覆盖为归一化值（mineflayer 先注册先更新，我们后注册覆盖）。
  // ⚠️ 2026-08-18 二次修复：26.1 协议 timeOfDay 是 BigInt（long）——
  // `typeof pkt.timeOfDay === 'number'` 恒 False → 修正从未生效！
  // 用 Number() 统一转 number 再归一化。
  try {
    if (bot._client && typeof bot._client.on === 'function') {
      bot._client.on('time', (pkt) => {
        try {
          if (pkt && pkt.timeOfDay != null && bot.time) {
            const raw = typeof pkt.timeOfDay === 'bigint' ? Number(pkt.timeOfDay) : pkt.timeOfDay;
            if (typeof raw === 'number' && isFinite(raw)) {
              let v = raw % 24000;
              if (v < 0) v += 24000;
              if (bot.time.timeOfDay !== v) bot.time.timeOfDay = v;
            }
          }
        } catch (e) { /* 忽略单次修正失败 */ }
      });
    }
  } catch (e) { /* time 修正注册失败不影响其余功能 */ }

  // ── 入睡/醒来事件 → 广播（Python 插件决策 + 前端实时状态） ──
  function emitSleepState(extra = {}) {
    if (!broadcast || !createEvent) return;
    broadcast(createEvent('sleep_state', {
      is_sleeping: !!bot.isSleeping,
      time_of_day: bot.time ? bot.time.timeOfDay : null,
      dimension: bot.game?.dimension || 'unknown',
      position: bot.entity ? {
        x: Math.round(bot.entity.position.x * 100) / 100,
        y: Math.round(bot.entity.position.y * 100) / 100,
        z: Math.round(bot.entity.position.z * 100) / 100,
      } : null,
      ...extra,
    }));
  }
  bot.on('sleep', () => emitSleepState({ event: 'sleep' }));
  bot.on('wake', () => emitSleepState({ event: 'wake' }));

  // ── 世界时间/状态 ──
  // ⚠️ 2026-08-18 根因修复：服务器运行时间长，Time Update 包 timeOfDay(long)
  // 溢出为负数 → mineflayer `timeOfDay % 24000` 得到负值（实测 -4060）→
  // 夜晚判断（12542~23458）恒 False → 「晚上不睡觉」根因。归一化：
  //   tod = tod % 24000; if (tod < 0) tod += 24000
  // 真实值：-4060 → 19940（夜晚 19:53）。
  function normalizeTimeOfDay(tod) {
    // ⚠️ 2026-08-18：兼容 BigInt（26.1 协议 timeOfDay 为 long）
    if (typeof tod === 'bigint') tod = Number(tod);
    if (typeof tod !== 'number' || isNaN(tod)) return null;
    let v = tod % 24000;
    if (v < 0) v += 24000;
    return v;
  }
  function get_time_status({} = {}) {
    const t = bot.time || {};
    const tod = normalizeTimeOfDay(t.timeOfDay);
    return {
      success: true,
      time_of_day: tod,                        // 0~24000（0=6:00 日出）
      is_day: tod !== null ? (tod < 13000) : (t.isDay ?? null), // 修正后重算（原 t.isDay 可能基于负值错误）
      day: t.day ?? null,
      do_daylight_cycle: t.doDaylightCycle ?? null, // false=服务器锁时间，睡觉不会跳
      is_raining: !!bot.isRaining,
      thunder_state: bot.thunderState ?? 0,    // >0 且 isRaining = 雷暴（也可睡）
      dimension: bot.game?.dimension || 'unknown',
      is_sleeping: !!bot.isSleeping,
      position: bot.entity ? {
        x: Math.round(bot.entity.position.x * 100) / 100,
        y: Math.round(bot.entity.position.y * 100) / 100,
        z: Math.round(bot.entity.position.z * 100) / 100,
      } : null,
    };
  }

  // ── 找附近最近的床 ──
  function find_bed({ radius = 64 } = {}) {
    if (!bot.entity) return { success: false, reason: 'no_entity' };
    const r = Number(radius) || 64;
    let bed = null;
    try {
      bed = bot.findBlock({
        matching: (b) => bot.isABed(b),
        maxDistance: r,
      });
    } catch (err) {
      return { success: false, reason: 'find_block_error:' + err.message };
    }
    if (!bed) {
      return { success: true, found: false, radius: r };
    }
    const dist = bed.position.distanceTo(bot.entity.position);
    return {
      success: true,
      found: true,
      block: {
        x: bed.position.x,
        y: bed.position.y,
        z: bed.position.z,
        name: bed.name,
      },
      distance: Math.round(dist * 100) / 100,
    };
  }

  /**
   * 到睡觉点睡觉：睡觉点坐标 = 床的方块坐标。
   * 1) 在睡觉点附近（8 格）找床，找不到 → 明确失败（床未放置/被拆）
   * 2) 距离 >2.5 格先寻路（远用 baritone，近用 pathfinder GoalNear 2 格）
   * 3) bot.sleep(bed) 并等待 sleep 事件（内部 3s 超时）
   */
  async function sleep_at({ x, y, z, timeout_ms = 30000 } = {}) {
    if (!bot.entity) return { success: false, reason: 'no_entity' };
    if (bot.isSleeping) return { success: false, reason: 'already_sleeping' };

    // 1. 可睡条件预检（提前返回友好原因；bot.sleep 内部也会再查一次）
    // ⚠️ 2026-08-18：tod 用 normalizeTimeOfDay 归一化（服务器 long 溢出为负时
    // 负值判断恒 not_night → 睡觉永远失败；实测 -4060 → 19940 夜晚）。
    const thunderstorm = bot.isRaining && (bot.thunderState > 0);
    const tod = normalizeTimeOfDay(bot.time ? bot.time.timeOfDay : null);
    // ⚠️ 2026-08-18 二次修复：强制把 bot.time.timeOfDay 写为归一化正值——
    // mineflayer bed.js 内部用 bot.time.timeOfDay（可能 BigInt/负值）判断
    // isDay（<13000=白天）→ 负值/BigInt 会被误判为白天 → 睡觉永远失败。
    if (tod !== null && bot.time) bot.time.timeOfDay = tod;
    if (!thunderstorm && (tod === null || !(tod >= 12541 && tod <= 23458))) {
      return { success: false, reason: 'not_night', time_of_day: tod };
    }

    // 2. 睡觉点附近找床
    const point = new Vec3(Math.floor(Number(x) || 0), Math.floor(Number(y) || 0), Math.floor(Number(z) || 0));
    let bed = null;
    try {
      bed = bot.findBlock({
        matching: (b) => bot.isABed(b),
        maxDistance: 8,
        point,
      });
    } catch (err) {
      return { success: false, reason: 'find_block_error:' + err.message };
    }
    if (!bed) {
      return {
        success: false,
        reason: 'bed_not_found_at_point',
        point: { x: point.x, y: point.y, z: point.z },
      };
    }

    // 3. 走到床边（2 格内可点击；bed.js 点击范围 x/z ±2、y ±2）
    // 2026-08-18：寻路失败【重试一次】（Via 数据旧/首次规划不准，重试常成功）；
    // 近距离（≤32）优先 pathfinder GoalNear（baritone 在近距离反而易 timeout）。
    const dist = bot.entity.position.distanceTo(bed.position);
    if (dist > 2.5) {
      let moved = false;
      try {
        const tryMove = async () => {
          if (dist > 32) {
            // 远距离：baritone 移植寻路（支持爬升/跳跃/下降）
            const r = await pathTo(bot, bed.position.x, bed.position.y, bed.position.z, {
              maxOffset: 2,
              timeoutMs: Math.min(timeout_ms, 30000),
              onLog: (m) => console.log(`[sleep][baritone] ${m}`),
            });
            return !!r.success;
          }
          // 近距离：pathfinder GoalNear（2 格容差）
          return await new Promise((resolve) => {
            let done = false;
            let timer = null;
            const cleanup = () => {
              bot.removeListener('goal_reached', onGoal);
              bot.removeListener('path_stop', onStop);
              bot.removeListener('path_timeout', onTimeout);
              if (timer) clearTimeout(timer);
            };
            const finish = (ok) => {
              if (done) return;
              done = true;
              cleanup();
              resolve(ok);
            };
            const onGoal = () => finish(true);
            const onStop = () => finish(false);
            const onTimeout = () => finish(false);
            bot.once('goal_reached', onGoal);
            bot.once('path_stop', onStop);
            bot.once('path_timeout', onTimeout);
            timer = setTimeout(() => {
              try { bot.pathfinder.stop(); } catch (e) { /* ignore */ }
              finish(false);
            }, Math.min(timeout_ms, 15000));
            try {
              bot.pathfinder.setGoal(new GoalNear(bed.position.x, bed.position.y, bed.position.z, 2));
            } catch (e) {
              finish(false);
            }
          });
        };
        moved = await tryMove();
        if (!moved) {
          // 2026-08-18：首次失败重试一次（Via 数据旧/卡住自愈）
          moved = await tryMove();
        }
      } catch (err) {
        return { success: false, reason: 'path_error:' + err.message };
      }
      if (!moved) {
        return { success: false, reason: 'path_failed', target: { x: bed.position.x, y: bed.position.y, z: bed.position.z } };
      }
    }

    // 4. 睡觉：优先 activateBlock 右键床（绕过 mineflayer bed.js 的
    //    「it's not night」时间检查——bed.js 内部用 bot.time.timeOfDay 原始值，
    //    即使我们预检通过它也可能拒绝），再等 sleep 事件；失败回退 bot.sleep()。
    //    2026-08-18 修复：实测 19:06 出现 sleep_error: it's not night。
    const sleepByActivate = () => new Promise((resolve) => {
      let done = false;
      const finish = (ok, extra) => {
        if (done) return;
        done = true;
        bot.removeListener('sleep', onSleep);
        if (timer) clearTimeout(timer);
        resolve(ok ? { success: true, ...extra } : { success: false, ...extra });
      };
      const onSleep = () => finish(true, { reason: 'sleeping' });
      const timer = setTimeout(() => finish(false, { reason: 'sleep_timeout' }), 4000);
      bot.once('sleep', onSleep);
      bot.activateBlock(bed).catch(() => finish(false, { reason: 'activate_failed' }));
    });
    try {
      const rAct = await sleepByActivate();
      if (rAct.success) {
        return { success: true, reason: 'sleeping', method: 'activate',
                bed: { x: bed.position.x, y: bed.position.y, z: bed.position.z } };
      }
      // activateBlock 未入睡（可能已修正时间）→ 回退 bot.sleep()（含时间/怪物检查）
      try {
        await bot.sleep(bed);
        return { success: true, reason: 'sleeping', method: 'bot.sleep',
                bed: { x: bed.position.x, y: bed.position.y, z: bed.position.z } };
      } catch (err2) {
        return { success: false, reason: 'sleep_error:' + err2.message, method: 'bot.sleep' };
      }
    } catch (err) {
      // 常见失败：床被占用 / 附近有怪物 / 点击太远 / 点击被拒
      return { success: false, reason: 'sleep_error:' + err.message };
    }
  }

  // ── 手动唤醒 ──
  async function wake_up({} = {}) {
    if (!bot.isSleeping) return { success: false, reason: 'already_awake' };
    try {
      await bot.wake();
      return { success: true };
    } catch (err) {
      return { success: false, reason: err.message };
    }
  }

  return { get_time_status, find_bed, sleep_at, wake_up };
}

module.exports = { createSleepHandlers };
