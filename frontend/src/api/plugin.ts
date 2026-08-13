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
  /** 某个 bot 的插件状态（含全局 enabled + 该 bot 生效 bot_enabled，2026-08-13） */
  getBotPluginStatus(botId: string) {
    return client.get('/plugins/status', { params: { bot_id: botId } })
  },
  /** 为某个 bot 启用插件（?bot_id= 时只对该 bot 生效） */
  enablePluginForBot(name: string, botId: string) {
    return client.post(`/plugins/${name}/enable`, null, { params: { bot_id: botId } })
  },
  /** 为某个 bot 禁用插件（?bot_id= 时只对该 bot 生效） */
  disablePluginForBot(name: string, botId: string) {
    return client.post(`/plugins/${name}/disable`, null, { params: { bot_id: botId } })
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
