import client from './client'

export const warehouseApi = {
  list() {
    return client.get('/warehouses')
  },
  get(id: string) {
    return client.get(`/warehouses/${id}`)
  },
  create(data: { name: string; organization_id?: string }) {
    return client.post('/warehouses', data)
  },
  delete(id: string) {
    return client.delete(`/warehouses/${id}`)
  },
  getMaterials(id: string, page = 1, pageSize = 500) {
    return client.get(`/warehouses/${id}/materials`, { params: { page, page_size: pageSize } })
  },
  searchMaterials(q: string, page = 1) {
    return client.get('/materials/search', { params: { q, page } })
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
}
