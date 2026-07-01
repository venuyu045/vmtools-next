<template>
  <div class="file-manager" :class="{ embedded }">
    <div class="file-toolbar">
      <span class="mono breadcrumbs">
        <template v-for="(crumb, idx) in crumbs" :key="crumb.path">
          <a class="crumb-link" href="#" @click.prevent="navigateTo(crumb.path)">{{ crumb.name }}</a>
          <span v-if="idx < crumbs.length - 1" class="crumb-sep"> / </span>
        </template>
      </span>
      <div class="toolbar-actions">
        <button class="pixel-btn outline small" @click="promptCreateFile">新建文件</button>
        <button class="pixel-btn outline small" @click="promptCreateDir">新建目录</button>
        <label class="pixel-btn outline small upload-btn">
          上传
          <input type="file" hidden @change="handleUpload" />
        </label>
        <button class="pixel-btn outline small" @click="refreshFiles">刷新</button>
      </div>
    </div>

    <div class="file-layout">
      <div class="file-tree-panel">
        <div class="tree-title mono">目录</div>
        <div class="file-tree">
          <div
            v-for="node in treeData"
            :key="node.path"
            :class="['tree-folder', { active: navigatingPath === node.path }]"
            @click="navigateTo(node.path)"
          >
            DIR {{ node.name }}
          </div>
        </div>
      </div>

      <div class="file-main">
        <div class="file-list" @contextmenu.prevent="onContextMenu($event, null)">
          <template v-if="fileList.length">
            <div
              v-for="file in fileList"
              :key="file.path"
              :class="['file-row', { active: selectedFilePath === file.path }]"
              @click="handleFileClick(file)"
              @contextmenu.stop.prevent="onContextMenu($event, file)"
            >
              <span>{{ file.type === 'directory' ? 'DIR' : file.language.toUpperCase().slice(0, 3) || 'TXT' }}</span>
              <strong>{{ file.name }}</strong>
              <div class="file-actions-inline">
                <em>{{ file.type === 'file' ? formatSize(file.size) : '' }}</em>
                <button v-if="file.downloadable" class="mini-btn" title="下载" @click.stop="downloadSingleFile(file.path)">DL</button>
              </div>
            </div>
          </template>
          <div v-else class="empty-list mono">-- 空目录 --</div>
        </div>

        <div class="file-editor" v-if="editingFile">
          <div class="editor-head mono">
            <span>{{ editingFile.path }} · {{ editingFile.language }} · {{ formatSize(editingFile.size) }}</span>
            <span v-if="editingFile.masked" class="secret-note">敏感字段已脱敏</span>
          </div>
          <el-input v-model="editorContent" type="textarea" :autosize="{ minRows: 14, maxRows: 24 }" resize="vertical" class="code-editor" />
          <div class="editor-actions">
            <button class="pixel-btn" @click="saveCurrentFile">保存</button>
            <button class="pixel-btn outline" @click="promptRenameFile">重命名</button>
            <button class="pixel-btn danger" @click="deleteCurrentFile">删除</button>
          </div>
          <pre v-if="lastDiff" class="diff-output">{{ lastDiff }}</pre>
        </div>

        <div v-else-if="!fileList.length" class="empty-editor mono">-- 选择一个文本文件查看/编辑 --</div>
        <div v-else class="empty-editor mono">-- 选择一个文件 --</div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="contextMenuVisible"
        class="context-menu"
        :style="{ top: contextMenuY + 'px', left: contextMenuX + 'px' }"
        @click.stop
        @mouseleave="contextMenuVisible = false"
      >
        <div v-if="contextFile" class="context-item" @click="contextMenuVisible = false; handleFileClick(contextFile)">编辑</div>
        <div v-if="contextFile?.downloadable" class="context-item" @click="contextMenuVisible = false; downloadSingleFile(contextFile!.path)">下载</div>
        <div v-if="contextFile" class="context-item" @click="contextMenuVisible = false; promptRenameFileRef(contextFile)">重命名</div>
        <div v-if="contextFile" class="context-item danger" @click="contextMenuVisible = false; deleteFileRef(contextFile)">删除</div>
        <div class="context-item" @click="contextMenuVisible = false; promptCreateFile()">新建文件</div>
        <div class="context-item" @click="contextMenuVisible = false; promptCreateDir()">新建目录</div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMccInstanceStore } from '@/stores/mccInstance'
import type { MccFileBreadcrumb, MccFileContent, MccFileEntry, MccFileTreeNode } from '@/api/mccInstance'

const props = withDefaults(defineProps<{
  instanceId: string
  slug?: string
  embedded?: boolean
}>(), {
  slug: '',
  embedded: false,
})

const store = useMccInstanceStore()
const currentPath = ref('')
const selectedFilePath = ref('')
const editingFile = ref<MccFileContent | null>(null)
const editorContent = ref('')
const lastDiff = ref('')
const treeData = ref<MccFileTreeNode[]>([])
const navigatingPath = ref('')
const contextMenuVisible = ref(false)
const contextMenuX = ref(0)
const contextMenuY = ref(0)
const contextFile = ref<MccFileEntry | null>(null)

const fileList = computed(() => store.fileLists[props.instanceId] || [])
const crumbs = computed<MccFileBreadcrumb[]>(() => store.fileBreadcrumbs[props.instanceId] || [])

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function refreshFiles() {
  await loadFiles(currentPath.value)
  await store.fetchFileTree(props.instanceId)
  treeData.value = store.fileTrees[props.instanceId] || []
}

async function loadFiles(path = '') {
  currentPath.value = path
  navigatingPath.value = path
  const resp = await store.fetchFiles(props.instanceId, path)
  if (resp) {
    store.fileBreadcrumbs[props.instanceId] = (resp as any).breadcrumbs || []
  }
}

async function navigateTo(path: string) {
  editingFile.value = null
  selectedFilePath.value = ''
  editorContent.value = ''
  lastDiff.value = ''
  await loadFiles(path || '')
}

async function handleFileClick(file: MccFileEntry) {
  if (file.type === 'directory') {
    await navigateTo(file.path)
    return
  }
  if (!file.editable) {
    if (file.downloadable) {
      await downloadSingleFile(file.path)
    } else {
      ElMessage.warning('该文件不可在线编辑或下载')
    }
    return
  }
  selectedFilePath.value = file.path
  const data = await store.readFile(props.instanceId, file.path)
  editingFile.value = data
  editorContent.value = data.content
  lastDiff.value = ''
}

async function saveCurrentFile() {
  if (!editingFile.value) return
  const result = await store.saveFile(props.instanceId, editingFile.value.path, editorContent.value, editingFile.value.encoding || 'utf-8')
  lastDiff.value = result.diff || ''
  ElMessage.success(result.masked_secrets_preserved ? '文件已保存，脱敏密钥已保留原值' : '文件已保存')
}

async function promptCreateFile() {
  const { value } = await ElMessageBox.prompt('输入相对路径，如 notes.txt', '新建文件', { inputPlaceholder: 'notes.txt' })
  if (!value) return
  await store.createFile(props.instanceId, value, '')
  await refreshFiles()
  ElMessage.success('文件已创建')
}

async function promptCreateDir() {
  const { value } = await ElMessageBox.prompt('输入目录相对路径，如 config', '新建目录', { inputPlaceholder: 'config' })
  if (!value) return
  await store.createDirectory(props.instanceId, value)
  await refreshFiles()
  ElMessage.success('目录已创建')
}

async function promptRenameFile() {
  if (!editingFile.value) return
  const { value } = await ElMessageBox.prompt('输入新相对路径', '重命名文件', { inputValue: editingFile.value.path })
  if (!value || value === editingFile.value.path) return
  await store.renameFile(props.instanceId, editingFile.value.path, value)
  editingFile.value = null
  selectedFilePath.value = ''
  editorContent.value = ''
  await refreshFiles()
  ElMessage.success('文件已重命名')
}

async function promptRenameFileRef(file: MccFileEntry) {
  const { value } = await ElMessageBox.prompt('输入新相对路径', '重命名文件', { inputValue: file.path })
  if (!value || value === file.path) return
  await store.renameFile(props.instanceId, file.path, value)
  await refreshFiles()
  ElMessage.success('文件已重命名')
}

async function deleteCurrentFile() {
  if (!editingFile.value) return
  await ElMessageBox.confirm(`确认删除 ${editingFile.value.path}？`, '删除文件', { type: 'warning' })
  await store.deleteFile(props.instanceId, editingFile.value.path)
  editingFile.value = null
  selectedFilePath.value = ''
  editorContent.value = ''
  await refreshFiles()
  ElMessage.success('文件已删除')
}

async function deleteFileRef(file: MccFileEntry) {
  await ElMessageBox.confirm(`确认删除 ${file.path}？`, '删除文件', { type: 'warning' })
  await store.deleteFile(props.instanceId, file.path)
  if (selectedFilePath.value === file.path) {
    editingFile.value = null
    selectedFilePath.value = ''
    editorContent.value = ''
  }
  await refreshFiles()
  ElMessage.success('文件已删除')
}

async function downloadSingleFile(path: string) {
  const blob = await store.downloadFile(props.instanceId, path)
  if (blob) {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = path.split('/').pop() || path
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('下载完成')
  }
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const raw = await file.arrayBuffer()
    const bytes = new Uint8Array(raw)
    let base64 = ''
    for (let i = 0; i < bytes.length; i++) base64 += String.fromCharCode(bytes[i])
    base64 = btoa(base64)
    const targetPath = currentPath.value ? `${currentPath.value}/${file.name}` : file.name
    await store.uploadFile(props.instanceId, targetPath, base64)
    await refreshFiles()
    ElMessage.success('文件已上传')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '上传失败')
  } finally {
    input.value = ''
  }
}

function onContextMenu(event: MouseEvent, file: MccFileEntry | null) {
  contextMenuX.value = event.clientX
  contextMenuY.value = event.clientY
  contextFile.value = file
  contextMenuVisible.value = true
}

watch(() => props.instanceId, () => { if (props.instanceId) refreshFiles() })
onMounted(() => refreshFiles())
</script>

<style scoped>
.file-manager { display: flex; flex-direction: column; gap: 10px; min-height: 520px; }
.file-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 4px; }
.breadcrumbs { color: var(--text-secondary); font-size: 14px; }
.crumb-link { color: var(--green-primary); cursor: pointer; text-decoration: none; }
.crumb-link:hover { text-decoration: underline; }
.crumb-sep { color: var(--text-muted); }
.toolbar-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.pixel-btn.small { padding: 5px 10px; font-size: 12px; }
.upload-btn { cursor: pointer; }
.file-layout { display: grid; grid-template-columns: 220px 1fr; gap: 12px; min-height: 480px; }
.file-tree-panel { background: #000; border: 1px solid var(--border-card); overflow: auto; padding: 8px; }
.tree-title { color: var(--text-muted); font-size: 12px; padding: 6px; border-bottom: 1px solid var(--border-subtle); margin-bottom: 6px; }
.tree-folder { color: var(--text-secondary); padding: 7px 10px; cursor: pointer; font-family: var(--font-mono); font-size: 12px; }
.tree-folder:hover { background: rgba(0, 255, 65, .08); color: var(--text-primary); }
.tree-folder.active { background: rgba(0, 255, 65, .14); color: var(--green-primary); }
.file-main { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.file-list { background: #000; border: 1px solid var(--border-card); overflow: auto; max-height: 340px; }
.file-row { display: grid; grid-template-columns: 48px 1fr auto; gap: 8px; padding: 10px; border-bottom: 1px solid var(--border-subtle); color: var(--text-secondary); cursor: pointer; align-items: center; }
.file-row:hover, .file-row.active { background: rgba(0, 255, 65, .12); color: var(--text-primary); }
.file-row span, .file-row em { color: var(--text-muted); font-style: normal; font-family: var(--font-mono); font-size: 12px; }
.file-actions-inline { display: flex; gap: 10px; align-items: center; }
.mini-btn { color: var(--green-primary); background: none; border: 1px solid var(--border-subtle); padding: 2px 7px; font-family: var(--font-mono); font-size: 11px; cursor: pointer; }
.mini-btn:hover { background: var(--green-glow); }
.file-editor { min-width: 0; }
.editor-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; color: var(--text-secondary); }
.secret-note { color: var(--warning); }
.empty-editor { padding: 80px 0; text-align: center; color: var(--text-muted); border: 1px dashed var(--border-subtle); }
.empty-list { padding: 40px 0; text-align: center; color: var(--text-muted); }
.editor-actions { display: flex; gap: 10px; margin: 10px 0; }
.diff-output { max-height: 200px; overflow: auto; background: #000; color: var(--text-secondary); border: 1px solid var(--border-card); padding: 10px; white-space: pre-wrap; font-size: 12px; }
:deep(.code-editor textarea) { font-family: var(--font-mono); color: var(--green-primary); background: #000; }
.context-menu { position: fixed; background: #0a0a0a; border: 1px solid var(--green-primary); z-index: 9999; min-width: 140px; box-shadow: 0 0 12px rgba(0, 255, 65, .18); }
.context-item { padding: 8px 14px; color: var(--text-secondary); font-family: var(--font-mono); font-size: 13px; cursor: pointer; }
.context-item:hover { background: var(--green-glow); color: var(--text-primary); }
.context-item.danger { color: var(--danger); }
.context-item.danger:hover { background: rgba(255, 77, 79, .15); }
@media (max-width: 900px) { .file-layout { grid-template-columns: 1fr; } .file-tree-panel { max-height: 200px; } }
</style>
