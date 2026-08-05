import { defineStore } from 'pinia'
import { mapArtApi } from '@/api/mapArt'

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
}

/**
 * 地图画建造任务 store（合并原建造任务后唯一保留的建造功能）。
 * 供仪表盘"建造状态"与 Socket.IO build_progress 事件共用。
 */
export const useMapArtStore = defineStore('mapArt', {
  state: () => ({
    tasks: [] as MapArtTaskSummary[],
    loading: false,
  }),
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
    /** Socket.IO build_progress 增量更新 */
    updateFromSocket(payload: Partial<MapArtTaskSummary> & { task_id: string }) {
      const idx = this.tasks.findIndex(t => t.task_id === payload.task_id)
      if (idx >= 0) {
        Object.assign(this.tasks[idx], payload)
      } else if (payload.task_id) {
        this.tasks.unshift(payload as MapArtTaskSummary)
      }
    },
  },
})