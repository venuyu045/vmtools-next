import client from './client'

export const botApi = {
  list() {
    return client.get('/mcc-bots')
  },
  get(botId: string) {
    return client.get(`/mcc-bots/${botId}`)
  },
  create(data: {
    bot_id: string
    name?: string
    ws_host?: string
    ws_port?: number
    ws_password?: string
    mc_username?: string
    mc_account_type?: string
    mc_server_host?: string
    mc_server_port?: number
    organization_id?: string
  }) {
    return client.post('/mcc-bots', data)
  },
  delete(botId: string) {
    return client.delete(`/mcc-bots/${botId}`)
  },
  connect(botId: string, data: { host?: string; port?: number; auth_token?: string }) {
    return client.post(`/mcc-bots/${botId}/connect`, data)
  },
  disconnect(botId: string) {
    return client.post(`/mcc-bots/${botId}/disconnect`)
  },
}
