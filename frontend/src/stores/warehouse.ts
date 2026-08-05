import { defineStore } from 'pinia'
import { warehouseApi } from '@/api/warehouse'

export interface Warehouse {
  warehouse_id: string
  name: string
  last_scan_time: string | null
  container_count: number
  total_items: number
  material_count: number
  group_id: string | null
  organization_id: string | null
  teleport_cmd: string | null
  logistics_teleport_cmd: string | null
}

export interface WarehouseZone {
  zone_id: string
  warehouse_fk: string
  name: string
  range_min_x: number
  range_min_y: number
  range_min_z: number
  range_max_x: number
  range_max_y: number
  range_max_z: number
  aisle_lines: any[]
  created_at: string | null
}

export interface MaterialItem {
  item_id: string
  display_name: string
  count: number
}

export const useWarehouseStore = defineStore('warehouse', {
  state: () => ({
    warehouses: [] as Warehouse[],
    currentWarehouse: null as Warehouse | null,
    materials: [] as MaterialItem[],
    materialTotal: 0,
    loading: false,
    // 扫描状态（Socket.IO 实时推送）
    scanStatus: 'idle' as string, // idle | queued | scanning | paused | finished | cancelled | failed
    scanProgress: 0,
    scanScanned: 0,
    scanTotal: 0,
    scanItems: 0,
    scanSpeed: 0,
    scanEta: null as number | null,
    scanCurrentPos: null as { x: number; y: number; z: number } | null,
    scanQueue: [] as any[], // 扫描队列（scan_queue_update）
  }),
  actions: {
    async fetchWarehouses() {
      this.loading = true
      try {
        const { data } = await warehouseApi.list()
        this.warehouses = data
      } finally {
        this.loading = false
      }
    },
    async fetchWarehouse(id: string) {
      const { data } = await warehouseApi.get(id)
      this.currentWarehouse = data
      return data
    },
    async createWarehouse(name: string, teleportCmd?: string) {
      const { data } = await warehouseApi.create({ name, teleport_cmd: teleportCmd || undefined })
      this.warehouses.push(data)
      return data
    },
    async updateWarehouse(id: string, data: any) {
      const res = await warehouseApi.update(id, data)
      this.currentWarehouse = res.data
      return res.data
    },
    async deleteWarehouse(id: string) {
      await warehouseApi.delete(id)
      this.warehouses = this.warehouses.filter(w => w.warehouse_id !== id)
    },
    async fetchMaterials(id: string) {
      const { data } = await warehouseApi.getMaterials(id)
      this.materials = data.items ?? []
      this.materialTotal = data.total ?? 0
      return data
    },
    async fetchScanStatus(id: string) {
      const { data } = await warehouseApi.getScanStatus(id)
      this.scanStatus = data.status || 'idle'
      this.scanProgress = data.progress || 0
      this.scanScanned = data.scanned_containers || 0
      this.scanTotal = data.total_containers || 0
      this.scanItems = data.items_scanned || 0
      return data
    },
    async fetchScanQueue() {
      try {
        const { data } = await warehouseApi.getScanQueue()
        this.scanQueue = data?.items ?? []
      } catch { /* ignore */ }
    },
    setScanProgress(payload: any) {
      this.scanProgress = payload?.progress ?? this.scanProgress
      this.scanScanned = payload?.scanned ?? this.scanScanned
      this.scanTotal = payload?.total ?? this.scanTotal
      this.scanItems = payload?.items_scanned ?? this.scanItems
      this.scanSpeed = payload?.speed ?? 0
      this.scanEta = payload?.eta_seconds ?? null
      if (payload?.current_pos) this.scanCurrentPos = payload.current_pos
    },
    setScanQueue(items: any[]) {
      this.scanQueue = items ?? []
    },
  },
})
