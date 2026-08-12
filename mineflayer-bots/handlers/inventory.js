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

// 容器类窗口类型（对齐 mineflayer chest.js allowedWindowTypes）
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
]);

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
    if (broadcast && createEvent) {
      try { broadcast(createEvent(name, data)); } catch (e) { /* 忽略 */ }
    }
  }

  /** 检查 bot.currentWindow 是否为新打开的容器窗口；是则自动注册并返回 container_id */
  async function registerOpenedWindowIfNew() {
    const w = bot.currentWindow;
    if (!w) return null;
    for (const entry of openContainers.values()) {
      if (entry.window === w) return null; // 已注册
    }
    if (!CONTAINER_WINDOW_TYPES.has(w.type)) return null; // 非容器类（如合成/附魔/村民交易）
    const cid = uuidv4();
    openContainers.set(cid, {
      window: w,
      openedAt: Date.now(),
      position: null,
      blockName: w.title || 'container',
      auto: true,
    });
    emitEvent('container_opened', {
      container_id: cid,
      block_name: w.title || 'container',
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
      // 自动注册（点击/激活触发的服务器 GUI，如快捷潜影盒）
      if (CONTAINER_WINDOW_TYPES.has(window.type)) {
        const cid = registerOpenedWindowIfNewSync(window);
        if (cid) {
          emitEvent('container_opened', {
            container_id: cid,
            block_name: window.title || 'container',
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
      blockName: window.title || 'container',
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
    return { durability, max_durability: maxDur, enchantments };
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
        items.push({
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
        });
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
      const block = bot.blockAt(pos);

      if (!block || block.type === 0) {
        return { success: false, error: `No block at (${x},${y},${z})` };
      }

      // 距离远 → pathfinder 先走到容器旁（2 格内），再右键打开
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

      const containerId = uuidv4();
      expectedContainers.add(containerId); // 标记主动打开，windowOpen 时跳过自动注册

      let container;
      try {
        container = await Promise.race([
          bot.openContainer(block),
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
      const items = (entry.window.containerItems?.() || []).map(item => ({
        slot: item.slot,
        name: item.name,
        type: item.type,
        count: item.count,
        display_name: item.displayName,
        // 完整物品 NBT（1.21.x 组件化数据，潜影盒内容在此）——仅用于诊断/展开
        nbt: item.nbt ? JSON.stringify(item.nbt) : null,
      }));
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
      const items = container.containerItems();

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

  // ── 右键使用手持物品（快捷潜影盒/末影珍珠等，2026-08-12） ──
  // 需先由前端设为手持（select_hotbar）；若服务器弹出新容器窗口则自动注册返回
  async function activate_item({} = {}) {
    try {
      if (!bot.heldItem) return { success: false, error: 'No item in hand' };
      bot.activateItem();
      // 等待服务器处理（GUI 打开/右键效果），再检查是否有新容器窗口
      await new Promise(r => setTimeout(r, 800));
      const newCid = await registerOpenedWindowIfNew();
      return {
        success: true,
        item: bot.heldItem.name,
        opened: !!newCid,
        new_container_id: newCid || null,
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
      return {
        success: true,
        block: block.name,
        opened: !!newCid,
        new_container_id: newCid || null,
      };
    } catch (err) {
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
  };
}

module.exports = { createInventoryHandlers };
