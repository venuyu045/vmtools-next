import { defineStore } from 'pinia'
import { mapArtApi, type MapArtTaskSummary } from '@/api/mapArt'

// 兼容原有导入路径（接口实际定义已随字段契约迁移到 @/api/mapArt）
export type { MapArtTaskSummary }

/**
 * A5 修复：socket 先到、列表还没刷新的任务，只允许「节流重新拉取列表」，
 * 绝不把半截 payload 塞进 tasks（缺 name/created_at → Dashboard 空名称卡片）。
 */
const REFETCH_MIN_INTERVAL_MS = 10_000
let lastRefetchAt = 0
let refetchTimer: number | undefined

/** build_progress 里允许写回列表的字段白名单（防止 payload 脏字段污染列表项） */
const PATCHABLE_FIELDS: (keyof MapArtTaskSummary)[] = [
  'name',
  'status',
  'projection_name',
  'projection_size_x',
  'projection_size_z',
  'total_blocks',
  'placed_blocks',
  'created_at',
  'build_mode',
]

/**
 * 地图画建造任务 store（合并原建造任务后唯一保留的建造功能）。
 * 供仪表盘"建造状态"与 Socket.IO build_progress 事件共用。
 */
export const useMapArtStore = defineStore('mapArt', {
  state: () => ({
    tasks: [] as MapArtTaskSummary[],
    loading: false,
    /** 最近一次 build_progress 快照（可能属于列表外的任务，故单独存） */
    lastProgress: null as Record<string, unknown> | null,
  }),
  getters: {
    /** P2-29：运行中的建造任务（Dashboard 卡片消费） */
    runningTasks: (state) => state.tasks.filter(t => t.status === 'running'),
    /** 已暂停的建造任务（契约 §四新增 paused 状态） */
    pausedTasks: (state) => state.tasks.filter(t => t.status === 'paused'),
  },
  actions: {
    async fetchTasks() {
      this.loading = true
      try {
        const { data } = await mapArtApi.listTasks()
        this.tasks = data.tasks || []
      } finally {
        this.loading = false
      }
    },
    /**
     * Socket.IO build_progress 增量更新（A5）。
     *
     * 只更新**已存在**的任务；任务不在列表里时不再 `unshift` 半截 payload
     * （build_progress 只有 task_id/status/placed_blocks…，没有 name/created_at，
     * 插进去就是一张空名称卡片）。需要新增条目时改为节流调用 fetchTasks()。
     */
    updateFromSocket(payload: Partial<MapArtTaskSummary> & { task_id: string }) {
      if (!payload?.task_id) return
      this.lastProgress = payload as Record<string, unknown>
      const idx = this.tasks.findIndex(t => t.task_id === payload.task_id)
      if (idx >= 0) {
        const target = this.tasks[idx] as unknown as Record<string, unknown>
        for (const key of PATCHABLE_FIELDS) {
          const value = (payload as Record<string, unknown>)[key as string]
          if (value !== undefined && value !== null) target[key as string] = value
        }
        return
      }
      // 任务不在列表：可能是新建任务（socket 先到）或列表尚未加载 → 节流重拉列表
      this.scheduleRefetch()
    },
    /** 节流重新拉取任务列表（最短间隔 10s，避免 2s 一次的 build_progress 打爆接口） */
    scheduleRefetch() {
      if (refetchTimer !== undefined || this.loading) return
      const wait = Math.max(0, REFETCH_MIN_INTERVAL_MS - (Date.now() - lastRefetchAt))
      refetchTimer = window.setTimeout(() => {
        refetchTimer = undefined
        lastRefetchAt = Date.now()
        this.fetchTasks().catch(() => { /* 拉取失败静默：下次 socket 推送会再触发 */ })
      }, wait)
    },
  },
})
