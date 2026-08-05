import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import router from '@/router'

/** 角色 → 权限等级映射（等级越高权限越大） */
const ROLE_RANK: Record<string, number> = {
  site_admin: 3,
  org_admin: 2,
  org_member: 1,
  user: 1,
  guest: 1,
}

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
    isSiteAdmin: (state) => state.user?.role === 'site_admin',
    isOrgAdmin: (state) => state.user?.role === 'org_admin',
    /**
     * 权限等级：3=站点管理员 2=组织管理员 1=组织成员/普通用户/访客
     * 用于侧边栏与路由守卫的权限过滤。
     */
    roleRank: (state) => ROLE_RANK[state.user?.role || 'guest'] ?? 1,
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
