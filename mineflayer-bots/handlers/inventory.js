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
 */

const { Vec3 } = require('vec3');
const { v4: uuidv4 } = require('uuid');

// ── 全局容器映射（进程级别） ──
// { containerId: { window, openedAt, position } }
const openContainers = new Map();

/**
 * @param {import('mineflayer').Bot} bot
 */
function createInventoryHandlers(bot) {

  // ── 在快捷栏中选择物品 ──
  async function select_hotbar_item({ item_type, prefer_lowest_slot = true } = {}) {
    try {
      const items = bot.inventory.items();
      // 在快捷栏中查找匹配的物品（快捷栏槽位 36-44）
      const hotbarItems = items.filter(item => item.slot >= 36 && item.slot <= 44);
      const match = hotbarItems.find(item =>
        item.name === item_type || item.type?.toString() === item_type
      );

      if (!match) {
        // 尝试在所有背包物品中查找
        const anyMatch = items.find(item =>
          item.name === item_type || item.type?.toString() === item_type
        );
        if (!anyMatch) {
          return { success: false, error: `Item ${item_type} not found in inventory` };
        }
        // 物品在背包中但不在快捷栏
        return {
          success: false,
          error: `Item ${item_type} found at slot ${anyMatch.slot} (not in hotbar)`,
          item: { name: anyMatch.name, slot: anyMatch.slot, count: anyMatch.count },
        };
      }

      // 计算快捷栏索引 (slot 36-44 → index 0-8)
      const hotbarIndex = match.slot - 36;
      bot.setQuickBarSlot(hotbarIndex);

      return {
        success: true,
        slot: hotbarIndex,
        item: { name: match.name, count: match.count },
      };
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
      const items = bot.inventory.items().map(item => {
        const detail = itemDetail(item);
        return {
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
        };
      });
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
  async function open_container_at({ x, y, z } = {}) {
    try {
      const pos = new Vec3(x, y, z);
      const block = bot.blockAt(pos);

      if (!block || block.type === 0) {
        return { success: false, error: `No block at (${x},${y},${z})` };
      }

      const container = await bot.openContainer(block);
      const containerId = uuidv4();
      openContainers.set(containerId, {
        window: container,
        openedAt: Date.now(),
        position: { x, y, z },
        blockName: block.name,
      });

      return {
        success: true,
        container_id: containerId,
        block_name: block.name,
        slot_count: container.containerItems
          ? container.containerItems().length
          : container.slots.length,
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
        // 按类型：全背包找匹配（第一个匹配的槽位），保持原语义
        const items = bot.inventory.items();
        match = items.find(item =>
          item.name === item_type || item.type?.toString() === item_type
        );
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
  };
}

module.exports = { createInventoryHandlers };
