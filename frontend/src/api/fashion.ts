import client from './client'

/** 时装系统 API（mod + 网站共用后端，字段 camelCase 与后端一致） */

export type FashionCategory = 'cape' | 'wings' | 'hat' | 'back' | 'pet' | 'aura' | 'other'

export const FASHION_SLOTS: { value: FashionCategory; label: string }[] = [
  { value: 'cape', label: '披风' },
  { value: 'wings', label: '翅膀' },
  { value: 'hat', label: '头饰' },
  { value: 'back', label: '背饰' },
  { value: 'pet', label: '宠物' },
  { value: 'aura', label: '光环' },
  { value: 'other', label: '其它' },
]

export const CATEGORY_LABELS: Record<string, string> = {
  cape: '披风',
  wings: '翅膀',
  hat: '头饰',
  back: '背饰',
  pet: '宠物',
  aura: '光环',
  other: '其它',
}

export interface FashionIdentity {
  id: string
  mcUuid: string
  mcName: string
  authType: 'mojang' | 'yggdrasil' | string
  authServer: string
  verified: boolean
  verifiedAt: string | null
  userId: string | null
  createdAt: string | null
  lastSeenAt: string | null
}

export interface CatalogItem {
  cosmeticId: string
  name: string
  category: string
  assetKey: string
  sha256: string
  bytes: number
  packId: string
  sortOrder: number
}

export interface LoadoutItem {
  slot: string
  cosmeticId: string
  scale: number
  assetKey: string
  sha256: string
  bytes: number
  name: string
  category: string
  missing: boolean
  /** 包级下发（mod 契约 §3）：这件时装属于哪个包 / 包的当前版本；无包时为空串 */
  packId: string
  packVersion: string
}

export interface DeviceApproveResult {
  ok: boolean
  identityId: string
  mcUuid: string
  mcName: string
}

/** 保存穿戴时被后端跳过的条目（未知 / 已下架的时装，不会再让整条请求失败） */
export interface LoadoutWarning {
  slot: string
  cosmeticId: string
  code: string
}

export interface LoadoutPutResult {
  ok: boolean
  updatedAt: string
  warnings?: LoadoutWarning[]
}

export const fashionApi = {
  /** 时装目录（登录用户可读） */
  catalog(params?: { category?: string; pack_id?: string }) {
    return client.get<{ items: CatalogItem[] }>('/fashion/catalog', { params })
  },
  /** 当前网页账号绑定的 MC 身份 */
  myIdentities() {
    return client.get<{ items: FashionIdentity[] }>('/fashion/identities/me')
  },
  /** 解绑自己的 MC 身份 */
  unbind(identityId: string) {
    return client.delete(`/fashion/identities/${encodeURIComponent(identityId)}`)
  },
  /** 输入 6 位绑定码（mod 端生成）完成绑定 */
  approveDevice(userCode: string) {
    return client.post<DeviceApproveResult>('/fashion/device/approve', { userCode })
  },
  /** 读取穿戴配置；identityId 用于一个账号绑了多个 MC 身份时指定 */
  getLoadout(identityId?: string) {
    return client.get<{ items: LoadoutItem[] }>('/fashion/loadout/me', {
      params: identityId ? { identityId } : {},
    })
  },
  /** 全量覆盖穿戴配置（后端会跳过未知/已下架的条目，并在 warnings 里列出） */
  putLoadout(items: { slot: string; cosmeticId: string; scale: number }[], identityId?: string) {
    return client.put<LoadoutPutResult>(
      '/fashion/loadout',
      { items },
      { params: identityId ? { identityId } : {} }
    )
  },
  /** 资产 URL（公开可读、长缓存；注意带 /api 前缀，img 标签直接可用） */
  assetUrl(assetKey: string) {
    const safe = assetKey
      .split('/')
      // 丢弃空段与 "."/".."：避免拼出会被浏览器归一化的穿越路径
      .filter((seg) => seg && seg !== '.' && seg !== '..')
      .map((seg) => encodeURIComponent(seg))
      .join('/')
    return `/api/fashion/assets/${safe}`
  },
}

/** 从 axios 错误里抽出后端结构化错误码（detail 可能是对象） */
export function fashionErrorCode(error: unknown): string {
  const err = error as { response?: { data?: { detail?: unknown } } }
  const detail = err?.response?.data?.detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    return String((detail as { code: unknown }).code)
  }
  return ''
}

/** 后端错误的中文提示 */
export function fashionErrorMessage(error: unknown, fallback = '操作失败'): string {
  const err = error as { response?: { data?: { detail?: unknown } } }
  const detail = err?.response?.data?.detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message: unknown }).message
    if (typeof message === 'string' && message.trim()) return message.trim()
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  return fallback
}
