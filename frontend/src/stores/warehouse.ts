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
    scanStatus: 'idle' as string, // idle | scanning | paused | finished | cancelled | failed
    scanProgress: 0,
    scanScanned: 0,
    scanTotal: 0,
    scanCurrentPos: null as { x: number; y: number; z: number } | null,
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
    async createWarehouse(name: string) {
      const { data } = await warehouseApi.create({ name })
      this.warehouses.push(data)
      return data
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
      return data
    },
    setScanProgress(payload: any) {
      this.scanProgress = payload?.progress ?? this.scanProgress
      this.scanScanned = payload?.scanned ?? this.scanScanned
      this.scanTotal = payload?.total ?? this.scanTotal
      if (payload?.current_pos) this.scanCurrentPos = payload.current_pos
    },
  },
})
