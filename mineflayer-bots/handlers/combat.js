/**
 * combat.js — 战斗 handler（自动攻击 / 手动攻击 / 守护模式）
 *
 * 方法：
 *   get_nearby_entities(radius?, target_types?) → 列出附近可攻击实体
 *   attack(target_id?, target_type?)            → 手动攻击一次（默认最近目标）
 *   set_auto_attack({enabled, radius, target_types, interval_ms, stop_durability})
 *                                               → 自动攻击最近的匹配实体
 *   set_guard({enabled, x, y, z, radius, target_types, interval_ms, stop_durability})
 *                                               → 守护模式（绕点巡逻，入侵者自动攻击）
 *   get_combat_status()                         → 当前战斗配置 + 主手武器耐久
 *   stop_combat()                               → 停止自动攻击 / 守护
 *
 * 事件（broadcast）：
 *   combat_durability_low {durability_ratio, weapon} — 主手武器耐久低于阈值自动停止
 */
const { Vec3 } = require('vec3');
const { GoalNear, GoalBlock } = require('mineflayer-pathfinder').goals;

/**
 * @param {import('mineflayer').Bot} bot
 * @param {{broadcast?: Function, createEvent?: Function}} ctx
 * @returns {object}
 */
function createCombatHandlers(bot, ctx = {}) {
  const { broadcast = null, createEvent = null } = ctx;
  let autoAttack = null; // { timer, config }
  let guard = null;      // { timer, config }

  // ── 工具 ──────────────────────────────────────────────
  function matchesType(entity, targetTypes) {
    if (!targetTypes || targetTypes.length === 0) return true; // 空 = 全部
    for (const t of targetTypes) {
      const tt = String(t).toLowerCase();
      if (tt === 'all') return true;
      if (tt === 'hostile' && entity.type === 'mob') return true; // 敌对≈mob 类（盔甲架是 object 不会误打）
      if (tt === 'mob' && entity.type === 'mob') return true;
      if (tt === 'object' && entity.type === 'object') return true;
      if (tt === 'player' && entity.type === 'player') return true;
      if (entity.name && entity.name.toLowerCase() === tt) return true;
      if (entity.displayName && entity.displayName.toLowerCase() === tt) return true;
    }
    return false;
  }

  /** 目标类型是否包含玩家（决定索敌/扫描是否放行 player 实体） */
  function includesPlayer(targetTypes) {
    if (!targetTypes || targetTypes.length === 0) return false;
    return targetTypes.some((t) => {
      const tt = String(t).toLowerCase();
      return tt === 'player' || tt === 'all';
    });
  }

  function getNearbyEntities(radius, targetTypes, excludePlayers = true) {
    if (!bot.entity || !bot.entities) return [];
    const pos = bot.entity.position;
    const out = [];
    for (const id of Object.keys(bot.entities)) {
      const e = bot.entities[id];
      if (!e || e === bot.entity) continue;
      if (excludePlayers && e.type === 'player') continue;
      if (!e.position) continue;
      const dist = e.position.distanceTo(pos);
      if (dist > radius) continue;
      if (!matchesType(e, targetTypes)) continue;
      out.push({
        id: e.id,
        name: e.name || '?',
        displayName: e.displayName || e.name || '?',
        type: e.type,
        kind: e.kind || null,
        position: { x: e.position.x, y: e.position.y, z: e.position.z },
        distance: Math.round(dist * 100) / 100,
      });
    }
    out.sort((a, b) => a.distance - b.distance);
    return out;
  }

  function heldDurability() {
    const item = bot.heldItem;
    if (!item) return { hasDurability: false, ratio: 1, name: null, display_name: null };
    const max = item.maxDurability;
    const used = item.durabilityUsed;
    if (typeof max !== 'number' || !isFinite(max) || max <= 0) {
      return { hasDurability: false, ratio: 1, name: item.name || null, display_name: item.displayName || item.name || null };
    }
    const ratio = 1 - ((used || 0) / max);
    return { hasDurability: true, ratio, used, max, name: item.name || null, display_name: item.displayName || item.name || null };
  }

  async function attackEntity(entity) {
    if (!entity) return { success: false, error: 'no target' };
    try {
      // ⚠️ 不能用 bot.attack()：mineflayer 在 1.21.6+/26.1 新协议下构造的
      // use_entity 包缺 hand 字段且位置字段结构变化，protodef 序列化报
      // 「SizeOf error for undefined (reading 'x')」——攻击包根本没发出去。
      // 这里直接用 bot._client.write 按协议原生发送攻击包（字段全带，兼容新旧协议）。
      if (!bot._client) return { success: false, error: 'no client' };
      if (!bot.entity || !bot.entity.position) return { success: false, error: 'bot not spawned' };
      const epos = entity.position;
      if (!epos) return { success: false, error: 'target has no position' };
      // 挥手动画（攻击表现；不阻塞主流程）
      try { bot.swingArm('right'); } catch (e) { /* 忽略 */ }
      bot._client.write('use_entity', {
        target: entity.id,
        mouse: 0,   // 0 = 左键攻击
        x: epos.x, y: epos.y, z: epos.z, // 部分协议版本位置必填，带上兼容
        hand: 0,    // 0 = 主手（1.21.6+ 协议 mouse=0 时必填）
        sneaking: bot.getControlState('sneak') || false,
      });
      return { success: true, target: entity.name, id: entity.id };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  async function approachAndAttack(entity, maxDist = 3) {
    if (!entity || !entity.position) return { success: false, error: 'no target' };
    const dist = bot.entity.position.distanceTo(entity.position);
    if (dist > maxDist) {
      try {
        await bot.pathfinder.goto(new GoalNear(entity.position.x, entity.position.y, entity.position.z, 2));
      } catch (err) {
        // 寻路失败不阻塞，仍尝试攻击
      }
    }
    return attackEntity(entity);
  }

  /** 原地攻击（挂机模式）：不寻路，目标超出近战范围（≈3格）直接跳过 */
  async function standAndAttack(entity) {
    if (!entity || !entity.position) return { success: false, error: 'no target' };
    const dist = bot.entity.position.distanceTo(entity.position);
    if (dist > 3.2) {
      return { success: false, error: 'target too far', distance: Math.round(dist * 100) / 100 };
    }
    return attackEntity(entity);
  }

  /** 按当前攻击模式执行（挂机不动 / 寻路追击） */
  async function attackByMode(entity, moveToTarget) {
    if (moveToTarget) return approachAndAttack(entity);
    return standAndAttack(entity);
  }

  function notifyDurabilityLow(ratio) {
    if (broadcast && createEvent) {
      broadcast(createEvent('combat_durability_low', {
        durability_ratio: Math.round(ratio * 100) / 100,
        weapon: heldDurability().name,
      }));
    }
  }

  function stopTimers() {
    if (autoAttack && autoAttack.timer) { clearInterval(autoAttack.timer); autoAttack.timer = null; }
    if (guard && guard.timer) { clearInterval(guard.timer); guard.timer = null; }
  }

  async function combatTick(state) {
    if (!state || !state.enabled) return;
    // 主手武器耐久检测：低于阈值 → 自动停止 + 广播通知
    const dur = heldDurability();
    const stopRatio = state.stop_durability ?? 0.1;
    if (dur.hasDurability && dur.ratio < stopRatio) {
      state.enabled = false;
      stopTimers();
      notifyDurabilityLow(dur.ratio);
      return { stopped: 'durability_low', ratio: dur.ratio };
    }
    // 守护模式：先回到守护点附近再索敌
    if (state.mode === 'guard' && state.guard_pos) {
      const gp = state.guard_pos;
      const distToGuard = bot.entity.position.distanceTo(new Vec3(gp.x, gp.y, gp.z));
      if (distToGuard > (state.guard_radius || state.radius)) {
        try {
          await bot.pathfinder.goto(new GoalBlock(gp.x, gp.y, gp.z));
        } catch (err) { /* ignore */ }
      }
    }
    // 索敌并攻击最近的匹配实体（target_types 含 player 时放行玩家）
    const targets = getNearbyEntities(state.radius, state.target_types, !includesPlayer(state.target_types));
    if (targets.length === 0) return { scanned: 0 };
    const entity = bot.entities[targets[0].id];
    if (!entity) return { scanned: targets.length };
    // move_to_target=false（默认挂机）：原地攻击，够不到不追；true：寻路追击
    const res = await attackByMode(entity, state.move_to_target);
    return { attacked: entity.name, distance: targets[0].distance, result: res };
  }

  function summarize(state) {
    return {
      enabled: state.enabled,
      mode: state.mode,
      radius: state.radius,
      target_types: state.target_types,
      interval_ms: state.interval_ms,
      stop_durability: state.stop_durability,
      move_to_target: state.move_to_target,
      guard_pos: state.guard_pos || null,
    };
  }

  // ── 方法 ──────────────────────────────────────────────
  function get_nearby_entities({ radius = 16, target_types = [] } = {}) {
    // 玩家过滤由 target_types 决定（含 player/all 时列出玩家）
    return { success: true, entities: getNearbyEntities(radius, target_types, !includesPlayer(target_types)) };
  }

  async function attack({ target_id = null, target_type = null, move_to_target = false } = {}) {
    let entity = null;
    if (target_id != null) entity = bot.entities[target_id];
    if (!entity && target_type) {
      const list = getNearbyEntities(64, [target_type], false);
      if (list.length > 0) entity = bot.entities[list[0].id];
    }
    if (!entity) {
      const list = getNearbyEntities(8, [], true);
      if (list.length > 0) entity = bot.entities[list[0].id];
    }
    if (!entity) return { success: false, error: 'no target found' };
    // 手动攻击也遵循移动开关：false=原地打（够不到报错），true=寻路追击
    return attackByMode(entity, Boolean(move_to_target));
  }

  function set_auto_attack({ enabled = true, radius = 8, target_types = [], interval_ms = 1000, stop_durability = 0.1, move_to_target = false } = {}) {
    stopTimers();
    autoAttack = {
      enabled: Boolean(enabled),
      mode: 'auto',
      radius: Number(radius) || 8,
      target_types: Array.isArray(target_types) ? target_types : [],
      interval_ms: Math.max(100, Number(interval_ms) || 1000),
      stop_durability: Number(stop_durability) || 0.1,
      move_to_target: Boolean(move_to_target),
      timer: null,
    };
    guard = null;
    if (autoAttack.enabled) {
      autoAttack.timer = setInterval(() => { combatTick(autoAttack).catch(() => {}); }, autoAttack.interval_ms);
      combatTick(autoAttack).catch(() => {});
    }
    return { success: true, config: summarize(autoAttack) };
  }

  function set_guard({ enabled = true, x = null, y = null, z = null, radius = 8, target_types = [], interval_ms = 1000, stop_durability = 0.1, move_to_target = false } = {}) {
    stopTimers();
    const pos = bot.entity.position;
    guard = {
      enabled: Boolean(enabled),
      mode: 'guard',
      guard_pos: { x: x ?? pos.x, y: y ?? pos.y, z: z ?? pos.z },
      guard_radius: Number(radius) || 8,
      radius: Number(radius) || 8,
      target_types: Array.isArray(target_types) ? target_types : [],
      interval_ms: Math.max(100, Number(interval_ms) || 1000),
      stop_durability: Number(stop_durability) || 0.1,
      move_to_target: Boolean(move_to_target),
      timer: null,
    };
    autoAttack = null;
    if (guard.enabled) {
      guard.timer = setInterval(() => { combatTick(guard).catch(() => {}); }, guard.interval_ms);
      combatTick(guard).catch(() => {});
    }
    return { success: true, config: summarize(guard) };
  }

  function stop_combat() {
    stopTimers();
    if (autoAttack) autoAttack.enabled = false;
    if (guard) guard.enabled = false;
    return { success: true };
  }

  function get_combat_status() {
    const active = (autoAttack && autoAttack.enabled) ? autoAttack : ((guard && guard.enabled) ? guard : null);
    return {
      success: true,
      active_mode: active ? active.mode : null,
      config: active ? summarize(active) : null,
      durability: heldDurability(),
      entity_count: bot.entities ? Object.keys(bot.entities).length : 0,
    };
  }

  return {
    get_nearby_entities,
    attack,
    set_auto_attack,
    set_guard,
    get_combat_status,
    stop_combat,
  };
}

module.exports = { createCombatHandlers };
