<template>
  <div class="members-page">
    <h2 class="pixel page-title">成员管理</h2>
    <p class="page-subtitle mono">审批注册申请 · 管理所有成员的状态与角色</p>

    <el-card shadow="never" class="member-card">
      <div class="member-toolbar">
        <el-radio-group v-model="statusFilter" size="small" @change="loadUsers">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="pending">待审批</el-radio-button>
          <el-radio-button label="approved">已批准</el-radio-button>
          <el-radio-button label="rejected">已拒绝</el-radio-button>
          <el-radio-button label="banned">已封禁</el-radio-button>
        </el-radio-group>
        <el-button size="small" class="refresh-btn" @click="loadUsers">刷新</el-button>
      </div>

      <el-table
        v-loading="loading"
        :data="users"
        stripe
        style="width: 100%"
        empty-text="暂无成员"
      >
        <el-table-column label="Game ID" prop="game_id" min-width="120" />
        <el-table-column label="显示名" prop="display_name" min-width="120" />
        <el-table-column label="角色" min-width="120">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              size="small"
              class="role-select"
              @change="(val: string) => changeRole(row, val)"
            >
              <el-option label="站点管理员" value="site_admin" />
              <el-option label="管理员" value="admin" />
              <el-option label="用户" value="user" />
              <el-option label="访客" value="guest" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <span class="status-tag" :class="row.status">{{ statusLabel(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="上次上线" min-width="150">
          <template #default="{ row }">
            <span class="mono time-text">{{ formatTime(row.last_seen_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button size="small" type="success" plain @click="setStatus(row, 'approved')">通过</el-button>
              <el-button size="small" type="danger" plain @click="setStatus(row, 'rejected')">拒绝</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="setStatus(row, 'approved')" :disabled="row.status === 'approved'">启用</el-button>
              <el-button size="small" type="warning" plain @click="setStatus(row, 'banned')" :disabled="row.status === 'banned'">封禁</el-button>
            </template>
            <el-button size="small" type="primary" plain @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 编辑成员弹窗（修改角色/状态 + 删除成员） -->
    <el-dialog v-model="editOpen" title="编辑成员" width="420px">
      <div v-if="editRow" class="edit-form">
        <div class="edit-meta">
          <span class="edit-game">{{ editRow.game_id }}</span>
          <span class="edit-name">{{ editRow.display_name || '—' }}</span>
        </div>
        <el-form label-width="90px">
          <el-form-item label="角色">
            <el-select v-model="editForm.role" style="width: 100%">
              <el-option label="站点管理员" value="site_admin" />
              <el-option label="管理员" value="admin" />
              <el-option label="用户" value="user" />
              <el-option label="访客" value="guest" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="editForm.status" style="width: 100%">
              <el-option label="待审批" value="pending" />
              <el-option label="已批准" value="approved" />
              <el-option label="已拒绝" value="rejected" />
              <el-option label="已封禁" value="banned" />
            </el-select>
          </el-form-item>
          <el-form-item label="注册时间">
            <span class="mono time-text">{{ formatTime(editRow.created_at) }}</span>
          </el-form-item>
          <el-form-item label="上次上线">
            <span class="mono time-text">{{ formatTime(editRow.last_seen_at) }}</span>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button type="danger" plain @click="removeUser">删除成员</el-button>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { membersApi, type MemberUser } from '@/api/members'

const loading = ref(false)
const users = ref<MemberUser[]>([])
const statusFilter = ref('')

// ── 编辑成员弹窗 ──
const editOpen = ref(false)
const editSaving = ref(false)
const editRow = ref<MemberUser | null>(null)
const editForm = reactive({ role: 'user', status: 'approved' })

const STATUS_LABELS: Record<string, string> = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  banned: '已封禁',
}

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await membersApi.list(statusFilter.value || undefined)
    users.value = data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载成员列表失败')
  } finally {
    loading.value = false
  }
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status
}

function formatTime(t: string | null): string {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function setStatus(row: MemberUser, status: string) {
  const label = STATUS_LABELS[status] || status
  try {
    await ElMessageBox.confirm(`确认将成员「${row.game_id}」设为「${label}」？`, '确认操作', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const { data } = await membersApi.update(row.id, { status })
    Object.assign(row, data)
    ElMessage.success(`已将 ${row.game_id} 设为 ${label}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function changeRole(row: MemberUser, role: string) {
  try {
    const { data } = await membersApi.update(row.id, { role })
    Object.assign(row, data)
    ElMessage.success(`已将 ${row.game_id} 的角色更新为 ${role}`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '更新角色失败')
  }
}

// ── 编辑成员：打开弹窗（预填当前角色/状态） ──
function openEdit(row: MemberUser) {
  editRow.value = row
  editForm.role = row.role
  editForm.status = row.status
  editOpen.value = true
}

// ── 保存编辑（角色/状态） ──
async function saveEdit() {
  if (!editRow.value) return
  const row = editRow.value
  editSaving.value = true
  try {
    const patch: { role?: string; status?: string } = {}
    if (editForm.role !== row.role) patch.role = editForm.role
    if (editForm.status !== row.status) patch.status = editForm.status
    if (!Object.keys(patch).length) { editOpen.value = false; return }
    const { data } = await membersApi.update(row.id, patch)
    Object.assign(row, data)
    ElMessage.success(`已保存 ${row.game_id} 的修改`)
    editOpen.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    editSaving.value = false
  }
}

// ── 删除成员 ──
async function removeUser() {
  if (!editRow.value) return
  const row = editRow.value
  try {
    await ElMessageBox.confirm(
      `确认删除成员「${row.game_id}」？删除后不可恢复。`,
      '删除成员',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await membersApi.remove(row.id)
    users.value = users.value.filter(u => u.id !== row.id)
    ElMessage.success(`已删除成员 ${row.game_id}`)
    editOpen.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.members-page { max-width: 1080px; }
.page-title { color: var(--green-primary); font-size: 16px; margin-bottom: 4px; }
.page-subtitle { color: var(--text-muted); font-size: 13px; margin-bottom: 16px; }

.member-card { background: #0a0a0a; }
.member-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.refresh-btn { margin-left: auto; }

.role-select { width: 130px; }

.status-tag {
  display: inline-block;
  padding: 2px 10px;
  font-size: 12px;
  font-family: var(--font-mono);
  border: 1px solid var(--border-card);
}
.status-tag.pending { color: var(--color-warning, #e6a23c); border-color: rgba(230, 162, 60, 0.4); }
.status-tag.approved { color: var(--green-primary); border-color: rgba(0, 255, 0, 0.3); }
.status-tag.rejected { color: var(--color-error, #f56c6c); border-color: rgba(245, 108, 108, 0.4); }
.status-tag.banned { color: var(--color-error, #f56c6c); border-color: rgba(245, 108, 108, 0.4); }

.time-text { color: var(--text-secondary); font-size: 12px; }

/* 编辑弹窗 */
.edit-form { padding: 4px 0 8px; }
.edit-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 14px;
  background: #000;
  border: 1px solid var(--border-subtle);
}
.edit-game { color: var(--green-primary); font-weight: bold; font-size: 15px; }
.edit-name { color: var(--text-muted); font-size: 13px; }

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .members-page { max-width: 100%; }
  .member-toolbar { flex-direction: column; align-items: flex-start; }
  .refresh-btn { margin-left: 0; }
}
</style>