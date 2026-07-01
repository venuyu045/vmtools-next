import { defineStore } from 'pinia'
import { logisticsApi } from '@/api/logistics'

export interface Waypoint {
  waypoint_id: string
  name: string
  key: string
  warehouse_fk: string | null
  container_x: number
  container_y: number
  container_z: number
  teleport_command: string
  item_name: string
  item_id: string | null
  wait_after_teleport: number
  organization_id: string | null
  created_at: string | null
}

export interface DropPoint {
  drop_point_id: string
  name: string
  teleport_command: string
  drop_x: number | null
  drop_y: number | null
  drop_z: number | null
  drop_method: string
  wait_after_teleport: number
  organization_id: string | null
  created_at: string | null
}

export interface TaskTemplate {
  template_id: string
  name: string
  source_waypoint_id: string
  drop_point_id: string
  loop_mode: string
  enabled: boolean
  organization_id: string | null
  created_at: string | null
}

export interface TaskRun {
  run_id: string
  template_id: string
  bot_id: string
  status: string
  current_state: string
  loop_count: number
  progress: number
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

export const useLogisticsStore = defineStore('logistics', {
  state: () => ({
    waypoints: [] as Waypoint[],
    dropPoints: [] as DropPoint[],
    templates: [] as TaskTemplate[],
    runs: [] as TaskRun[],
    loading: false,
  }),
  actions: {
    async fetchWaypoints() {
      const { data } = await logisticsApi.listWaypoints()
      this.waypoints = data
    },
    async createWaypoint(wp: Partial<Waypoint>) {
      const { data } = await logisticsApi.createWaypoint(wp)
      this.waypoints.push(data)
      return data
    },
    async deleteWaypoint(id: string) {
      await logisticsApi.deleteWaypoint(id)
      this.waypoints = this.waypoints.filter(w => w.waypoint_id !== id)
    },
    async fetchDropPoints() {
      const { data } = await logisticsApi.listDropPoints()
      this.dropPoints = data
    },
    async createDropPoint(dp: Partial<DropPoint>) {
      const { data } = await logisticsApi.createDropPoint(dp)
      this.dropPoints.push(data)
      return data
    },
    async deleteDropPoint(id: string) {
      await logisticsApi.deleteDropPoint(id)
      this.dropPoints = this.dropPoints.filter(d => d.drop_point_id !== id)
    },
    async fetchTemplates() {
      const { data } = await logisticsApi.listTemplates()
      this.templates = data
    },
    async createTemplate(tpl: Partial<TaskTemplate>) {
      const { data } = await logisticsApi.createTemplate(tpl)
      this.templates.push(data)
      return data
    },
    async deleteTemplate(id: string) {
      await logisticsApi.deleteTemplate(id)
      this.templates = this.templates.filter(t => t.template_id !== id)
    },
    async toggleTemplate(id: string) {
      const { data } = await logisticsApi.toggleTemplate(id)
      const idx = this.templates.findIndex(t => t.template_id === id)
      if (idx >= 0) this.templates[idx] = data
      return data
    },
    async fetchRuns() {
      const { data } = await logisticsApi.listRuns()
      this.runs = data
    },
    async startTask(templateId: string, botId: string) {
      const { data } = await logisticsApi.startTask({ template_id: templateId, bot_id: botId })
      this.runs.push(data)
      return data
    },
    async stopTask(id: string) {
      await logisticsApi.stopTask(id)
      this.updateRunFromSocket({ run_id: id, status: 'cancelled' })
    },
    async pauseTask(id: string) {
      await logisticsApi.pauseTask(id)
      this.updateRunFromSocket({ run_id: id, status: 'paused' })
    },
    async resumeTask(id: string) {
      await logisticsApi.resumeTask(id)
      this.updateRunFromSocket({ run_id: id, status: 'running' })
    },
    updateRunFromSocket(payload: Partial<TaskRun> & { run_id: string }) {
      const idx = this.runs.findIndex(r => r.run_id === payload.run_id)
      if (idx >= 0) Object.assign(this.runs[idx], payload)
    },
  },
})
