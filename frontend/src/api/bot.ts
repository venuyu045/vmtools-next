import client from './client'

export const botApi = {
  list() {
    return client.get('/mcc-bots')
  },
  get(botId: string) {
    return client.get(`/mcc-bots/${botId}`)
  },
  create(data: {
    bot_id: string
    name?: string
    ws_host?: string
    ws_port?: number
    ws_password?: string
    mc_username?: string
    mc_account_type?: string
    mc_server_host?: string
    mc_server_port?: number
    organization_id?: string
  }) {
    return client.post('/mcc-bots', data)
  },
  delete(botId: string) {
    return client.delete(`/mcc-bots/${botId}`)
  },
  connect(botId: string, data: { host?: string; port?: number; auth_token?: string }) {
    return client.post(`/mcc-bots/${botId}/connect`, data)
  },
  disconnect(botId: string) {
    return client.post(`/mcc-bots/${botId}/disconnect`)
  },
  // Inventory
  getInventory(botId: string, mcpPort?: number) {
    return client.get(`/mcc-bots/${botId}/inventory`, { params: { mcp_port: mcpPort || 0 } })
  },
  inventoryAction(botId: string, data: { inventory_id: number; slot_id: number; action: string }) {
    return client.post(`/mcc-bots/${botId}/inventory/action`, data)
  },
  inventoryDrop(botId: string, data: { item_type: string; count: number; inventory_id?: number; slot_id?: number }) {
    return client.post(`/mcc-bots/${botId}/inventory/drop`, data)
  },
  inventorySelectHotbar(botId: string, slot: number) {
    return client.post(`/mcc-bots/${botId}/inventory/select-hotbar`, { slot })
  },
  inventoryMove(botId: string, data: { slot_id: number; dest_slot_id: number }) {
    return client.post(`/mcc-bots/${botId}/inventory/move`, data)
  },
  inventoryUse(botId: string, data: { item_type?: string; slot_id?: number }) {
    return client.post(`/mcc-bots/${botId}/inventory/use`, data)
  },
  // 窗口内点击（左键/右键物品，mineflayer only，2026-08-12）
  inventoryClick(botId: string, data: {
    target: 'inventory' | 'container'; slot: number; mouse_button?: 0 | 1; mode?: number; container_id?: string
  }) {
    return client.post(`/mcc-bots/${botId}/inventory/click`, data)
  },
  // 右键使用手持物品（快捷潜影盒等，mineflayer only，2026-08-12）
  inventoryActivateItem(botId: string) {
    return client.post(`/mcc-bots/${botId}/inventory/activate-item`, {})
  },
  // 右键方块（箱子 UI / 快捷潜影盒方块触发，mineflayer only，2026-08-12）
  inventoryActivateBlock(botId: string, data: { x: number; y: number; z: number }) {
    return client.post(`/mcc-bots/${botId}/inventory/activate-block`, data)
  },
  // 当前打开的容器窗口（常驻面板查询，mineflayer only，2026-08-12）
  currentWindow(botId: string) {
    return client.get(`/mcc-bots/${botId}/inventory/current-window`)
  },
  // 移动控制（mineflayer only）
  control(botId: string, data: { direction: string; state: boolean }) {
    return client.post(`/mcc-bots/${botId}/control`, data)
  },
  getState(botId: string) {
    return client.get(`/mcc-bots/${botId}/state`)
  },
  jump(botId: string) {
    return client.post(`/mcc-bots/${botId}/jump`)
  },
  sneak(botId: string, state?: boolean) {
    return client.post(`/mcc-bots/${botId}/sneak`, state === undefined ? {} : { state })
  },
  look(botId: string, data: { yaw: number; pitch?: number; force?: boolean }) {
    return client.post(`/mcc-bots/${botId}/look`, data)
  },
  // 战斗（mineflayer only，2026-08-10）
  combatEntities(botId: string, radius = 16, targetTypes: string[] = []) {
    return client.get(`/mcc-bots/${botId}/combat/entities`, {
      params: { radius, target_types: targetTypes.join(',') },
    })
  },
  combatAutoAttack(botId: string, data: {
    enabled: boolean; radius?: number; scan_radius: number; attack_radius: number;
    target_types: string[]; interval_tick: number; interval_mode: string;
    stop_durability: number; move_to_target: boolean;
    enable_sprint_attack: boolean; enable_jump_crit: boolean;
    enable_wtap: boolean; enable_stap: boolean; enable_strafe: boolean;
    anti_afk?: boolean; anti_afk_interval_ms?: number
  }) {
    return client.post(`/mcc-bots/${botId}/combat/auto-attack`, data)
  },
  combatAttack(botId: string, data: {
    target_id?: number | null; target_type?: string | null; move_to_target?: boolean;
    scan_radius?: number; attack_radius?: number
  }) {
    return client.post(`/mcc-bots/${botId}/combat/attack`, data)
  },
  combatGuard(botId: string, data: {
    enabled: boolean; x?: number | null; y?: number | null; z?: number | null;
    radius?: number; scan_radius: number; attack_radius: number;
    target_types: string[]; interval_tick: number; stop_durability: number; move_to_target: boolean
  }) {
    return client.post(`/mcc-bots/${botId}/combat/guard`, data)
  },
  combatStatus(botId: string) {
    return client.get(`/mcc-bots/${botId}/combat/status`)
  },
  combatStop(botId: string) {
    return client.post(`/mcc-bots/${botId}/combat/stop`)
  },
  // 容器（大箱子 UI / 附加箱子，mineflayer only，2026-08-11）
  scanContainers(botId: string, maxCount = 200) {
    return client.get(`/mcc-bots/${botId}/inventory/containers`, { params: { max_count: maxCount } })
  },
  openContainer(botId: string, x: number, y: number, z: number) {
    return client.post(`/mcc-bots/${botId}/inventory/container/open`, { x, y, z })
  },
  containerSnapshot(botId: string, containerId: string) {
    return client.get(`/mcc-bots/${botId}/inventory/container/${containerId}`)
  },
  closeContainer(botId: string, containerId: string) {
    return client.post(`/mcc-bots/${botId}/inventory/container/${containerId}/close`)
  },
  // 永昼：睡觉（mineflayer only，2026-08-16）
  sleepStatus(botId: string) {
    return client.get(`/mcc-bots/${botId}/sleep/status`)
  },
  saveSleepPoint(botId: string, point: { x: number; y: number; z: number }) {
    return client.put(`/mcc-bots/${botId}/sleep/point`, point)
  },
  clearSleepPoint(botId: string) {
    return client.delete(`/mcc-bots/${botId}/sleep/point`)
  },
  sleepNow(botId: string) {
    return client.post(`/mcc-bots/${botId}/sleep`)
  },
}
