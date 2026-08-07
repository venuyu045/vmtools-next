<template>
  <div class="login-page">
    <div class="login-card pixel-card">
      <div class="login-header">
        <h1 class="pixel">注册账号</h1>
        <p>使用 QQ 认证注册，注册后直接生效</p>
      </div>
      <el-button
        class="qq-btn"
        size="large"
        :loading="qqLoading"
        @click="handleQqAuth"
        style="width: 100%"
      >
        <template v-if="!qqVerified">
          <span class="qq-icon">Q</span> 使用 QQ 一键注册
        </template>
        <template v-else>
          <span class="qq-icon">✓</span> QQ 已认证：{{ qqNickname || '已认证' }}
        </template>
      </el-button>
      <el-divider style="margin: 16px 0"><span style="color: var(--text-muted)">或</span></el-divider>
      <el-form @submit.prevent="handleRegister" class="login-form">
        <el-form-item>
          <el-input
            v-model="form.game_id"
            placeholder="Game ID"
            size="large"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码（至少 6 位）"
            size="large"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.confirm_password"
            type="password"
            placeholder="确认密码"
            size="large"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          @click="handleRegister"
          style="width: 100%"
        >
          > 注册并登录
        </el-button>
        <div class="back-login">
          <el-link type="primary" @click="goBack">← 返回登录</el-link>
        </div>
      </el-form>
      <div class="login-footer mono">
        v3.0 · MCC Server · Build Automation
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const qqLoading = ref(false)
const qqVerified = ref(false)
const qqTicket = ref('')
const qqNickname = ref('')
const form = reactive({ game_id: '', password: '', confirm_password: '' })

async function handleQqAuth() {
  if (qqVerified.value) return
  qqLoading.value = true
  try {
    await authStore.startQqAuth()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'QQ 登录暂不可用，请稍后再试')
    qqLoading.value = false
  }
}

/** 处理 QQ 回调落地：已注册→直接登录；未注册→预填并允许注册 */
async function handleQqTicket(ticket: string) {
  try {
    const res = await authStore.qqTicketLogin(ticket)
    if (res.loggedIn) {
      ElMessage.success('QQ 登录成功')
      router.push('/dashboard')
    } else {
      qqVerified.value = true
      qqTicket.value = ticket
      qqNickname.value = res.nickname || ''
      ElMessage.success(`QQ 认证成功${res.nickname ? `（${res.nickname}）` : ''}，请填写 Game ID 和密码完成注册`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'QQ 认证已过期，请重新发起')
    router.replace('/register')
  }
}

async function handleRegister() {
  if (!qqVerified.value || !qqTicket.value) {
    ElMessage.warning('请先点击「使用 QQ 一键注册」完成 QQ 认证')
    return
  }
  if (!form.game_id.trim()) {
    ElMessage.warning('请输入游戏 Game ID')
    return
  }
  if (!form.password) {
    ElMessage.warning('请输入密码')
    return
  }
  if (form.password.length < 6) {
    ElMessage.warning('密码长度至少 6 位')
    return
  }
  if (form.password !== form.confirm_password) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    const data = await authStore.register(form.game_id.trim(), form.password, qqNickname.value || form.game_id.trim(), qqTicket.value)
    if (data?.token) {
      ElMessage.success('注册成功，已自动登录')
      router.push('/dashboard')
    } else {
      ElMessage.success('注册成功')
      router.push('/login')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push('/login')
}

onMounted(() => {
  const ticket = route.query.qq_ticket as string | undefined
  if (ticket) {
    handleQqTicket(ticket)
  }
})
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000;
  position: relative;
}

.login-page::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    rgba(0, 255, 0, 0.03) 0px,
    rgba(0, 255, 0, 0.03) 1px,
    transparent 1px,
    transparent 3px
  );
  pointer-events: none;
}

.login-card {
  width: 400px;
  max-width: calc(100vw - 32px);
  padding: 48px 40px;
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-header h1 {
  color: var(--green-primary);
  font-size: 24px;
  margin-bottom: 8px;
  text-shadow: 0 0 20px rgba(0,255,0,0.3);
}

.login-header p {
  color: var(--text-secondary);
  font-size: 14px;
  font-family: var(--font-body);
}

.back-login {
  text-align: center;
  margin-top: 16px;
}

.qq-btn {
  background: #12b7f5;
  border-color: #12b7f5;
  color: #fff;
}
.qq-btn:hover {
  background: #0aa3dc;
  border-color: #0aa3dc;
  color: #fff;
}
.qq-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-right: 8px;
  border-radius: 4px;
  background: #fff;
  color: #12b7f5;
  font-weight: 700;
  font-size: 13px;
  line-height: 1;
}

.login-footer {
  text-align: center;
  margin-top: 24px;
  color: var(--text-muted);
  font-size: 14px;
}

@media (max-width: 480px) {
  .login-card {
    width: 100%;
    max-width: 100%;
    padding: 36px 20px;
    border-left: none;
    border-right: none;
  }

  .login-header h1 {
    font-size: 20px;
  }

  .login-header p {
    font-size: 12px;
  }

  .login-footer {
    font-size: 12px;
    margin-top: 20px;
  }
}
</style>
