/**
 * inventory.js — 物品栏/容器操作 handler
 *
 * 方法：
 *   select_hotbar_item(item_type)                    → 在快捷栏中选择一个物品
 *   set_quick_bar_slot(slot_index)                   → 直接设置快捷栏槽位
 *   get_inventory_snapshot()                         → 获取 bot 背包快照
 *   open_container_at(x, y, z)                       → 打开容器，返回容器 ID
 *   close_container(container_id)                    → 关闭指定容器
 *   get_container_snapshot(container_id)             → 获取容器内容快照
 *   withdraw_container_item(item_type, count, container_id)  → 从容器取物品
 *   deposit_container_item(item_type, count, container_id)   → 向容器存物品
 *   click_window(target, container_id, slot, mouse_button, mode) → 窗口内左键/右键物品（2026-08-12）
 *   activate_item()                                  → 右键使用手持物品（快捷潜影盒等，2026-08-12）
 *
 * 窗口自动注册（2026-08-12）：服务器因点击/激活打开的新容器窗口（如快捷潜影盒 GUI）
 * 自动注册进 openContainers 并推送 container_opened 事件，前端据此切换容器面板。
 */

const { Vec3 } = require('vec3');
const { v4: uuidv4 } = require('uuid');

// ── 全局容器映射（进程级别） ──
// { containerId: { window, openedAt, position, blockName, auto } }
const openContainers = new Map();

// 主动打开（open_container_at）产生的预期容器 id 集合：windowOpen 时命中则跳过自动注册
const expectedContainers = new Set();

// 容器类窗口类型（对齐 mineflayer chest.js allowedWindowTypes + 服务器 GUI 常用类型）
const CONTAINER_WINDOW_TYPES = new Set([
  'minecraft:generic', 'minecraft:chest', 'minecraft:dispenser', 'minecraft:ender_chest',
  'minecraft:shulker_box', 'minecraft:hopper', 'minecraft:container', 'minecraft:dropper',
  'minecraft:trapped_chest', 'minecraft:barrel',
  'minecraft:white_shulker_box', 'minecraft:orange_shulker_box', 'minecraft:magenta_shulker_box',
  'minecraft:light_blue_shulker_box', 'minecraft:yellow_shulker_box', 'minecraft:lime_shulker_box',
  'minecraft:pink_shulker_box', 'minecraft:gray_shulker_box', 'minecraft:light_gray_shulker_box',
  'minecraft:cyan_shulker_box', 'minecraft:purple_shulker_box', 'minecraft:blue_shulker_box',
  'minecraft:brown_shulker_box', 'minecraft:green_shulker_box', 'minecraft:red_shulker_box',
  'minecraft:black_shulker_box',
  // 服务器 GUI / 箱子 UI 插件常用类型（Chest Commands / DeluxeMenus 等）：
  // generic_9xN = 9 列 × N 行（9x1=9格 … 9x6=54格），右键书本等触发的箱子 UI 即此类
  'minecraft:generic_9x1', 'minecraft:generic_9x2', 'minecraft:generic_9x3',
  'minecraft:generic_9x4', 'minecraft:generic_9x5', 'minecraft:generic_9x6',
  'minecraft:generic_3x3',
]);

/** 是否容器类窗口（白名单 + generic_9xN 等服务器 GUI 类型） */
function isContainerWindow(type) {
  if (!type) return false;
  if (CONTAINER_WINDOW_TYPES.has(type)) return true;
  // 兜底：generic_9xN / generic_3x3 前缀变体（未来插件可能用 generic_9x7 等）
  if (typeof type === 'string' && type.startsWith('minecraft:generic_9x')) return true;
  if (typeof type === 'string' && type.startsWith('minecraft:generic_3x3')) return true;
  return false;
}

// ── 文本组件解析（2026-08-12）────────────────────────────
// 窗口标题/物品自定义名/Lore 在 1.13+ 是 JSON 文本组件，mineflayer 传给
// 后端的可能是：JSON 字符串 / 已解析对象 / prismarine-nbt {type,value} 包装。
// 统一解析成去掉 § 格式码的纯文本。

function stripColor(s) {
  return String(s == null ? '' : s).replace(/§[0-9a-fk-or]/gi, '');
}

/** JSON 文本组件 → 纯文本（支持字符串/对象/数组/{type,value} NBT 包装/translate/extra；text+extra 拼接） */
function textComponentToPlain(v) {
  if (v == null) return '';
  if (typeof v === 'string') {
    const s = v.trim();
    if (s.startsWith('{') || s.startsWith('[')) {
      try { return textComponentToPlain(JSON.parse(s)); } catch (e) { /* 非JSON */ }
    }
    return stripColor(v);
  }
  if (Array.isArray(v)) return v.map(textComponentToPlain).join('');
  if (typeof v === 'object') {
    // NBT 包装 {type, value}：先解包（text/translate/extra 的值也可能是这种包装）
    if (v.value != null && v.type != null) return textComponentToPlain(v.value);
    // text/translate/extra 可能同时存在（如 extra 是内容、text 为空占位）→ 全部拼接非空部分
    let out = '';
    if (v.text != null) out += textComponentToPlain(v.text);
    if (v.translate != null) out += textComponentToPlain(v.translate);
    if (v.extra != null) out += textComponentToPlain(v.extra);
    if (out) return out;
    if (v.value != null) return textComponentToPlain(v.value);
  }
  return '';
}

/** 窗口标题（prismarine-chat ChatMessage / NBT / 字符串）→ 纯文本 */
function windowTitleText(title) {
  if (title == null) return '';
  if (typeof title === 'string') return textComponentToPlain(title);
  if (typeof title === 'object') {
    // prismarine-chat ChatMessage：toString() 返回去除格式码的纯文本
    if (typeof title.toString === 'function' && title.toString !== Object.prototype.toString) {
      try {
        const s = stripColor(title.toString());
        if (s) return s;
      } catch (e) { /* 忽略 */ }
    }
    return textComponentToPlain(title);
  }
  return String(title);
}

/** 从 prismarine-nbt {type,value} 包装结构中取指定路径字段值 */
function nbtGet(nbt, path) {
  try {
    let cur = nbt;
    for (const key of path) {
      if (!cur || typeof cur !== 'object') return undefined;
      const v = cur.value;
      if (v && typeof v === 'object' && key in v) cur = v[key];
      else return undefined;
    }
    return cur && 'value' in cur ? cur.value : undefined;
  } catch (e) { return undefined; }
}

/** 物品自定义名 + Lore（1.13+ NBT display / 1.21+ components 数组·对象·componentMap / prismarine-item 字段全兼容） */
function parseItemDisplay(item) {
  let custom_name = null;
  let lore = [];
  if (!item) return { custom_name, lore };

  // ── 1.21+ 数据组件（components 可能是数组 [{id,data}]、对象 {id:data}、NBT {type,value} 包装）──
  try {
    const comps = item.components;
    // 1) components 数组格式（协议组件列表）
    if (Array.isArray(comps) && comps.length) {
      for (const c of comps) {
        if (!c || typeof c !== 'object') continue;
        const id = String(c.id || c.type || c.name || '');
        const data = c.data !== undefined ? c.data : c;
        if (id.includes('custom_name')) {
          const t = textComponentToPlain(data);
          if (t) custom_name = t;
        } else if (id.includes('lore')) {
          const arr = Array.isArray(data) ? data : (data && Array.isArray(data.value) ? data.value : null);
          if (arr && !lore.length) {
            lore = arr.map(textComponentToPlain).map(s => s.trim()).filter(Boolean);
          }
        }
      }
    }
    // 2) componentMap（prismarine-item 解析后的组件映射）
    const cm = item.componentMap;
    if (cm && typeof cm === 'object' && Object.keys(cm).length) {
      const cn = cm['minecraft:custom_name'] != null ? cm['minecraft:custom_name'] : cm.custom_name;
      if (cn != null && !custom_name) {
        const t = textComponentToPlain(cn);
        if (t) custom_name = t;
      }
      const lr = cm['minecraft:lore'] != null ? cm['minecraft:lore'] : cm.lore;
      if (Array.isArray(lr) && !lore.length) {
        lore = lr.map(textComponentToPlain).map(s => s.trim()).filter(Boolean);
      }
    }
    // 3) components 对象形式（{id: data} 或 {type:'compound', value:{}}）
    if (comps && typeof comps === 'object' && !Array.isArray(comps)) {
      const compsVal = (comps.value && typeof comps.value === 'object') ? comps.value : comps;
      const cn = compsVal['minecraft:custom_name'] != null ? compsVal['minecraft:custom_name'] : compsVal.custom_name;
      if (cn != null && !custom_name) {
        const t = textComponentToPlain(cn);
        if (t) custom_name = t;
      }
      const lr = compsVal['minecraft:lore'] != null ? compsVal['minecraft:lore'] : compsVal.lore;
      if (Array.isArray(lr) && !lore.length) {
        lore = lr.map(textComponentToPlain).map(s => s.trim()).filter(Boolean);
      }
    }
  } catch (e) { /* 忽略 */ }

  // ── 1.13-1.20 NBT 格式（display.Name / display.Lore）──
  try {
    if (!custom_name) {
      const rawName = nbtGet(item.nbt, ['display', 'Name']);
      if (rawName != null) {
        const t = textComponentToPlain(rawName);
        if (t) custom_name = t;
      }
    }
    if (!lore.length) {
      const rawLore = nbtGet(item.nbt, ['display', 'Lore']);
      if (Array.isArray(rawLore)) {
        lore = rawLore.map(textComponentToPlain).map(s => s.trim()).filter(Boolean);
      }
    }
  } catch (e) { /* 忽略 */ }

  // ── prismarine-item 已解析字段（customName / lore / loreLines）──
  if (!custom_name && item.customName) {
    const t = stripColor(String(item.customName));
    if (t) custom_name = t;
  }
  if (!lore.length && Array.isArray(item.lore)) {
    lore = item.lore.map(s => stripColor(String(s))).map(s => s.trim()).filter(Boolean);
  }
  if (!lore.length && Array.isArray(item.loreLines)) {
    lore = item.loreLines.map(s => stripColor(String(s && s.toString ? s.toString() : s))).filter(Boolean);
  }
  return { custom_name, lore };
}

/**
 * @param {import('mineflayer').Bot} bot
 * @param {{broadcast?: Function, createEvent?: Function}} opts 事件推送闭包（mineflayer_bot.js 传入）
 */
function createInventoryHandlers(bot, opts = {}) {

  const broadcast = opts.broadcast || null;
  const createEvent = opts.createEvent || null;

  // 挂载 windowOpen/windowClose 自动注册（防重复）
  setupWindowListeners();

  /** 推事件（无广播闭包时静默跳过，如本地测试） */
  function emitEvent(name, data) {
    if (name === 'container_opened' || name === 'container_closed') {
      console.log(`[event:${name}] ${JSON.stringify(data)}`);
    }
    if (broadcast && createEvent) {
      try { broadcast(createEvent(name, data)); } catch (e) { /* 忽略 */ }
    }
  }

  /** 检查 bot.currentWindow 是否为新打开的容器窗口；是则自动注册并返回 container_id。
   *  已注册（windowOpen listener 已抢先注册）→ 返回已有 container_id，前端据此切换面板。 */
  async function registerOpenedWindowIfNew() {
    const w = bot.currentWindow;
    if (!w) return null;
    for (const [cid, entry] of openContainers.entries()) {
      if (entry.window === w) return cid; // 已注册：返回已有容器 id（视为已打开）
    }
    if (!isContainerWindow(w.type)) return null; // 非容器类（如合成/附魔/村民交易）
    const cid = uuidv4();
    openContainers.set(cid, {
      window: w,
      openedAt: Date.now(),
      position: null,
      blockName: windowTitleText(w.title) || 'container',
      auto: true,
    });
    emitEvent('container_opened', {
      container_id: cid,
      block_name: windowTitleText(w.title) || 'container',
      slot_count: typeof w.inventoryStart === 'number' ? w.inventoryStart : 27,
    });
    return cid;
  }

  /** 注册 windowOpen / windowClose 监听（防重复） */
  function setupWindowListeners() {
    if (bot.__inventoryWindowListeners) return;
    bot.__inventoryWindowListeners = true;

    bot.on('windowOpen', (window) => {
      // 主动打开（expectedContainers 非空）→ 由 open_container_at 注册，跳过
      if (expectedContainers.size > 0) {
        expectedContainers.clear();
        return;
      }
      // 自动注册（点击/激活触发的服务器 GUI，如快捷潜影盒/箱子 UI）
      if (isContainerWindow(window.type)) {
        const cid = registerOpenedWindowIfNewSync(window);
        if (cid) {
          emitEvent('container_opened', {
            container_id: cid,
            block_name: windowTitleText(window.title) || 'container',
            slot_count: typeof window.inventoryStart === 'number' ? window.inventoryStart : 27,
          });
        }
      }
    });

    bot.on('windowClose', (window) => {
      for (const [cid, entry] of openContainers.entries()) {
        if (entry.window === window) {
          openContainers.delete(cid);
          emitEvent('container_closed', { container_id: cid });
          break;
        }
      }
    });
  }

  /** 同步版自动注册（供 windowOpen listener 使用） */
  function registerOpenedWindowIfNewSync(window) {
    for (const entry of openContainers.values()) {
      if (entry.window === window) return null;
    }
    const cid = uuidv4();
    openContainers.set(cid, {
      window,
      openedAt: Date.now(),
      position: null,
      blockName: windowTitleText(window.title) || 'container',
      auto: true,
    });
    return cid;
  }

  // ── 在快捷栏中选择物品（或从背包装备到主手） ──
  // 对齐 litematica-printer InventoryUtils.switchToItems：物品在背包任意位置
  // 都能装备，而不只限快捷栏——否则建造切换物品会因"不在快捷栏"失败。
  async function select_hotbar_item({ item_type, prefer_lowest_slot = true } = {}) {
    try {
      const items = bot.inventory.items();
      const matchName = (it) => it.name === item_type || it.type?.toString() === item_type;

      // 1. 快捷栏优先（槽位 36-44，零成本切换）
      const hotbarItems = items.filter(item => item.slot >= 36 && item.slot <= 44);
      const match = hotbarItems.find(matchName);

      if (match) {
        // 计算快捷栏索引 (slot 36-44 → index 0-8)
        const hotbarIndex = match.slot - 36;
        bot.setQuickBarSlot(hotbarIndex);
        return {
          success: true,
          slot: hotbarIndex,
          item: { name: match.name, count: match.count },
        };
      }

      // 2. 快捷栏无匹配 → 尝试从背包装备到主手（printer switchToItems 等效）
      const invMatch = items.find(matchName);
      if (invMatch) {
        try {
          await bot.equip(invMatch.type, 'hand');
          return {
            success: true,
            slot: -1,  // 非快捷栏（直接装备到主手）
            item: { name: invMatch.name, count: invMatch.count },
            equipped_from_inventory: true,
          };
        } catch (equipErr) {
          return {
            success: false,
            error: `Equip from inventory failed: ${equipErr.message}`,
            item: { name: invMatch.name, slot: invMatch.slot, count: invMatch.count },
          };
        }
      }

      // 3. 背包中完全没有该物品
      return { success: false, error: `Item ${item_type} not found in inventory` };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 直接设置快捷栏槽位 ──
  function set_quick_bar_slot({ slot_index } = {}) {
    try {
      if (slot_index < 0 || slot_index > 8) {
        return { success: false, error: 'Slot index must be 0-8' };
      }
      bot.setQuickBarSlot(slot_index);
      return { success: true, slot: slot_index };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 获取背包快照 ──
  // 附带物品详情字段（耐久/附魔），供前端「物品详情」弹窗展示。
  function itemDetail(item) {
    const maxDur = (item && item.maxDurability) || null;
    let durability = null;
    let durabilityUsed = 0;
    try { durabilityUsed = item.durabilityUsed || 0; } catch (e) { durabilityUsed = 0; }
    if (maxDur) {
      durability = Math.max(0, maxDur - durabilityUsed);
    }
    let enchantments = [];
    try {
      const ench = item.enchants;
      if (Array.isArray(ench) && ench.length) {
        // enchants: [{name, lvl}]（prismarine-item 已解析）；过滤掉无名的条目
        enchantments = ench
          .filter(e => e && (e.name || e.lvl != null))
          .map(e => ({ name: e.name || '', lvl: e.lvl || 1 }));
      }
    } catch (e) { enchantments = []; }
    const display = parseItemDisplay(item);
    return { durability, max_durability: maxDur, enchantments, custom_name: display.custom_name, lore: display.lore };
  }

  function get_inventory_snapshot({} = {}) {
    try {
      // 注意：不能用 bot.inventory.items()——它只返回主背包+快捷栏（inventoryStart~inventoryEnd，
      // 即槽位 9-44），【不含】副手 45 / 盔甲 5-8 / 合成 0-4（此前移到副手的物品快照读不到 → 前端不显示）。
      // 必须遍历完整 slots 数组（0-45），由 Python 端统一归一化为前端标准槽位。
      const items = [];
      for (let i = 0; i < bot.inventory.slots.length; i++) {
        const item = bot.inventory.slots[i];
        if (!item) continue;
        const detail = itemDetail(item);
        const entry = {
          slot: item.slot,
          name: item.name,
          type: item.type,
          count: item.count,
          display_name: item.displayName,
          displayName: item.displayName,
          max_stack_size: item.maxStackSize,
          durability: detail.durability,
          max_durability: detail.max_durability,
          enchantments: detail.enchantments,
          custom_name: detail.custom_name,
          lore: detail.lore,
        };
        items.push(entry);
      }
      return {
        success: true,
        items,
        total_slots: bot.inventory.slots.length,
        held_item: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null,
        // 当前选中快捷栏索引（0-8）：前端黄色框跟随手持
        selectedHotbar: (typeof bot.quickBarSlot === 'number' && bot.quickBarSlot >= 0) ? bot.quickBarSlot : 0,
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 打开容器 ──
  // 距离超过 3 格时自动寻路靠近（2 格）再打开——支持前端「前往打开」一键操作
  async function open_container_at({ x, y, z } = {}) {
    try {
      const pos = new Vec3(x, y, z);

      // 2026-08-14 修复③：先显式寻路到坐标附近（触发 chunk 加载），再查方块。
      // 原逻辑 blockAt 在传送后 chunk 未加载时返回 null → scanContainerNear 也扫不到
      // → 直接 return "No container near"，根本没走到寻路逻辑（用户反馈"没等寻路
      // 就返回建造点"的根因）。
      if (bot.entity && bot.entity.position) {
        const dist = bot.entity.position.distanceTo(pos);
        if (dist > 3) {
          try {
            const { GoalNear } = require('mineflayer-pathfinder').goals;
            await Promise.race([
              bot.pathfinder.goto(new GoalNear(x, y, z, 2)),
              new Promise((resolve) => setTimeout(resolve, 15000)),
            ]);
          } catch (err) {
            // 寻路失败/超时不阻塞，仍尝试直接打开（可能失败）
          }
        }
      }

      let block = bot.blockAt(pos);

      // 2026-08-14 修复①：blockAt 可能因 chunk 未加载/非容器返回无效
      // （实测 bot 距目标 3.5 格仍拿到无效方块）→ 在目标附近扫描容器兜底
      if (!block || block.type === 0 || !isContainerBlockName(block.name)) {
        const nearby = scanContainerNear(pos, 3);
        if (!nearby) {
          return { success: false, error: `No container near (${x},${y},${z})` };
        }
        block = nearby.block;
        pos.copy(nearby.pos);
      }

      const containerId = uuidv4();
      expectedContainers.add(containerId); // 标记主动打开，windowOpen 时跳过自动注册

      let container;
      try {
        // 2026-08-14 修复②：bot.openContainer 用 containerToOpen.constructor.name==='Block'
        // 严格判断——prismarine-world 26.1 返回的 Block 跨包实例该判断失败，抛
        // "containerToOpen is neither a block nor an entity"（实测根因）。
        // bot.openBlock = activateBlock（右键交互）+ windowOpen 等待，无类型检查。
        container = await Promise.race([
          bot.openBlock(block),
          new Promise((_, reject) => setTimeout(() => reject(new Error('open container timeout (8s)')), 8000)),
        ]);
      } finally {
        // 无论成败都清掉预期标记，防止残留导致后续 windowOpen 自动注册被跳过
        expectedContainers.delete(containerId);
      }
      openContainers.set(containerId, {
        window: container,
        openedAt: Date.now(),
        position: { x, y, z },
        blockName: block.name,
        auto: false,
      });

      return {
        success: true,
        container_id: containerId,
        block_name: block.name,
        // 容器容量 = inventoryStart（容器槽位起点；小箱子27/大箱子54/末影箱27/潜影盒27）
        // 不能用 containerItems().length——那是【非空物品数】，空箱子会返回 0
        slot_count: typeof container.inventoryStart === 'number'
          ? container.inventoryStart
          : (container.slots ? container.slots.length : 27),
        position: { x, y, z },
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 容器方块名判断（潜影盒各色/箱子/桶/漏斗/发射器等） ──
  function isContainerBlockName(name) {
    if (!name) return false;
    const base = String(name).includes(':') ? String(name).split(':')[1] : name;
    if (base.includes('shulker_box')) return true;
    return ['chest', 'trapped_chest', 'barrel', 'hopper', 'dispenser', 'dropper',
            'furnace', 'blast_furnace', 'smoker', 'brewing_stand', 'ender_chest']
      .includes(base);
  }

  // ── 目标坐标附近扫描容器（blockAt 无效时的兜底） ──
  function scanContainerNear(pos, radius = 3) {
    try {
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -radius; dx <= radius; dx++) {
          for (let dz = -radius; dz <= radius; dz++) {
            const p = pos.offset(dx, dy, dz);
            const b = bot.blockAt(p);
            if (b && b.type !== 0 && isContainerBlockName(b.name)) {
              return { block: b, pos: p };
            }
          }
        }
      }
      return null;
    } catch { return null; }
  }

  // ── 关闭容器 ──
  async function close_container({ container_id } = {}) {
    try {
      const entry = openContainers.get(container_id);
      if (!entry) {
        return { success: false, error: `Container ${container_id} not found` };
      }
      entry.window.close();
      openContainers.delete(container_id);
      return { success: true };
    } catch (err) {
      // 即使关闭失败也移除记录
      openContainers.delete(container_id);
      return { success: false, error: err.message };
    }
  }

  // ── 获取容器内容 ──
  function get_container_snapshot({ container_id } = {}) {
    try {
      const entry = openContainers.get(container_id);
      if (!entry) {
        return { success: false, error: `Container ${container_id} not found` };
      }
      const items = (entry.window.containerItems?.() || []).map(item => {
        const d = parseItemDisplay(item);
        return {
          slot: item.slot,
          name: item.name,
          type: item.type,
          count: item.count,
          display_name: item.displayName,
          custom_name: d.custom_name,
          lore: d.lore,
          // 完整物品 NBT（1.21.x 组件化数据，潜影盒内容在此）——仅用于诊断/展开
          nbt: item.nbt ? JSON.stringify(item.nbt) : null,
        };
      });
      return { success: true, items, container_id };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 从容器取物品 ──
  async function withdraw_container_item({ item_type, count = 64, container_id } = {}) {
    try {
      const entry = openContainers.get(container_id);
      if (!entry) {
        return { success: false, error: `Container ${container_id} not found` };
      }
      const container = entry.window;

      // 2026-08-14 修复④：openBlock 只等 windowOpen（窗口 ID 分配），不等
      // window_items 包（slots 填充）→ 刚打开时 containerItems() 为空，立即取货
      // 会报 "Item not found"（用户反馈"挥手瞬间被传回"的根因）。这里轮询等待
      // slots 加载（最多 2s），消除时序问题。
      let items = container.containerItems();
      const waitStart = Date.now();
      while (items.length === 0 && Date.now() - waitStart < 2000) {
        await new Promise(r => setTimeout(r, 150));
        items = container.containerItems();
      }

      // 查找匹配物品
      const match = items.find(item =>
        item.name === item_type || item.type?.toString() === item_type
      );
      if (!match) {
        return { success: false, error: `Item ${item_type} not found in container` };
      }

      await container.withdraw(match.type, null, Math.min(count, match.count));
      return { success: true, item: match.name, count: Math.min(count, match.count) };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 向容器存物品 ──
  async function deposit_container_item({ item_type, count = 64, container_id } = {}) {
    try {
      const entry = openContainers.get(container_id);
      if (!entry) {
        return { success: false, error: `Container ${container_id} not found` };
      }
      const container = entry.window;
      const items = bot.inventory.items();

      const match = items.find(item =>
        item.name === item_type || item.type?.toString() === item_type
      );
      if (!match) {
        return { success: false, error: `Item ${item_type} not found in inventory` };
      }

      await container.deposit(match.type, null, Math.min(count, match.count));
      return { success: true, item: match.name, count: Math.min(count, match.count) };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 丢弃背包物品 ──
  // 支持两种模式：
  //   1) 指定 slot（精确槽位丢弃）：只丢该槽位的物品（tossStack 整组 / 窗口点击精确数量）。
  //      ——修复「按类型全局 findItemRange 找第一个槽位」导致丢错槽位的问题。
  //   2) 仅 item_type（批量丢弃语义）：按类型在背包中查找凑足数量（保持原逻辑）。
  async function drop_item({ item_type, count = 64, slot = null } = {}) {
    try {
      let match = null;
      if (slot !== null && slot !== undefined && slot !== '') {
        // 精确槽位：只操作该槽位
        match = bot.inventory.slots[slot];
        if (!match) {
          return { success: false, error: `No item in slot ${slot}` };
        }
        if (item_type && match.name !== item_type && match.type?.toString() !== item_type) {
          return { success: false, error: `Slot ${slot} contains ${match.name}, not ${item_type}` };
        }
      } else {
        // 按类型：全背包找匹配（遍历完整 slots，含副手/盔甲/合成——items() 不含这些槽位）
        for (let i = 0; i < bot.inventory.slots.length; i++) {
          const it = bot.inventory.slots[i];
          if (it && (it.name === item_type || it.type?.toString() === item_type)) {
            match = it;
            break;
          }
        }
        if (!match) {
          return { success: false, error: `Item ${item_type} not found in inventory` };
        }
      }

      const dropCount = Math.min(Number(count) || match.count, match.count);
      if (dropCount >= match.count) {
        // 整组丢弃：拿起 → 丢出 → 关闭窗口（tossStack 按 item.slot 精确操作）
        await bot.tossStack(match);
      } else {
        // 精确数量（按槽位）：拿起整组 → 右键虚空丢 N 个 → 剩余放回
        await bot.clickWindow(match.slot, 0, 0);   // 拿起整组
        for (let i = 0; i < dropCount; i++) {
          await bot.clickWindow(-999, 1, 0);        // 右键虚空 = 丢弃 1 个
        }
        if (bot.inventory.selectedItem) {
          await bot.clickWindow(match.slot, 0, 0);  // 剩余放回原槽位
        }
      }
      return { success: true, item: match.name, count: dropCount, slot: match.slot };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 移动/交换背包槽位（mineflayer 原生窗口点击：拿起源槽 → 放到目标槽） ──
  // slot / dest_slot 均为 bot.inventory 原始槽位（0-45，由 Python 端负责
  // 「前端标准槽位 → 原始槽位」的反向映射，与 get_inventory_snapshot 归一化成对）。
  async function move_item({ slot, dest_slot } = {}) {
    try {
      if (slot === undefined || dest_slot === undefined) {
        return { success: false, error: 'slot and dest_slot are required' };
      }
      if (typeof slot !== 'number' || typeof dest_slot !== 'number') {
        return { success: false, error: 'slot/dest_slot must be numbers' };
      }
      if (slot === dest_slot) {
        return { success: false, error: 'source and destination slot are the same' };
      }
      if (slot < 0 || slot > 45 || dest_slot < 0 || dest_slot > 45) {
        return { success: false, error: 'slot must be in 0-45' };
      }
      const srcItem = bot.inventory.slots[slot];
      if (!srcItem) {
        return { success: false, error: `No item in source slot ${slot}` };
      }
      await bot.moveSlotItem(slot, dest_slot);
      return {
        success: true,
        from: slot,
        to: dest_slot,
        item: { name: srcItem.name, count: srcItem.count },
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 使用物品（吃食物等） ──
  // 指定 slot / item_type：自动装备到手持（equip 会移到快捷栏并选中）后 bot.consume() 食用；
  // 不指定：直接使用当前手持物品。
  async function use_item({ item_type = null, slot = null } = {}) {
    try {
      let item = null;
      if (slot !== null && slot !== undefined && slot !== '') {
        item = bot.inventory.slots[slot];
        if (!item) {
          return { success: false, error: `No item in slot ${slot}` };
        }
        if (item_type && item.name !== item_type && item.type?.toString() !== item_type) {
          return { success: false, error: `Slot ${slot} contains ${item.name}, not ${item_type}` };
        }
      } else if (item_type) {
        for (let i = 0; i < bot.inventory.slots.length; i++) {
          const it = bot.inventory.slots[i];
          if (it && (it.name === item_type || it.type?.toString() === item_type)) {
            item = it;
            break;
          }
        }
        if (!item) {
          return { success: false, error: `Item ${item_type} not found in inventory` };
        }
      }

      if (item) {
        // 装备到手持：物品在快捷栏则直接选中；否则移到快捷栏空槽并选中
        await bot.equip(item, 'hand');
        // 等待 heldItem 更新（moveSlotItem / setQuickBarSlot 后立即读可能仍是旧值）
        await new Promise(r => setTimeout(r, 400));
      }
      if (!bot.heldItem) {
        return { success: false, error: 'No item in hand' };
      }
      const name = bot.heldItem.name;
      try {
        await bot.consume();
        return { success: true, item: name, action: 'consume' };
      } catch (err) {
        // consume 失败：食物已满 / 不可食用（超时等）→ 回退 activateItem 直接使用一次？
        // 不，保持明确错误提示，避免误用（如拿着剑点使用挥空）。
        return { success: false, item: name, error: err.message };
      }
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 窗口内点击（左键/右键物品，2026-08-12） ──
  // target="inventory"：玩家背包（slot 为原始槽位 0-45，Python 端已映射）
  // target="container"：已打开容器（slot 为窗口内槽位 0..n-1）
  // mouse_button：0=左键（拿/放整组） 1=右键（拿/放半组）；mode：0=普通点击
  // 若服务器因点击打开了新窗口（快捷潜影盒 GUI）→ 自动注册并返回 new_container_id
  async function click_window({ target = 'inventory', container_id = null, slot, mouse_button = 0, mode = 0 } = {}) {
    try {
      let window;
      if (target === 'container') {
        const entry = openContainers.get(container_id);
        if (!entry) return { success: false, error: `Container ${container_id} not found` };
        window = entry.window;
      } else {
        window = bot.inventory;
      }
      if (slot == null || typeof slot !== 'number' || (slot < 0 && slot !== -999)) {
        return { success: false, error: 'slot is required (>=0, or -999 for void drop)' };
      }
      if (![0, 1].includes(Number(mouse_button))) {
        return { success: false, error: 'mouse_button must be 0 (left) or 1 (right)' };
      }
      await bot.clickWindow(slot, Number(mouse_button), Number(mode) || 0);
      const holding = !!(window.selectedItem && window.selectedItem.count > 0);
      // 点击可能触发服务器打开新窗口（快捷潜影盒）→ 自动注册并返回新 container_id
      const newCid = await registerOpenedWindowIfNew();
      return {
        success: true,
        target,
        slot,
        mouse_button: Number(mouse_button),
        holding,
        new_container_id: newCid || null,
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  /** 当前打开的窗口信息（调试：判断服务器弹了什么窗口类型） */
  function getCurrentWindowInfo() {
    const w = bot.currentWindow;
    if (!w) return null;
    return {
      type: w.type || '',
      title: windowTitleText(w.title),
      slot_count: typeof w.inventoryStart === 'number' ? w.inventoryStart : null,
    };
  }

  /** 当前窗口查询（2026-08-12）：前端挂载时调用 → 常驻显示已打开的 GUI 窗口 */
  function get_current_window({} = {}) {
    const w = bot.currentWindow;
    if (!w) {
      return { success: true, opened: false, container_id: null, items: [] };
    }
    let cid = null;
    for (const [id, entry] of openContainers.entries()) {
      if (entry.window === w) { cid = id; break; }
    }
    let items = [];
    if (cid) {
      try {
        items = (w.containerItems?.() || []).map(it => {
          const d = parseItemDisplay(it);
          return {
            slot: it.slot,
            name: it.name,
            type: it.type,
            count: it.count,
            display_name: it.displayName,
            custom_name: d.custom_name,
            lore: d.lore,
          };
        });
      } catch (e) { items = []; }
    }
    const entry = cid ? openContainers.get(cid) : null;
    return {
      success: true,
      opened: !!cid,
      container_id: cid,
      block_name: entry ? (entry.blockName || windowTitleText(w.title) || 'container') : (windowTitleText(w.title) || null),
      slot_count: typeof w.inventoryStart === 'number' ? w.inventoryStart : 27,
      type: w.type || '',
      items,
    };
  }

  // ── 右键使用手持物品（快捷潜影盒/末影珍珠等，2026-08-12） ──
  // 需先由前端设为手持（select_hotbar）；若服务器弹出新容器窗口则自动注册返回
  async function activate_item({} = {}) {
    try {
      if (!bot.heldItem) return { success: false, error: 'No item in hand' };
      bot.activateItem();
      // 等待服务器处理（GUI 打开/右键效果），再检查是否有新容器窗口
      await new Promise(r => setTimeout(r, 800));
      const newCid = await registerOpenedWindowIfNew();
      console.log(`[activate_item] held=${bot.heldItem.name} opened=${!!newCid} window=${getCurrentWindowInfo() ? getCurrentWindowInfo().type : 'none'}`);
      return {
        success: true,
        item: bot.heldItem.name,
        opened: !!newCid,
        new_container_id: newCid || null,
        current_window: getCurrentWindowInfo(),
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 右键方块（2026-08-12）：箱子 UI / 快捷潜影盒（右键方块触发）等 ──
  // 距离 >3 格自动寻路靠近（2 格）再右键；服务器插件响应后弹出 GUI →
  // windowOpen 自动注册 → 返回 new_container_id
  async function activate_block({ x, y, z } = {}) {
    try {
      const pos = new Vec3(x, y, z);
      const block = bot.blockAt(pos);
      if (!block || block.type === 0) {
        return { success: false, error: `No block at (${x},${y},${z})` };
      }
      // 距离远 → pathfinder 先走到方块旁（2 格内），再右键
      if (bot.entity && bot.entity.position) {
        const dist = bot.entity.position.distanceTo(pos);
        if (dist > 3) {
          try {
            const { GoalNear } = require('mineflayer-pathfinder').goals;
            await Promise.race([
              bot.pathfinder.goto(new GoalNear(x, y, z, 2)),
              new Promise((resolve) => setTimeout(resolve, 15000)),
            ]);
          } catch (err) {
            // 寻路失败/超时不阻塞，仍尝试直接右键（可能失败）
          }
        }
      }
      bot.activateBlock(block);
      // 等待服务器处理（GUI 打开），再检查是否有新容器窗口
      await new Promise(r => setTimeout(r, 1000));
      const newCid = await registerOpenedWindowIfNew();
      console.log(`[activate_block] block=${block.name} opened=${!!newCid} window=${getCurrentWindowInfo() ? getCurrentWindowInfo().type : 'none'}`);
      return {
        success: true,
        block: block.name,
        opened: !!newCid,
        new_container_id: newCid || null,
        current_window: getCurrentWindowInfo(),
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 装备物品到副手（2026-08-14 模块A：猪排等食物放副手） ──
  // 从背包任意位置（主背包/快捷栏）找 item_type 并装备到副手（slot 45）。
  async function equip_offhand({ item_type } = {}) {
    try {
      if (!item_type) {
        return { success: false, error: 'item_type is required' };
      }
      // 遍历完整 slots（含主背包/快捷栏，不含盔甲/副手），找目标物品
      let target = null;
      for (let i = 0; i < bot.inventory.slots.length; i++) {
        const it = bot.inventory.slots[i];
        if (it && (it.name === item_type || it.type?.toString() === item_type)) {
          target = it;
          break;
        }
      }
      if (!target) {
        return { success: false, error: `Item ${item_type} not found in inventory` };
      }
      await bot.equip(target, 'off-hand');
      // 等待副手槽位更新
      await new Promise(r => setTimeout(r, 400));
      const offhand = bot.inventory.slots[45];
      return {
        success: true,
        item: (offhand && offhand.name) || target.name,
        slot: 45,
      };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  // ── 吃副手食物（2026-08-14 模块A：主手拿方块时按住右键吃副手猪排） ──
  // Minecraft 机制：主手物品无 use 动作（如混凝土方块）时，按住右键会
  // 持续食用副手食物。这里按住 use 直到吃完 / 饱食度满 / 3s 超时。
  const FOOD_NAMES = new Set([
    'cooked_porkchop', 'porkchop', 'cooked_beef', 'beef', 'cooked_chicken', 'chicken',
    'bread', 'golden_carrot', 'cooked_mutton', 'mutton', 'cooked_cod', 'cod',
    'cooked_salmon', 'salmon', 'baked_potato', 'carrot', 'apple', 'golden_apple',
    'enchanted_golden_apple', 'suspicious_stew', 'beetroot_soup', 'mushroom_stew',
    'rabbit_stew', 'sweet_berries', 'glow_berries', 'honey_bottle', 'dried_kelp',
    'melon_slice', 'cookie', 'cooked_rabbit', 'rabbit', 'beetroot', 'pumpkin_pie',
  ]);
  async function consume_offhand({} = {}) {
    try {
      const offhand = bot.inventory.slots[45];
      if (!offhand) {
        return { success: false, error: 'No item in offhand' };
      }
      const name = offhand.name;
      if (!FOOD_NAMES.has(name)) {
        return { success: false, error: `Offhand item ${name} is not food`, item: name };
      }
      const startCount = offhand.count;
      const startFood = bot.food || 0;
      // 副手进食：mineflayer 的 bot.consume() 只吃主手（set_cooldown 按 heldItem
      // 匹配），副手食物需手动持续发送 use_item(hand=1) 直到吃掉一个 / 饱了 / 超时。
      const start = Date.now();
      while (Date.now() - start < 3000) {
        bot.activateItem(true); // 使用副手物品（use_item hand=1）
        await new Promise(r => setTimeout(r, 250));
        const cur = bot.inventory.slots[45];
        if (!cur || cur.name !== name) break;      // 副手食物被吃完了
        if (cur.count < startCount) break;          // 吃掉了一个
        if ((bot.food || 0) >= 20) break;           // 饱食度已满
      }
      try { bot.deactivateItem(); } catch (e) { /* 忽略 */ }
      return {
        success: true,
        item: name,
        food: bot.food || startFood,
        health: bot.health || 20,
      };
    } catch (err) {
      try { bot.deactivateItem(); } catch (e) { /* 忽略 */ }
      return { success: false, error: err.message };
    }
  }

  return {
    select_hotbar_item,
    set_quick_bar_slot,
    get_inventory_snapshot,
    open_container_at,
    close_container,
    get_container_snapshot,
    withdraw_container_item,
    deposit_container_item,
    drop_item,
    move_item,
    use_item,
    click_window,
    activate_item,
    activate_block,
    get_current_window,
    equip_offhand,
    consume_offhand,
  };
}

module.exports = { createInventoryHandlers };
