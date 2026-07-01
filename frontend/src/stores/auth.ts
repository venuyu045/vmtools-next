import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import router from '@/router'

interface UserInfo {
  id: string
  game_id: string
  display_name: string
  role: string
  status: string
  organization_id: string | null
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || null as string | null,
    user: null as UserInfo | null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    isAdmin: (state) => state.user?.role === 'site_admin' || state.user?.role === 'org_admin',
  },
  actions: {
    async login(game_id: string, password: string) {
      const { data } = await authApi.login(game_id, password)
      this.token = data.token
      localStorage.setItem('token', data.token)
      await this.getMe()
    },
    async register(game_id: string, password: string, display_name?: string) {
      await authApi.register(game_id, password, display_name)
    },
    async getMe() {
      try {
        const { data } = await authApi.getMe()
        this.user = data
      } catch {
        this.logout()
      }
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('token')
      router.push('/login')
    },
  },
})
