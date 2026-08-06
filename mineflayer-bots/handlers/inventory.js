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
  function get_inventory_snapshot({} = {}) {
    try {
      const items = bot.inventory.items().map(item => ({
        slot: item.slot,
        name: item.name,
        type: item.type,
        count: item.count,
        display_name: item.displayName,
        displayName: item.displayName,
        max_stack_size: item.maxStackSize,
      }));
      return {
        success: true,
        items,
        total_slots: bot.inventory.slots.length,
        held_item: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null,
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

  return {
    select_hotbar_item,
    set_quick_bar_slot,
    get_inventory_snapshot,
    open_container_at,
    close_container,
    get_container_snapshot,
    withdraw_container_item,
    deposit_container_item,
  };
}

module.exports = { createInventoryHandlers };
