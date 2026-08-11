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
      // 1.21.6+/26.1 新协议：攻击是独立的 packet_attack 包（{entityId}），
      // use_entity 仅用于交互（右键，不会造成伤害）。
      // 此前误发 use_entity → 只有挥手动画没有实质伤害。
      bot._client.write('attack', { entityId: entity.id });
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

  /** 原地攻击（挂机模式）：不寻路，目标超出攻击半径直接跳过 */
  async function standAndAttack(entity, maxDist = 3) {
    if (!entity || !entity.position) return { success: false, error: 'no target' };
    const dist = bot.entity.position.distanceTo(entity.position);
    if (dist > maxDist) {
      return { success: false, error: 'target too far', distance: Math.round(dist * 100) / 100 };
    }
    return attackEntity(entity);
  }

  /** 按当前攻击模式执行（挂机不动 / 寻路追击）；attackRadius 为实际出手距离 */
  async function attackByMode(entity, moveToTarget, attackRadius = 3) {
    if (moveToTarget) return approachAndAttack(entity, attackRadius);
    return standAndAttack(entity, attackRadius);
  }

  // ── 高版本 PvP 攻击逻辑（1.21.6+/26.1，2026-08-11） ─────────────────
  // 1.9+ 战斗更新：攻击冷却（满=100%伤害）、冲刺攻击（+50%伤害+强击退）、
  // 跳劈（下落攻击1.5x）、W-tap/S-tap（重置冲刺→目标击退小→连击）、strafe 环绕。
  // 假人自身不受击退，技巧核心 = 控制【目标】击退距离 + 连击 + 走位躲避瞄准。

  /** 武器攻速 → 攻击冷却（毫秒）。攻速=每秒攻击次数，冷却 = 1000/攻速。 */
  function weaponAttackIntervalMs(itemName) {
    if (!itemName) return 250; // 空手 4.0 次/s
    const n = String(itemName).toLowerCase();
    if (n.includes('sword')) return 625;    // 剑 1.6 → 0.625s
    if (n.includes('trident')) return 909;  // 三叉戟 1.1 → 0.91s
    if (n.includes('pickaxe')) return 833;  // 镐 1.2 → 0.83s
    if (n.includes('shovel')) return 1000;  // 锹 1.0
    if (n.includes('hoe')) return 1000;     // 锄 1.0
    if (n.includes('axe')) return 1000;     // 斧 0.8~1.0，简化 1.0s
    return 1000;                            // 默认 1.0 次/s
  }

  let strafeDir = true;

  /** W-tap：攻击后短暂松开前进 → 重置冲刺 → 目标击退变小（连击） */
  function wtapOnce() {
    try {
      bot.setControlState('forward', false);
      bot.setControlState('sprint', false);
      setTimeout(() => { try { bot.setControlState('forward', true); } catch (e) { /* ignore */ } }, 90);
    } catch (e) { /* ignore */ }
  }

  /** S-tap：攻击后短暂后退 → 取消冲刺击退（连击） */
  function stapOnce() {
    try {
      bot.setControlState('back', true);
      setTimeout(() => { try { bot.setControlState('back', false); } catch (e) { /* ignore */ } }, 80);
    } catch (e) { /* ignore */ }
  }

  /** 环绕走位：冷却期间绕目标圆周移动，目标难瞄准 */
  function strafeAround(entity, atkR) {
    if (!bot.entity || !entity || !entity.position) return;
    const me = bot.entity.position;
    const dx = me.x - entity.position.x;
    const dz = me.z - entity.position.z;
    const d = Math.sqrt(dx * dx + dz * dz) || 0.001;
    try {
      if (d < atkR - 0.8) {
        bot.setControlState('forward', false);
        bot.setControlState('back', true);
      } else if (d > atkR + 0.6) {
        bot.setControlState('back', false);
        bot.setControlState('forward', true);
      } else {
        bot.setControlState('forward', false);
        bot.setControlState('back', false);
        strafeDir = !strafeDir;
        bot.setControlState('right', strafeDir);
        bot.setControlState('left', !strafeDir);
      }
    } catch (e) { /* ignore */ }
  }

  /** 执行一次攻击（含冲刺/跳劈/连击技巧），并记录冷却 */
  async function doAttack(state, entity, crit) {
    // 冲刺状态：非跳劈时保持冲刺 → 冲刺攻击 +50% 伤害 + 强击退
    if (!crit && state.tricks.sprint) {
      try { bot.setControlState('sprint', true); } catch (e) { /* ignore */ }
    }
    const res = await attackEntity(entity);
    state.lastAttackAt = Date.now();
    state.targetId = entity ? entity.id : null;
    if (res && res.success) {
      // W-tap / S-tap：重置冲刺 → 目标击退小 → 连续命中（combo）
      if (state.tricks.wtap) wtapOnce();
      else if (state.tricks.stap) stapOnce();
    }
    return res;
  }

  /** PvP 战斗循环（10Hz 决策 + 攻击冷却驱动，move_to_target=true 时使用） */
  async function pvpTick(state) {
    if (!state || !state.enabled) return;
    // 耐久检测
    const dur = heldDurability();
    if (dur.hasDurability && dur.ratio < state.stop_durability) {
      state.enabled = false;
      stopTimers();
      notifyDurabilityLow(dur.ratio);
      return { stopped: 'durability_low', ratio: dur.ratio };
    }
    const scanR = state.scan_radius ?? state.radius ?? 16;
    const atkR = state.attack_radius ?? 3;
    const targets = getNearbyEntities(scanR, state.target_types, !includesPlayer(state.target_types));
    if (targets.length === 0) {
      try { bot.pathfinder.setGoal(null); } catch (e) { /* ignore */ }
      state.targetId = null;
      state.pendingJump = false;
      return { scanned: 0 };
    }
    const entity = bot.entities[targets[0].id];
    if (!entity) return { scanned: targets.length };

    const now = Date.now();
    // 攻击冷却：auto=按武器攻速；manual=前端手动间隔
    const interval = state.interval_mode === 'manual'
      ? state.interval_ms
      : weaponAttackIntervalMs(bot.heldItem ? (bot.heldItem.name || '') : '');
    const dist = bot.entity.position.distanceTo(entity.position);

    // ── 追击态：pathfinder 实时追踪目标 + 冲刺 ──
    if (dist > atkR) {
      state.pendingJump = false;
      if (state.tricks.sprint) {
        try { bot.setControlState('sprint', true); } catch (e) { /* ignore */ }
      }
      try {
        bot.pathfinder.setGoal(new GoalNear(
          entity.position.x, entity.position.y, entity.position.z,
          Math.max(0.5, atkR - 0.5),
        ));
      } catch (e) { /* ignore */ }
      return { chasing: entity.name, distance: Math.round(dist * 100) / 100 };
    }

    // ── 近战态：停寻路，手动控制 ──
    try { bot.pathfinder.setGoal(null); } catch (e) { /* ignore */ }

    const cooldownOk = (now - (state.lastAttackAt || 0)) >= interval;
    if (!cooldownOk) {
      // 冷却中 → 环绕走位（目标难瞄准）
      if (state.tricks.strafe) strafeAround(entity, atkR);
      return { cooling: true };
    }

    // 跳劈：贴脸时起跳，下落中攻击（1.5x 暴击）
    if (state.tricks.jump_crit && !state.pendingJump
        && bot.entity.velocity && Math.abs(bot.entity.velocity.y) < 0.01
        && dist <= atkR + 0.5) {
      state.pendingJump = true;
      try { bot.setControlState('jump', true); } catch (e) { /* ignore */ }
      return { jump: true };
    }
    if (state.pendingJump) {
      if (bot.entity.velocity && bot.entity.velocity.y < 0) {
        state.pendingJump = false;
        const res = await doAttack(state, entity, true);
        return { crit: true, result: res };
      }
      return { falling: true };
    }

    // 普通攻击（冷却满）
    const res = await doAttack(state, entity, false);
    return { attacked: entity.name, distance: Math.round(dist * 100) / 100, result: res };
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
    // PVP 模式（move_to_target=true，非守护）：走高版本攻击逻辑
    if (state.move_to_target && state.mode !== 'guard') return pvpTick(state);
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
    // 索敌并攻击最近的匹配实体（scan_radius 扫描；target_types 含 player 时放行玩家）
    const scanR = state.scan_radius ?? state.radius ?? 8;
    const atkR = state.attack_radius ?? 3;
    const targets = getNearbyEntities(scanR, state.target_types, !includesPlayer(state.target_types));
    if (targets.length === 0) return { scanned: 0 };
    const entity = bot.entities[targets[0].id];
    if (!entity) return { scanned: targets.length };
    // move_to_target=false（挂机）：只打攻击半径内目标；true（PVP）：追到攻击半径内打
    const res = await attackByMode(entity, state.move_to_target, atkR);
    return { attacked: entity.name, distance: targets[0].distance, result: res };
  }

  function summarize(state) {
    return {
      enabled: state.enabled,
      mode: state.mode,
      radius: state.scan_radius ?? state.radius,       // 兼容旧字段 = 扫描半径
      scan_radius: state.scan_radius ?? state.radius ?? 8,
      attack_radius: state.attack_radius ?? 3,
      target_types: state.target_types,
      interval_ms: state.interval_ms,
      interval_mode: state.interval_mode || 'auto',
      stop_durability: state.stop_durability,
      move_to_target: state.move_to_target,
      tricks: state.tricks || { sprint: true, jump_crit: true, wtap: true, stap: true, strafe: true },
      guard_pos: state.guard_pos || null,
    };
  }

  // ── 方法 ──────────────────────────────────────────────
  function get_nearby_entities({ radius = 16, target_types = [] } = {}) {
    // 玩家过滤由 target_types 决定（含 player/all 时列出玩家）
    return { success: true, entities: getNearbyEntities(radius, target_types, !includesPlayer(target_types)) };
  }

  async function attack({ target_id = null, target_type = null, move_to_target = false, scan_radius = 16, attack_radius = 3 } = {}) {
    let entity = null;
    if (target_id != null) entity = bot.entities[target_id];
    if (!entity && target_type) {
      const list = getNearbyEntities(64, [target_type], false);
      if (list.length > 0) entity = bot.entities[list[0].id];
    }
    if (!entity) {
      const list = getNearbyEntities(scan_radius, [], true);
      if (list.length > 0) entity = bot.entities[list[0].id];
    }
    if (!entity) return { success: false, error: 'no target found' };
    // 手动攻击也遵循模式：false=原地打（够不到报错），true=寻路追击；均按攻击半径判定
    return attackByMode(entity, Boolean(move_to_target), Number(attack_radius) || 3);
  }

  function set_auto_attack({
    enabled = true, radius = 8, scan_radius = null, attack_radius = 3,
    target_types = [], interval_ms = 1000, interval_mode = 'auto',
    stop_durability = 0.1, move_to_target = false,
    enable_sprint_attack = true, enable_jump_crit = true,
    enable_wtap = true, enable_stap = true, enable_strafe = true,
  } = {}) {
    stopTimers();
    autoAttack = {
      enabled: Boolean(enabled),
      mode: 'auto',
      scan_radius: Number(scan_radius) || Number(radius) || 8,
      attack_radius: Number(attack_radius) || 3,
      radius: Number(scan_radius) || Number(radius) || 8, // 兼容旧引用
      target_types: Array.isArray(target_types) ? target_types : [],
      interval_ms: Math.max(100, Number(interval_ms) || 1000),
      interval_mode: interval_mode === 'manual' ? 'manual' : 'auto',
      stop_durability: Number(stop_durability) || 0.1,
      move_to_target: Boolean(move_to_target),
      tricks: {
        sprint: Boolean(enable_sprint_attack),
        jump_crit: Boolean(enable_jump_crit),
        wtap: Boolean(enable_wtap),
        stap: Boolean(enable_stap),
        strafe: Boolean(enable_strafe),
      },
      lastAttackAt: 0,
      pendingJump: false,
      targetId: null,
      timer: null,
    };
    guard = null;
    if (autoAttack.enabled) {
      // PVP（移动攻击）：10Hz 决策循环；挂机：按配置间隔
      const tickMs = autoAttack.move_to_target ? 100 : Math.max(100, autoAttack.interval_ms);
      autoAttack.timer = setInterval(() => { combatTick(autoAttack).catch(() => {}); }, tickMs);
      combatTick(autoAttack).catch(() => {});
    }
    return { success: true, config: summarize(autoAttack) };
  }

  function set_guard({ enabled = true, x = null, y = null, z = null, radius = 8, scan_radius = null, attack_radius = 3, target_types = [], interval_ms = 1000, stop_durability = 0.1, move_to_target = false } = {}) {
    stopTimers();
    const pos = bot.entity.position;
    const scanR = Number(scan_radius) || Number(radius) || 8;
    guard = {
      enabled: Boolean(enabled),
      mode: 'guard',
      guard_pos: { x: x ?? pos.x, y: y ?? pos.y, z: z ?? pos.z },
      guard_radius: scanR,
      scan_radius: scanR,
      attack_radius: Number(attack_radius) || 3,
      radius: scanR, // 兼容旧引用
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
    // 清理移动/冲刺/跳跃控制状态与寻路目标
    try { bot.pathfinder.setGoal(null); } catch (e) { /* ignore */ }
    ['forward', 'back', 'left', 'right', 'sprint', 'jump'].forEach((k) => {
      try { bot.setControlState(k, false); } catch (e) { /* ignore */ }
    });
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
