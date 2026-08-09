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
      <!-- 主题切换（快速亮/暗） -->
      <button
        class="theme-btn"
        @click="toggleTheme()"
        :title="`主题：${themeResolved === 'dark' ? '暗色' : '亮色'}（点击切换）`"
        :aria-label="`切换为${themeResolved === 'dark' ? '亮色' : '暗色'}主题`"
      >
        <span class="theme-btn-icon">◐</span><span class="theme-btn-text">{{ themeResolved === 'dark' ? '暗' : '亮' }}</span>
      </button>
      <!-- 未登录（访客）：显示「登录」按钮，点击进入登录页 -->
      <router-link v-if="!authStore.isLoggedIn" to="/login" class="profile-btn login-link">登录</router-link>
      <template v-else>
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
          <div class="profile-role theme-select">
            <span class="profile-label">主题</span>
            <el-radio-group v-model="themeMode" size="small" @change="onThemeChange">
              <el-radio-button :value="'light'">亮色</el-radio-button>
              <el-radio-button :value="'dark'">暗色</el-radio-button>
              <el-radio-button :value="'system'">跟随</el-radio-button>
            </el-radio-group>
          </div>
          <button class="profile-item" @click="openChangePwd">更改密码</button>
          <button class="profile-item danger" @click="authStore.logout()">退出登录</button>
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
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore, roleLabel } from '@/stores/auth'
import { authApi } from '@/api/auth'
import { useTheme } from '@/composables/useTheme'

const emit = defineEmits<{
  toggleSidebar: []
  openMobileMenu: []
}>()
const route = useRoute()
const authStore = useAuthStore()
const { mode: themeMode, resolved: themeResolved, setThemeMode, toggleTheme } = useTheme()

const shortName = computed(() => {
  const name = authStore.user?.display_name || authStore.user?.game_id || ''
  return name.length > 8 ? name.slice(0, 8) + '...' : name
})

// ── 更改密码 ──
const showPwdDialog = ref(false)
const pwdSaving = ref(false)
const pwdForm = reactive({ old: '', new1: '', new2: '' })

function onThemeChange(v: string | number | boolean | undefined) {
  if (v === 'light' || v === 'dark' || v === 'system') {
    setThemeMode(v)
  }
}

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
  background: var(--bg-card);
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
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 14px;
  flex-shrink: 0;
  transition: background-color 150ms var(--ease-out), border-color 150ms var(--ease-out), color 150ms var(--ease-out);
}

.sidebar-toggle:hover,
.mobile-menu-btn:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
  color: var(--text-primary);
}

/* ---- Page Title ---- */
.page-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 400;
  letter-spacing: -0.5px;
  color: var(--text-primary);
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
  border-radius: 50%;
  background: var(--success);
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

.theme-btn {
  background: none;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-sans);
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  transition: background-color 150ms var(--ease-out), border-color 150ms var(--ease-out), color 150ms var(--ease-out);
}

.theme-btn-icon {
  font-size: 13px;
  line-height: 1;
}

.theme-btn:hover {
  border-color: var(--accent);
  color: var(--text-primary);
  background: var(--bg-hover);
}

.theme-select {
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 4px;
}

.profile-btn {
  background: none;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-sans);
  flex-shrink: 0;
  transition: background-color 150ms var(--ease-out), border-color 150ms var(--ease-out), color 150ms var(--ease-out);
}

.profile-btn:hover {
  border-color: var(--accent);
  color: var(--text-primary);
  background: var(--bg-hover);
}

/* 未登录「登录」按钮（访客模式入口） */
.login-link {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
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
  color: var(--accent);
  border: 1px solid var(--accent-soft);
  padding: 2px 10px;
  border-radius: var(--radius-md);
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
  border-radius: var(--radius-md);
  font-family: var(--font-sans);
  transition: background-color 150ms var(--ease-out), color 150ms var(--ease-out);
}

.profile-item:hover {
  background: var(--green-glow);
  color: var(--green-primary);
}

.profile-item.danger {
  color: var(--danger);
}

.profile-item.danger:hover {
  background: var(--danger-bg);
  color: var(--danger);
}

/* ============ RESPONSIVE ============ */
/* 桌面：仅显示 sidebar-toggle（折叠按钮），隐藏移动汉堡（防 global utility 被 scoped display:flex 覆盖） */
@media (min-width: 769px) {
  .mobile-menu-btn { display: none; }
}

@media (max-width: 768px) {
  .sidebar-toggle { display: none; }

  .header {
    padding: 0 12px;
  }

  .header-left {
    gap: 10px;
    min-width: 0;
  }

  .sidebar-toggle,
  .mobile-menu-btn {
    width: 36px;
    height: 36px;
    font-size: 18px;
  }

  .page-title {
    font-size: 13px;
    max-width: 38vw;
  }

  .theme-btn {
    min-height: 36px;
    padding: 4px 10px;
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
    max-width: 30vw;
  }

  /* 超窄屏：主题按钮图标化（隐藏文字），为标题/个人按钮腾出空间 */
  .theme-btn {
    padding: 6px 9px;
    font-size: 13px;
    gap: 0;
  }
  .theme-btn-text {
    display: none;
  }

  .profile-btn {
    padding: 4px 8px;
    font-size: 10px;
  }

  .header-right {
    gap: 6px;
  }
}
</style>
