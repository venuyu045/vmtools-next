import client from './client'

// ══════════════════════════════════════════════════════════════════════════
// 类型定义：与后端契约对齐（docs/dev/map-art-重构方案-2026-10-28.md §四）
// ══════════════════════════════════════════════════════════════════════════

/** 建造模式：column = 多 Bot 列式协作（2026-10-28 起全链路默认）；strip = 旧分区独立 */
export type MapArtBuildMode = 'column' | 'strip'

/** 任务控制动作（POST /tasks/{id}/control 的 action） */
export type MapArtControlAction = 'start' | 'pause' | 'resume' | 'stop'

/**
 * 每 Bot 进度字段（修 A1）。
 *
 * 后端实际下发的是 `blocks_placed / blocks_total / place_rate`：
 *   - `GET /tasks/{id}` 的 bots[]（build_map_art.py get_task）
 *   - WS `build_bot_status`（map_art_coordinator / multi_bot_coordinator）
 * 而契约 §四 又给 `GET /tasks/{id}` 补了 `placed / total / rate` 别名；
 * WS `build_progress.bots` 目前只给短名。
 *
 * 三处命名不一致 → **模板里禁止直接读某个字段**，一律走 `botProgress()` 归一化。
 */
export interface MapArtBotProgressFields {
  blocks_placed?: number | null
  blocks_total?: number | null
  place_rate?: number | null
  placed?: number | null
  total?: number | null
  rate?: number | null
}

/** 归一化后的每 Bot 进度（百分比/文本/速率都由它算，防 undefined / NaN / 越界） */
export interface MapArtBotProgressView {
  placed: number
  total: number
  rate: number
  pct: number
}

/** bots[] 单条（GET /tasks/{id} 与 build_bot_status 的并集；列式额外带 column/squad_*） */
export interface MapArtTaskBot extends MapArtBotProgressFields {
  bot_id: string
  bot_name?: string
  name?: string
  state?: string
  /** 列式：本 bot 负责的列号（0-based，展示用世界 X） */
  column?: number | null
  /** 列式：本列世界 X（origin_x + column） */
  world_x?: number | null
  /** 列式：当前排号（1-based） */
  squad_index?: number | null
  /** 列式：当前排方向（1=y+ / -1=y-） */
  squad_direction?: number | null
  current_row?: number | null
  position?: { x?: number | null; y?: number | null; z?: number | null } | null
  health?: number | null
  food?: number | null
  region?: { x_start: number; x_end: number; z_start: number; z_end: number } | null
}

export interface MapArtTaskMaterial {
  item_id: string
  display_name?: string
  required?: number
  placed?: number
  color_hex?: string
}

export interface MapArtTaskProgressInfo {
  total_blocks?: number
  placed_blocks?: number
  verified_blocks?: number
  /** 契约 §四：启动/行尾/完成对账统计（排障用，可能缺失） */
  reconcile?: Record<string, unknown>
}

/** GET /tasks/{id} 返回体 */
export interface MapArtTaskDetail {
  task_id: string
  name?: string
  status?: string
  build_mode?: MapArtBuildMode | string
  rotation?: number
  squad_index?: number
  projection?: {
    file_path?: string
    name?: string
    author?: string
    size_x?: number
    size_y?: number
    size_z?: number
    total_blocks?: number
  }
  origin?: { x: number; y: number; z: number }
  progress?: MapArtTaskProgressInfo
  /** fetchTask 展平后的顶层字段（模板直接用） */
  placed_blocks?: number
  total_blocks?: number
  materials?: MapArtTaskMaterial[]
  bots?: MapArtTaskBot[]
  created_at?: string
  started_at?: string | null
  completed_at?: string | null
  error_message?: string
}

/** GET /tasks 列表项 */
export interface MapArtTaskSummary {
  task_id: string
  name: string
  status: string
  projection_name: string
  projection_size_x: number
  projection_size_z: number
  total_blocks: number
  placed_blocks: number
  created_at: string
  /** 契约 §四：列表也带 build_mode（老后端可能没有） */
  build_mode?: MapArtBuildMode | string
}

/** WS build_progress 载荷（MapArtBuildState.__dict__） */
export interface MapArtBuildProgress {
  task_id: string
  /** 契约 §四：新增 "paused"（A2 修复后列式暂停态会真正推出来） */
  status?: string
  total_blocks?: number
  placed_blocks?: number
  bots?: MapArtTaskBot[]
  materials?: Record<string, { required?: number; placed?: number }>
  elapsed_sec?: number
  eta_sec?: number
  net_rate?: number
  net_eta?: number
  squad_index?: number
  build_mode?: MapArtBuildMode | string
  error_message?: string
}

/** WS build_alert（A3：join/control 无权限等会回这个，前端必须给出可见提示） */
export interface MapArtBuildAlert {
  type?: string
  message?: string
}

/** WS build_squad_status 的单列条目（契约 §四新增事件） */
export interface MapArtSquadColumn {
  bot_id: string
  /** 列号 0-based */
  column_x?: number
  /** 该列世界 X 坐标（origin_x + column_x），展示优先用它 */
  world_x?: number
  done?: boolean
  placed?: number
  total?: number
  /** 该 bot 当前状态（idle/placing/waiting/offline…） */
  state?: string
}

/**
 * WS build_squad_status（契约 §四新增，**可选订阅**）：
 * 事件不存在时前端不得报错 —— 整块 UI 静默不渲染。
 * 实际 payload（backend/core/map_art/column_engine.py `_squad_payload`）：
 * {task_id, squad_index, direction, total_columns, total_rows,
 *  remaining_columns, offline_bots[], columns[{bot_id, column_x, world_x, done, placed, total, state}]}
 */
export interface MapArtSquadStatus {
  task_id: string
  squad_index?: number
  /** 排方向：后端 SquadState.direction 为 1 / -1；契约文本为 y+/y-，两种都兼容 */
  direction?: number | string
  total_columns?: number
  total_rows?: number
  columns?: MapArtSquadColumn[]
  remaining_columns?: number
  offline_bots?: string[]
}

// ══════════════════════════════════════════════════════════════════════════
// 归一化 helper
// ══════════════════════════════════════════════════════════════════════════

function toNum(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

/**
 * 每 Bot 进度归一化（修 A1「每 bot 进度恒 0%」）。
 *
 * 取值顺序：`blocks_placed/blocks_total/place_rate`（后端权威字段）
 *          → `placed/total/rate`（契约新增别名 + build_progress.bots 短名）。
 * 两者都缺才回落 0；百分比夹在 0–100 防 NaN / 越界。
 */
export function botProgress(bot?: MapArtBotProgressFields | null): MapArtBotProgressView {
  if (!bot) return { placed: 0, total: 0, rate: 0, pct: 0 }
  const placed = toNum(bot.blocks_placed ?? bot.placed)
  const total = toNum(bot.blocks_total ?? bot.total)
  const rate = toNum(bot.place_rate ?? bot.rate)
  const pct = total > 0 ? Math.min(100, Math.max(0, Math.round((placed / total) * 100))) : 0
  return { placed, total, rate, pct }
}

/** 排方向展示：1 / 'y+' / '+y' → 'y+'；-1 / 'y-' / '-y' → 'y-' */
export function squadDirectionLabel(direction?: number | string | null): string {
  if (direction === null || direction === undefined || direction === '') return '-'
  if (typeof direction === 'string') {
    const s = direction.trim().toLowerCase()
    if (s === '1' || s === 'y+' || s === '+y' || s === 'plus' || s === 'positive') return 'y+'
    if (s === '-1' || s === 'y-' || s === '-y' || s === 'minus' || s === 'negative') return 'y-'
    return direction
  }
  return direction >= 0 ? 'y+' : 'y-'
}

/** 建造模式中文名 */
export function buildModeLabel(mode?: string | null): string {
  return mode === 'column' ? '多Bot协作（列式）' : '分区独立'
}

/**
 * Bot 列表合并（A1 补充 + 保留 per-bot state）。
 *
 * `build_bot_status` 不带 region，`build_progress.bots` 不带 position/column，
 * 直接整体替换会来回丢字段（位置/列号闪烁）→ 按 bot_id 合并：新值优先、
 * 缺失字段保留旧值，state 永远不因缺失被清空。
 * `allowEmpty=false` 时空数组原样返回旧列表（防瞬时抖动把 Bot 列表刷空）；
 * REST 全量刷新传 true（成员关系以服务端为准，允许变成空）。
 */
export function mergeBotList(
  prev: MapArtTaskBot[] | null | undefined,
  incoming: MapArtTaskBot[] | null | undefined,
  allowEmpty = false,
): MapArtTaskBot[] {
  const old = prev || []
  if (!Array.isArray(incoming)) return old
  if (!incoming.length && !allowEmpty) return old
  const prevMap = new Map(old.map(b => [b.bot_id, b]))
  return incoming.map((nb) => {
    const before = prevMap.get(nb.bot_id)
    if (!before) return nb
    const patch: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(nb)) {
      if (v !== undefined && v !== null) patch[k] = v
    }
    const merged = { ...before, ...patch } as MapArtTaskBot
    if (!merged.state) merged.state = before.state
    return merged
  })
}

// ══════════════════════════════════════════════════════════════════════════
// API 封装
// ══════════════════════════════════════════════════════════════════════════

export const mapArtApi = {
  listTasks(params?: { status?: string }) {
    return client.get<{ tasks: MapArtTaskSummary[]; total: number }>('/build/map-art/tasks', { params })
  },
  getTask(taskId: string) {
    return client.get<MapArtTaskDetail>(`/build/map-art/tasks/${taskId}`)
  },
  createTask(data: {
    name: string
    projection_file_path: string
    origin_x?: number
    origin_y?: number
    origin_z?: number
    bot_ids?: string[]
    organization_id?: string
    rotation?: number
    /** 契约 §四：全链路默认 column */
    build_mode?: MapArtBuildMode
  }) {
    return client.post('/build/map-art/tasks', data)
  },
  controlTask(taskId: string, action: MapArtControlAction) {
    return client.post(`/build/map-art/tasks/${taskId}/control`, { action })
  },
  deleteTask(taskId: string) {
    return client.delete(`/build/map-art/tasks/${taskId}`)
  },
  uploadProjection(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post('/build/map-art/projections/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  /** @deprecated B11 死协议：3D 画布（BuildMapCanvas）已删除，全仓无调用方，仅保留兼容 */
  getBlocks(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/blocks`)
  },
  /** @deprecated B11 死协议：同上，无调用方 */
  getPlacedBlocks(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/blocks/placed`)
  },
  /** 2026-08-14 终端：活动日志（REST 轮询兜底，不依赖 socket） */
  getLogs(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/logs`)
  },
  /** 2026-08-14：正在工作的 bot 背包快照（实时终端下方 bot 背包面板轮询） */
  getBotsInventory(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/bots/inventory`)
  },
  /** P2-27：动态 bot 分配（运行中任务 add/remove） */
  manageBot(taskId: string, action: 'add' | 'remove', botId: string) {
    return client.post(`/build/map-art/tasks/${taskId}/bots`, { action, bot_id: botId })
  },
  /** 2026-08-14：补货传送指令（go/save/return 三个可自定义） */
  getSupplyConfig(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/supply-config`)
  },
  saveSupplyConfig(taskId: string, cfg: { go: string; save: string; return: string; return_fixed?: string }) {
    return client.put(`/build/map-art/tasks/${taskId}/supply-config`, cfg)
  },
  /** 2026-08-14 模块A：食物补货配置（猪排仓库指令 + 进食阈值） */
  getFoodConfig(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/food-config`)
  },
  saveFoodConfig(taskId: string, cfg: {
    item_id: string; go_command: string; wait_after_go_ms: number;
    eat_threshold_food: number; eat_threshold_health: number
  }) {
    return client.put(`/build/map-art/tasks/${taskId}/food-config`, cfg)
  },
  getFoodBoxes(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/food-boxes`)
  },
  saveFoodBoxes(taskId: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put(`/build/map-art/tasks/${taskId}/food-boxes`, { items })
  },
  /** 2026-08-16：睡觉点（床的方块坐标，世界坐标；未配置→跳过自动睡觉） */
  getSleepPoint(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/sleep-point`)
  },
  saveSleepPoint(taskId: string, sp: { x: number; y: number; z: number }) {
    return client.put(`/build/map-art/tasks/${taskId}/sleep-point`, sp)
  },
  /** 2026-08-18：手动触发任务内 bot 睡觉（「睡觉按钮」） */
  forceBotSleep(taskId: string, botId: string) {
    return client.post(`/build/map-art/tasks/${taskId}/bots/${botId}/sleep`)
  },
  /** 2026-08-18：查询 bot 实时世界时间/昼夜/睡觉状态（状态栏数据源） */
  getBotSleepStatus(botId: string) {
    return client.get(`/mcc-bots/${botId}/sleep/status`)
  },
  /** 2026-08-14：补货潜影盒坐标（材料 ↔ 坐标，1 材料可配多坐标） */
  getSupplyBoxes(taskId: string) {
    return client.get(`/build/map-art/tasks/${taskId}/supply-boxes`)
  },
  saveSupplyBoxes(taskId: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put(`/build/map-art/tasks/${taskId}/supply-boxes`, { items })
  },
  /** 2026-08-14 三期：全局补货仓库（材料→潜影盒，任务自动复用） */
  getSupplyWarehouse() {
    return client.get('/build/map-art/supply-warehouse')
  },
  saveSupplyWarehouse(items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put('/build/map-art/supply-warehouse', { items })
  },
  /** 2026-08-14 二期：补货潜影盒模板（可复用配置） */
  listSupplyTemplates() {
    return client.get('/build/map-art/supply-templates')
  },
  createSupplyTemplate(name: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.post('/build/map-art/supply-templates', { name, items })
  },
  updateSupplyTemplate(id: number, name: string, items: { item_id: string; boxes: { x: number; y: number; z: number }[] }[]) {
    return client.put(`/build/map-art/supply-templates/${id}`, { name, items })
  },
  deleteSupplyTemplate(id: number) {
    return client.delete(`/build/map-art/supply-templates/${id}`)
  },
  applySupplyTemplate(id: number, taskId: string) {
    return client.post(`/build/map-art/supply-templates/${id}/apply`, { task_id: taskId })
  },
}
