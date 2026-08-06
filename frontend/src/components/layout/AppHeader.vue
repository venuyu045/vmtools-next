<template>
  <div class="header">
    <div class="header-left">
      <!-- Mobile: hamburger menu button -->
      <button class="mobile-menu-btn show-on-mobile" @click="emit('openMobileMenu')" title="菜单" aria-label="打开菜单">
        ☰
      </button>
      <!-- Desktop: sidebar collapse toggle -->
      <button class="sidebar-toggle hide-on-mobile" @click="emit('toggleSidebar')" title="切换侧边栏" aria-label="切换侧边栏">
        ☰
      </button>
      <div class="page-title" v-if="route.meta.title">
        > {{ route.meta.title }}
      </div>
      <div class="page-title" v-else>
        > VMTools
      </div>
    </div>
    <div class="header-right">
      <span class="user-dot"></span>
      <span class="username hide-on-mobile">{{ authStore.user?.display_name || authStore.user?.game_id }}</span>
      <span class="username-mobile show-on-mobile">{{ shortName }}</span>

      <!-- 个人中心弹窗 -->
      <el-popover
        placement="bottom-end"
        :width="240"
        trigger="click"
        popper-class="user-popover"
      >
        <template #reference>
          <button class="profile-btn" aria-label="个人中心">个人</button>
        </template>
        <div class="profile-menu">
          <div class="profile-role">
            <span class="profile-label">当前权限组</span>
            <span class="profile-role-tag">{{ roleLabel(authStore.user?.role) }}</span>
          </div>
          <button class="profile-item" @click="openChangePwd">🔑 更改密码</button>
          <button class="profile-item danger" @click="authStore.logout()">⏻ 退出登录</button>
        </div>
      </el-popover>

      <!-- 修改密码对话框 -->
      <el-dialog v-model="showPwdDialog" title="更改密码" width="360px" append-to-body>
        <el-form label-width="90px" @submit.prevent="submitChangePwd">
          <el-form-item label="旧密码">
            <el-input v-model="pwdForm.old" type="password" show-password placeholder="请输入旧密码" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="pwdForm.new1" type="password" show-password placeholder="至少 6 位" />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="pwdForm.new2" type="password" show-password placeholder="再次输入新密码" @keyup.enter="submitChangePwd" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showPwdDialog = false">取消</el-button>
          <el-button type="primary" :loading="pwdSaving" @click="submitChangePwd">确认修改</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore, roleLabel } from '@/stores/auth'
import { authApi } from '@/api/auth'

defineProps<{ isMobile?: boolean }>()
const emit = defineEmits<{
  toggleSidebar: []
  openMobileMenu: []
}>()
const route = useRoute()
const authStore = useAuthStore()

const shortName = computed(() => {
  const name = authStore.user?.display_name || authStore.user?.game_id || ''
  return name.length > 8 ? name.slice(0, 8) + '...' : name
})

// ── 更改密码 ──
const showPwdDialog = ref(false)
const pwdSaving = ref(false)
const pwdForm = reactive({ old: '', new1: '', new2: '' })

function openChangePwd() {
  pwdForm.old = ''
  pwdForm.new1 = ''
  pwdForm.new2 = ''
  showPwdDialog.value = true
}

async function submitChangePwd() {
  if (!pwdForm.old) { ElMessage.warning('请输入旧密码'); return }
  if (!pwdForm.new1 || pwdForm.new1.length < 6) { ElMessage.warning('新密码长度不能少于 6 位'); return }
  if (pwdForm.new1 !== pwdForm.new2) { ElMessage.warning('两次输入的新密码不一致'); return }
  pwdSaving.value = true
  try {
    await authApi.changePassword(pwdForm.old, pwdForm.new1)
    ElMessage.success('密码修改成功')
    showPwdDialog.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修改失败，请检查旧密码')
  } finally {
    pwdSaving.value = false
  }
}
</script>

<style scoped>
.header {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  background: #0a0a0a;
  border-bottom: 1px solid var(--border-subtle);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0; /* allow truncation */
}

/* ---- Toggle Buttons ---- */
.sidebar-toggle,
.mobile-menu-btn {
  background: none;
  border: 1px solid var(--border-card);
  color: var(--green-primary);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 14px;
  flex-shrink: 0;
}

.sidebar-toggle:hover,
.mobile-menu-btn:hover {
  border-color: var(--border-active);
  background: var(--green-glow);
  color: var(--text-primary);
}

/* ---- Page Title ---- */
.page-title {
  font-family: var(--font-pixel);
  font-size: 16px;
  color: var(--green-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- Right Side ---- */
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.user-dot {
  width: 8px;
  height: 8px;
  background: var(--green-primary);
  flex-shrink: 0;
}

.username,
.username-mobile {
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.profile-btn {
  background: none;
  border: 1px solid var(--border-card);
  color: var(--text-secondary);
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-body);
  flex-shrink: 0;
}

.profile-btn:hover {
  border-color: var(--border-active);
  color: var(--text-primary);
  background: var(--green-glow);
}

/* 个人中心弹窗 */
.profile-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
}

.profile-role {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 4px;
}

.profile-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.profile-role-tag {
  font-size: 12px;
  color: var(--green-primary);
  border: 1px solid rgba(0, 200, 83, 0.4);
  padding: 2px 10px;
  border-radius: 10px;
  font-family: var(--font-body);
}

.profile-item {
  background: none;
  border: none;
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  border-radius: 4px;
  font-family: var(--font-body);
  transition: background 0.15s;
}

.profile-item:hover {
  background: var(--green-glow);
  color: var(--green-primary);
}

.profile-item.danger {
  color: #f44336;
}

.profile-item.danger:hover {
  background: rgba(244, 67, 54, 0.12);
  color: #f44336;
}

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .header {
    padding: 0 12px;
  }

  .header-left {
    gap: 10px;
  }

  .sidebar-toggle,
  .mobile-menu-btn {
    width: 36px;
    height: 36px;
    font-size: 18px;
  }

  .page-title {
    font-size: 13px;
  }

  .profile-btn {
    padding: 4px 10px;
    font-size: 11px;
    min-height: 36px;
  }
}

@media (max-width: 480px) {
  .header {
    padding: 0 8px;
  }

  .header-left {
    gap: 8px;
  }

  .page-title {
    font-size: 11px;
  }

  .profile-btn {
    padding: 4px 8px;
    font-size: 10px;
  }
}
</style>
