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

/** `/auth/me` 的并发去重句柄（守卫在多次导航中可能同时触发） */
let userInflight: Promise<void> | null = null

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
    async register(game_id: string, password: string, display_name?: string, qq_ticket?: string) {
      const { data } = await authApi.register(game_id, password, display_name, qq_ticket)
      // 注册成功直接返回登录 token（QQ 认证通过即 approved）
      if (data?.token) {
        this.token = data.token
        localStorage.setItem('token', data.token)
        await this.getMe()
      }
      return data
    },
    /** 发起 QQ 互联授权（整页跳转 QQ） */
    async startQqAuth() {
      const { data } = await authApi.qqLoginUrl()
      if (data?.auth_url) {
        window.location.href = data.auth_url
      }
    },
    /** 凭 QQ ticket 登录：已注册→登录成功返回 true；未注册→false */
    async qqTicketLogin(qq_ticket: string) {
      const { data } = await authApi.qqTicketLogin(qq_ticket)
      if (data && data.need_register === false && data.token) {
        this.token = data.token
        localStorage.setItem('token', data.token)
        await this.getMe()
        return { loggedIn: true, nickname: data.nickname || '' }
      }
      return { loggedIn: false, nickname: data?.nickname || '', avatar: data?.avatar || '' }
    },
    /** QQ 绑定已有账号：绑定成功即登录（token 落地） */
    async qqBind(game_id: string, password: string, qq_ticket: string) {
      const { data } = await authApi.qqBind(game_id, password, qq_ticket)
      if (data?.token) {
        this.token = data.token
        localStorage.setItem('token', data.token)
        await this.getMe()
      }
      return data
    },
    async getMe() {
      try {
        const { data } = await authApi.getMe()
        this.user = data
      } catch {
        this.logout()
      }
    },
    /**
     * 确保 `user` 已加载（去重；失败不清 token、不跳转）。
     *
     * 为什么需要：`state.user` 只在内存里，刷新页面后是 null，而路由守卫原来只在
     * `user` 存在时才做角色校验 —— 于是「刷新 / 直接输 URL 进管理页」时守卫放行，
     * 页面先渲染、再被接口 403（用户看到一闪而过的报错，admin 还能短暂看到管理端骨架）。
     * 守卫里 await 本方法后即可拿到真实角色再决定放行/回落。
     */
    async ensureUser(): Promise<UserInfo | null> {
      if (this.user) return this.user
      if (!userInflight) {
        userInflight = authApi
          .getMe()
          .then(({ data }) => {
            this.user = data
          })
          .catch(() => {
            // 保持 null：由调用方（守卫）或接口 401 拦截器统一处理
          })
          .finally(() => {
            userInflight = null
          })
      }
      await userInflight
      return this.user
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('token')
      router.push('/login')
    },
  },
})
