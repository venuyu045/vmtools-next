import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'
import router from '@/router'

/** 角色 → 权限等级映射（等级越高权限越大；权限组重构后：user / admin / site_admin / guest） */
const ROLE_RANK: Record<string, number> = {
  site_admin: 3,
  admin: 2,
  user: 1,
  guest: 1,
}

/** 角色 → 中文显示名（个人弹窗「当前权限组」等场景使用） */
export const ROLE_LABELS: Record<string, string> = {
  site_admin: '站点管理员',
  admin: '管理员',
  user: '用户',
  guest: '访客',
}

export function roleLabel(role: string | undefined | null): string {
  if (!role) return '未登录'
  return ROLE_LABELS[role] || role
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
    isAdmin: (state) => state.user?.role === 'site_admin' || state.user?.role === 'admin',
    isSiteAdmin: (state) => state.user?.role === 'site_admin',
    /** 兼容旧引用：isOrgAdmin 已更名为 isAdmin（管理员 = admin 或 site_admin） */
    isOrgAdmin: (state) => state.user?.role === 'admin',
    /**
     * 权限等级：3=站点管理员 2=管理员 1=用户/访客
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
