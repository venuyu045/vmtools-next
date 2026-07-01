import { defineStore } from 'pinia'
import { mccInstanceApi, type MccAccountConfig, type MccAccountProfile, type MccAccountProfilePayload, type MccFileBreadcrumb, type MccFileContent, type MccFileEntry, type MccFileTreeNode, type MccInstance, type MccInstanceCreatePayload, type MccTerminalLine } from '@/api/mccInstance'

export const useMccInstanceStore = defineStore('mccInstance', {
  state: () => ({
    instances: [] as MccInstance[],
    accountProfiles: [] as MccAccountProfile[],
    terminalLines: {} as Record<string, MccTerminalLine[]>,
    fileLists: {} as Record<string, MccFileEntry[]>,
    fileBreadcrumbs: {} as Record<string, MccFileBreadcrumb[]>,
    fileTrees: {} as Record<string, MccFileTreeNode[]>,
    fileContents: {} as Record<string, MccFileContent>,
    accountConfigs: {} as Record<string, MccAccountConfig>,
    loading: false,
    actionLoading: {} as Record<string, boolean>,
  }),
  getters: {
    runningCount: (state) => state.instances.filter(item => item.status === 'running').length,
    totalCount: (state) => state.instances.length,
  },
  actions: {
    async fetchProfiles() {
      const { data } = await mccInstanceApi.listProfiles()
      this.accountProfiles = data.items
      return data.items
    },
    async createProfile(payload: MccAccountProfilePayload) {
      const { data } = await mccInstanceApi.createProfile(payload)
      this.accountProfiles.unshift(data)
      return data
    },
    async applyProfile(instanceId: string, profileId: string) {
      const { data } = await mccInstanceApi.applyProfile(instanceId, profileId)
      this.accountConfigs[instanceId] = data.config
      this.updateInstanceStatus(instanceId, {
        account_profile_id: profileId,
        mc_username: data.config.username,
        mc_server_host: data.config.mc_server_host,
        mc_server_port: data.config.mc_server_port,
        mc_version: data.config.mc_version,
      })
      return data
    },
    async fetchInstances() {
      this.loading = true
      try {
        const { data } = await mccInstanceApi.list()
        this.instances = data.items
      } finally {
        this.loading = false
      }
    },
    async createInstance(payload: MccInstanceCreatePayload) {
      const { data } = await mccInstanceApi.create(payload)
      this.instances.unshift(data)
      return data
    },
    async startInstance(instanceId: string) {
      this.actionLoading[instanceId] = true
      try {
        const { data } = await mccInstanceApi.start(instanceId)
        this.updateInstanceStatus(instanceId, data)
        return data
      } finally {
        this.actionLoading[instanceId] = false
      }
    },
    async stopInstance(instanceId: string, force = false) {
      this.actionLoading[instanceId] = true
      try {
        const { data } = await mccInstanceApi.stop(instanceId, force)
        this.updateInstanceStatus(instanceId, data)
        return data
      } finally {
        this.actionLoading[instanceId] = false
      }
    },
    async deleteInstance(instanceId: string) {
      await mccInstanceApi.delete(instanceId)
      this.instances = this.instances.filter(item => item.instance_id !== instanceId)
    },
    async fetchTerminalHistory(instanceId: string) {
      const { data } = await mccInstanceApi.history(instanceId)
      this.terminalLines[instanceId] = data.items
    },
    async sendInput(instanceId: string, input: string) {
      await mccInstanceApi.input(instanceId, input)
    },
    async fetchFiles(instanceId: string, path = '') {
      const { data } = await mccInstanceApi.listFiles(instanceId, path)
      this.fileLists[instanceId] = data.items
      return data.items
    },
    async readFile(instanceId: string, path: string) {
      const { data } = await mccInstanceApi.readFile(instanceId, path)
      this.fileContents[`${instanceId}:${path}`] = data
      return data
    },
    async saveFile(instanceId: string, path: string, content: string, encoding = 'utf-8') {
      const { data } = await mccInstanceApi.saveFile(instanceId, path, content, encoding)
      await this.readFile(instanceId, path)
      return data
    },
    async createFile(instanceId: string, path: string, content = '') {
      const { data } = await mccInstanceApi.createFile(instanceId, path, content)
      await this.fetchFiles(instanceId)
      return data
    },
    async deleteFile(instanceId: string, path: string) {
      await mccInstanceApi.deleteFile(instanceId, path)
      await this.fetchFiles(instanceId)
    },
    async renameFile(instanceId: string, sourcePath: string, targetPath: string) {
      await mccInstanceApi.renameFile(instanceId, sourcePath, targetPath)
      await this.fetchFiles(instanceId)
    },
    async fetchFileTree(instanceId: string) {
      const { data } = await mccInstanceApi.listFileTree(instanceId)
      this.fileTrees[instanceId] = data.items
      return data.items
    },
    async downloadFile(instanceId: string, path: string) {
      const { data } = await mccInstanceApi.downloadFile(instanceId, path)
      const binary = atob(data.content_base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
      return new Blob([bytes], { type: 'application/octet-stream' })
    },
    async uploadFile(instanceId: string, path: string, contentBase64: string, overwrite = false) {
      const { data } = await mccInstanceApi.uploadFile(instanceId, path, contentBase64, overwrite)
      return data
    },
    async createDirectory(instanceId: string, path: string, overwrite = false) {
      const { data } = await mccInstanceApi.createDirectory(instanceId, path, overwrite)
      return data
    },
    async fetchAccountConfig(instanceId: string) {
      const { data } = await mccInstanceApi.getAccountConfig(instanceId)
      this.accountConfigs[instanceId] = data
      return data
    },
    async saveAccountConfig(instanceId: string, config: MccAccountConfig) {
      const { data } = await mccInstanceApi.saveAccountConfig(instanceId, config)
      this.accountConfigs[instanceId] = data.config
      this.updateInstanceStatus(instanceId, {
        mc_username: data.config.username,
        mc_server_host: data.config.mc_server_host,
        mc_server_port: data.config.mc_server_port,
        mc_version: data.config.mc_version,
      })
      return data
    },
    updateInstanceStatus(instanceId: string, payload: Partial<MccInstance> & { status?: string; pid?: number | null }) {
      const idx = this.instances.findIndex(item => item.instance_id === instanceId)
      if (idx >= 0) {
        Object.assign(this.instances[idx], payload)
      }
    },
    pushTerminalLine(payload: MccTerminalLine & { instance_id: string }) {
      const lines = this.terminalLines[payload.instance_id] || []
      lines.push({
        seq: payload.seq,
        stream: payload.stream,
        content: payload.content,
        created_at: payload.created_at,
      })
      this.terminalLines[payload.instance_id] = lines.slice(-500)
    },
  },
})
