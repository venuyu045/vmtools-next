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
    loading: false,
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
    async createWarehouse(name: string, organizationId?: string) {
      const { data } = await warehouseApi.create({ name, organization_id: organizationId })
      this.warehouses.push(data)
      return data
    },
    async deleteWarehouse(id: string) {
      await warehouseApi.delete(id)
      this.warehouses = this.warehouses.filter(w => w.warehouse_id !== id)
    },
    async fetchMaterials(id: string) {
      const { data } = await warehouseApi.getMaterials(id)
      this.materials = data
      return data
    },
  },
})
