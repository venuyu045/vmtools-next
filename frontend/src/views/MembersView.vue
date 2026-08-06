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
        <el-table-column label="注册时间" min-width="150">
          <template #default="{ row }">
            <span class="mono time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button size="small" type="success" plain @click="setStatus(row, 'approved')">通过</el-button>
              <el-button size="small" type="danger" plain @click="setStatus(row, 'rejected')">拒绝</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="setStatus(row, 'approved')" :disabled="row.status === 'approved'">启用</el-button>
              <el-button size="small" type="warning" plain @click="setStatus(row, 'banned')" :disabled="row.status === 'banned'">封禁</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { membersApi, type MemberUser } from '@/api/members'

const loading = ref(false)
const users = ref<MemberUser[]>([])
const statusFilter = ref('')

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

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .members-page { max-width: 100%; }
  .member-toolbar { flex-direction: column; align-items: flex-start; }
  .refresh-btn { margin-left: 0; }
}
</style>