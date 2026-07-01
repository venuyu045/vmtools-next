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
}
