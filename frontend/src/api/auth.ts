import client from './client'

export const authApi = {
  login(game_id: string, password: string) {
    return client.post('/auth/login', { game_id, password })
  },
  register(game_id: string, password: string, display_name?: string) {
    return client.post('/auth/register', { game_id, password, display_name })
  },
  getMe() {
    return client.get('/auth/me')
  },
  changePassword(old_password: string, new_password: string) {
    return client.post('/auth/change-password', { old_password, new_password })
  },
}
