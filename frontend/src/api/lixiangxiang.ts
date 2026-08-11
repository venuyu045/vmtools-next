import client from './client'

export interface LxInfo {
  intro: string
  history: string
  slogan: string
  settings: Record<string, string>
}

export interface LxMember {
  id: string
  game_id: string
  nickname: string
  title: string
  joined_at: string
  specialty: string
  avatar_path: string
  bio: string
  sort_order: number
}

export interface LxBase {
  id: string
  name: string
  description: string
  image_path: string
  coordinates: string
  sort_order: number
}

export interface LxCategory {
  id: string
  name: string
  sort_order: number
  image_count?: number
}

export interface LxImage {
  id: string
  category_id: string | null
  image_path: string
  title: string
  description: string
  uploaded_at: string | null
}

/** 公开读接口（访客免登录） */
export const lxPublicApi = {
  info() {
    return client.get<LxInfo>('/lixiangxiang/info')
  },
  members() {
    return client.get<LxMember[]>('/lixiangxiang/members')
  },
  bases() {
    return client.get<LxBase[]>('/lixiangxiang/bases')
  },
  categories() {
    return client.get<LxCategory[]>('/lixiangxiang/categories')
  },
  images(categoryId?: string) {
    return client.get<LxImage[]>('/lixiangxiang/images', {
      params: categoryId ? { category_id: categoryId } : {},
    })
  },
}

/** 管理接口（仅 admin / site_admin，非管理员 403） */
export const lxAdminApi = {
  updateInfo(data: Partial<Pick<LxInfo, 'intro' | 'history' | 'slogan'>> & { settings?: string }) {
    return client.put<LxInfo>('/lixiangxiang/info', data)
  },
  createMember(data: Omit<LxMember, 'id'>) {
    return client.post<LxMember>('/lixiangxiang/members', data)
  },
  updateMember(id: string, data: Partial<Omit<LxMember, 'id'>>) {
    return client.put<LxMember>(`/lixiangxiang/members/${id}`, data)
  },
  deleteMember(id: string) {
    return client.delete(`/lixiangxiang/members/${id}`)
  },
  createBase(data: Omit<LxBase, 'id'>) {
    return client.post<LxBase>('/lixiangxiang/bases', data)
  },
  updateBase(id: string, data: Partial<Omit<LxBase, 'id'>>) {
    return client.put<LxBase>(`/lixiangxiang/bases/${id}`, data)
  },
  deleteBase(id: string) {
    return client.delete(`/lixiangxiang/bases/${id}`)
  },
  createCategory(data: { name: string; sort_order: number }) {
    return client.post<LxCategory>('/lixiangxiang/categories', data)
  },
  updateCategory(id: string, data: Partial<{ name: string; sort_order: number }>) {
    return client.put<LxCategory>(`/lixiangxiang/categories/${id}`, data)
  },
  deleteCategory(id: string) {
    return client.delete(`/lixiangxiang/categories/${id}`)
  },
  createImage(data: { image_path: string; category_id?: string | null; title?: string; description?: string }) {
    return client.post<LxImage>('/lixiangxiang/images', data)
  },
  updateImage(id: string, data: Partial<{ image_path: string; category_id: string | null; title: string; description: string }>) {
    return client.put<LxImage>(`/lixiangxiang/images/${id}`, data)
  },
  deleteImage(id: string) {
    return client.delete(`/lixiangxiang/images/${id}`)
  },
  /** 通用图片上传（multipart），返回可访问的 URL */
  async upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    const { data } = await client.post<{ url: string }>('/lixiangxiang/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 30000,
    })
    return data.url
  },
}
