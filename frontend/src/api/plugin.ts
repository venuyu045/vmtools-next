import client from './client'

export const pluginApi = {
  listPlugins() {
    return client.get('/plugins')
  },
  enablePlugin(name: string) {
    return client.post(`/plugins/${name}/enable`)
  },
  disablePlugin(name: string) {
    return client.post(`/plugins/${name}/disable`)
  },
  reloadPlugin(name: string) {
    return client.post(`/plugins/${name}/reload`)
  },
  getPluginConfig(name: string) {
    return client.get(`/plugins/${name}/config`)
  },
  savePluginConfig(name: string, config: Record<string, any>) {
    return client.put(`/plugins/${name}/config`, { config })
  },
}
