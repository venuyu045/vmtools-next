import client from './client'

export const configApi = {
  getConfig() {
    return client.get('/config')
  },
  reloadConfig() {
    return client.post('/config/reload')
  },
}
