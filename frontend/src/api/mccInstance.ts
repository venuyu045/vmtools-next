import client from './client'

export interface MccInstanceCreatePayload {
  slug: string
  display_name?: string
  bot_id?: string | null
  account_profile_id?: string | null
  binary_mode?: 'symlink' | 'copy' | 'external'
  mc_username?: string
  mc_server_host?: string
  mc_server_port?: number
  mc_version?: string
}

export interface MccInstance {
  instance_id: string
  slug: string
  display_name: string
  bot_id: string | null
  account_profile_id: string | null
  instance_dir: string
  binary_mode: string
  mcc_binary_path: string
  status: string
  desired_state: string
  pid: number | null
  exit_code: number | null
  mcp_host: string
  mcp_port: number
  mcp_auth_token_env: string
  mc_username: string
  mc_server_host: string
  mc_server_port: number
  mc_version: string
  organization_id: string | null
  created_by: string | null
  last_started_at: string | null
  last_stopped_at: string | null
  last_heartbeat_at: string | null
  created_at: string
  updated_at: string
}

export interface MccTerminalLine {
  seq: number
  stream: string
  content: string
  created_at: string
}

export interface MccFileEntry {
  name: string
  path: string
  type: 'directory' | 'file'
  size: number
  updated_at: number
  editable: boolean
  downloadable: boolean
  language: string
}

export interface MccFileTreeNode {
  name: string
  path: string
  type: 'directory' | 'file'
  children: MccFileTreeNode[]
}

export interface MccFileBreadcrumb {
  name: string
  path: string
}

export interface MccFileContent {
  path: string
  content: string
  encoding: string
  size: number
  language: string
  masked: boolean
  updated_at: number
}

export interface MccFileSaveResponse {
  path: string
  size?: number | null
  snapshot_id?: string | null
  diff?: string | null
  masked_secrets_preserved?: boolean
}

export interface MccFileDownloadResponse {
  path: string
  name: string
  size: number
  content_base64: string
  language: string
  download_name: string
}

export type MccAuthType = 'offline' | 'microsoft' | 'mojang' | 'yggdrasil' | 'custom'

export interface MccAccountConfig {
  auth_type: MccAuthType
  username: string
  password_set: boolean
  password?: string | null
  auth_server_url: string
  auth_api_path: string
  authlib_injector_path: string
  mc_server_host: string
  mc_server_port: number
  mc_version: string
  mcp_port: number
  mcp_auth_token_env: string
}

export interface MccAccountProfile {
  profile_id: string
  name: string
  auth_type: MccAuthType
  username: string
  password_set: boolean
  password?: string | null
  auth_server_url: string | null
  auth_api_path: string | null
  authlib_injector_path: string | null
  mc_server_host: string
  mc_server_port: number
  mc_version: string
  last_login_name: string | null
  organization_id: string | null
  created_at: string
  updated_at: string
}

export interface MccAccountProfilePayload {
  name: string
  auth_type: MccAuthType
  username: string
  password?: string | null
  auth_server_url?: string
  auth_api_path?: string
  authlib_injector_path?: string
  mc_server_host?: string
  mc_server_port?: number
  mc_version?: string
}

export const mccInstanceApi = {
  listProfiles() {
    return client.get<{ items: MccAccountProfile[]; total: number }>('/mcc/instances/account-profiles')
  },
  createProfile(data: MccAccountProfilePayload) {
    return client.post<MccAccountProfile>('/mcc/instances/account-profiles', data)
  },
  updateProfile(profileId: string, data: Partial<MccAccountProfilePayload> & { clear_password?: boolean }) {
    return client.patch<MccAccountProfile>(`/mcc/instances/account-profiles/${profileId}`, data)
  },
  deleteProfile(profileId: string) {
    return client.delete(`/mcc/instances/account-profiles/${profileId}`)
  },
  applyProfile(instanceId: string, profileId: string) {
    return client.post<{ config: MccAccountConfig; snapshot_id: string; diff: string; restart_required: boolean }>(`/mcc/instances/${instanceId}/account-config/apply-profile`, { profile_id: profileId })
  },
  list(status?: string) {
    return client.get<{ items: MccInstance[]; total: number }>('/mcc/instances', { params: { status } })
  },
  create(data: MccInstanceCreatePayload) {
    return client.post<MccInstance>('/mcc/instances', data)
  },
  get(instanceId: string) {
    return client.get<MccInstance>(`/mcc/instances/${instanceId}`)
  },
  update(instanceId: string, data: Partial<MccInstanceCreatePayload>) {
    return client.patch<MccInstance>(`/mcc/instances/${instanceId}`, data)
  },
  delete(instanceId: string) {
    return client.delete(`/mcc/instances/${instanceId}`)
  },
  start(instanceId: string, env: Record<string, string> = {}) {
    return client.post(`/mcc/instances/${instanceId}/start`, { env })
  },
  stop(instanceId: string, force = false, timeout_seconds = 10) {
    return client.post(`/mcc/instances/${instanceId}/stop`, { force, timeout_seconds })
  },
  restart(instanceId: string) {
    return client.post(`/mcc/instances/${instanceId}/restart`)
  },
  history(instanceId: string, tail = 200) {
    return client.get<{ items: MccTerminalLine[]; last_seq: number }>(`/mcc/instances/${instanceId}/terminal/history`, { params: { tail } })
  },
  input(instanceId: string, input: string, append_newline = true) {
    return client.post(`/mcc/instances/${instanceId}/terminal/input`, { input, append_newline })
  },
  listFiles(instanceId: string, path = '') {
    return client.get<{ path: string; breadcrumbs: MccFileBreadcrumb[]; items: MccFileEntry[] }>(`/mcc/instances/${instanceId}/files`, { params: { path } })
  },
  listFileTree(instanceId: string, path = '') {
    return client.get<{ items: MccFileTreeNode[] }>(`/mcc/instances/${instanceId}/files/tree`, { params: { path } })
  },
  downloadFile(instanceId: string, path: string) {
    return client.get<MccFileDownloadResponse>(`/mcc/instances/${instanceId}/files/download`, { params: { path } })
  },
  readFile(instanceId: string, path: string) {
    return client.get<MccFileContent>(`/mcc/instances/${instanceId}/files/content`, { params: { path } })
  },
  saveFile(instanceId: string, path: string, content: string, encoding = 'utf-8') {
    return client.put<MccFileSaveResponse>(`/mcc/instances/${instanceId}/files/content`, { path, content, encoding })
  },
  createFile(instanceId: string, path: string, content = '', overwrite = false) {
    return client.post<MccFileSaveResponse>(`/mcc/instances/${instanceId}/files`, { path, content, overwrite })
  },
  createDirectory(instanceId: string, path: string, overwrite = false) {
    return client.post<{ path: string; type: string }>(`/mcc/instances/${instanceId}/directories`, { path, overwrite })
  },
  uploadFile(instanceId: string, path: string, contentBase64: string, overwrite = false) {
    return client.post<MccFileSaveResponse>(`/mcc/instances/${instanceId}/files/upload`, { path, content: contentBase64, overwrite })
  },
  deleteFile(instanceId: string, path: string) {
    return client.delete(`/mcc/instances/${instanceId}/files`, { params: { path } })
  },
  renameFile(instanceId: string, source_path: string, target_path: string, overwrite = false) {
    return client.post(`/mcc/instances/${instanceId}/files/rename`, { source_path, target_path, overwrite })
  },
  getAccountConfig(instanceId: string) {
    return client.get<MccAccountConfig>(`/mcc/instances/${instanceId}/account-config`)
  },
  saveAccountConfig(instanceId: string, config: MccAccountConfig) {
    return client.put<{ config: MccAccountConfig; snapshot_id: string; diff: string; restart_required: boolean }>(`/mcc/instances/${instanceId}/account-config`, config)
  },
}
