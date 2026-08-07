import client from './client'

export const warehouseApi = {
  list() {
    return client.get('/warehouses')
  },
  get(id: string) {
    return client.get(`/warehouses/${id}`)
  },
  create(data: { name: string; teleport_cmd?: string; organization_id?: string }) {
    return client.post('/warehouses', data)
  },
    delete(id: string) {
    return client.delete(`/warehouses/${id}`)
    },
    update(id: string, data: any) {
    return client.put(`/warehouses/${id}`, data)
    },
    getMaterials(id: string, page = 1, pageSize = 5000) {
  return client.get(`/warehouses/${id}/materials`, { params: { page, page_size: pageSize } })
},
    searchMaterials(q: string, page = 1) {
    return client.get('/materials/search', { params: { q, page } })
  },
  // 仓库状态页：跨仓库物品搜索（中文名/英文名/id），返回物品→仓库→箱子明细
  searchItemDetails(q: string, limit = 50) {
    return client.get('/warehouses/items/search', { params: { q, limit } })
  },
    getAisles(id: string) {
    return client.get(`/warehouses/${id}/aisles`)
    },
    updateAisles(id: string, data: any) {
    return client.put(`/warehouses/${id}/aisles`, data)
    },
    getZones(id: string) {
    return client.get(`/warehouses/${id}/zones`)
    },
    createZone(id: string, data: any) {
    return client.post(`/warehouses/${id}/zones`, data)
    },
    updateZone(id: string, zoneId: string, data: any) {
    return client.put(`/warehouses/${id}/zones/${zoneId}`, data)
    },
    deleteZone(id: string, zoneId: string) {
    return client.delete(`/warehouses/${id}/zones/${zoneId}`)
    },
    getScanStatus(id: string) {
    return client.get(`/warehouses/${id}/scan-status`)
    },
    getScanQueue() {
    return client.get(`/warehouses/scan-queue`)
    },
    }
