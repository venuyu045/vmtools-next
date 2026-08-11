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
    target_types: string[]; interval_ms: number; interval_mode: string;
    stop_durability: number; move_to_target: boolean;
    enable_sprint_attack: boolean; enable_jump_crit: boolean;
    enable_wtap: boolean; enable_stap: boolean; enable_strafe: boolean
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
    target_types: string[]; interval_ms: number; stop_durability: number; move_to_target: boolean
  }) {
    return client.post(`/mcc-bots/${botId}/combat/guard`, data)
  },
  combatStatus(botId: string) {
    return client.get(`/mcc-bots/${botId}/combat/status`)
  },
  combatStop(botId: string) {
    return client.post(`/mcc-bots/${botId}/combat/stop`)
  },
}
