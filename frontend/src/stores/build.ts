import { defineStore } from 'pinia'
import { buildApi } from '@/api/build'

export interface BuildTask {
  task_id: string
  bot_id: string
  projection_name: string | null
  status: string
  current_state: string
  current_layer: number
  total_layers: number
  error_message: string | null
}

export const useBuildStore = defineStore('build', {
  state: () => ({
    tasks: [] as BuildTask[],
    currentTask: null as BuildTask | null,
    loading: false,
  }),
  actions: {
    async fetchTasks() {
      this.loading = true
      try {
        const { data } = await buildApi.listTasks()
        this.tasks = data
      } finally {
        this.loading = false
      }
    },
    async fetchTask(id: string) {
      const { data } = await buildApi.getTask(id)
      this.currentTask = data
      return data
    },
    async createTask(taskData: any) {
      const { data } = await buildApi.createTask(taskData)
      this.tasks.push(data)
      return data
    },
    async startTask(id: string) {
      const { data } = await buildApi.startTask(id)
      this.updateTaskFromSocket({ task_id: id, status: data.status })
      return data
    },
    async pauseTask(id: string) {
      const { data } = await buildApi.pauseTask(id)
      this.updateTaskFromSocket({ task_id: id, status: data.status })
      return data
    },
    async resumeTask(id: string) {
      const { data } = await buildApi.resumeTask(id)
      this.updateTaskFromSocket({ task_id: id, status: data.status })
      return data
    },
    async cancelTask(id: string) {
      const { data } = await buildApi.cancelTask(id)
      this.updateTaskFromSocket({ task_id: id, status: data.status })
      return data
    },
    updateTaskFromSocket(payload: Partial<BuildTask> & { task_id: string }) {
      const idx = this.tasks.findIndex(t => t.task_id === payload.task_id)
      if (idx >= 0) {
        Object.assign(this.tasks[idx], payload)
      }
      if (this.currentTask?.task_id === payload.task_id) {
        Object.assign(this.currentTask, payload)
      }
    },
  },
})
