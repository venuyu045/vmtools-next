import client from './client'

export interface MemberUser {
  id: string
  game_id: string
  display_name: string
  role: string
  status: string
  organization_id: string | null
  created_at: string | null
  approved_at: string | null
  last_seen_at: string | null
}

export const membersApi = {
  /** 列出所有用户（仅 site_admin），可按状态过滤 */
  list(status?: string) {
    return client.get<MemberUser[]>('/admin/users', {
      params: status ? { status } : {},
    })
  },
  /** 更新用户状态 / 角色（仅 site_admin） */
  update(id: string, data: { status?: string; role?: string }) {
    return client.patch<MemberUser>(`/admin/users/${id}`, data)
  },
  /** 删除成员（仅 site_admin） */
  remove(id: string) {
    return client.delete(`/admin/users/${id}`)
  },
}
