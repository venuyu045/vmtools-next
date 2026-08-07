<template>
  <div class="login-page">
    <div class="login-card pixel-card">
      <div class="login-header">
        <h1 class="pixel">VMTools</h1>
        <p>MCC 自动化管理平台</p>
      </div>
      <el-form @submit.prevent="handleLogin" class="login-form">
        <el-form-item>
          <el-input
            v-model="form.game_id"
            placeholder="Game ID"
            size="large"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="Password"
            size="large"
            show-password
          />
        </el-form-item>
        <el-button
        type="primary"
        size="large"
        :loading="loading"
        @click="handleLogin"
        style="width: 100%"
      >
        > 登录
      </el-button>
      <el-button
        class="qq-btn"
        size="large"
        :loading="qqLoading"
        @click="handleQqLogin"
        style="width: 100%; margin-top: 12px"
      >
        <span class="qq-icon">Q</span> QQ 登录
      </el-button>
      <div class="login-register">
        <span class="register-hint">还没有账号？</span>
        <el-link type="primary" @click="goRegister">立即注册</el-link>
      </div>
      </el-form>
      <div class="login-footer mono">
        v3.0 · MCC Server · Build Automation
      </div>
      <div class="login-icp">
        <a href="https://beian.miit.gov.cn" target="_blank" rel="noopener noreferrer">渝ICP备2026011793号-1</a>
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
const form = reactive({ game_id: '', password: '' })

async function handleLogin() {
  if (!form.game_id || !form.password) {
    ElMessage.warning('请输入 Game ID 和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.game_id, form.password)
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}

async function handleQqLogin() {
  qqLoading.value = true
  try {
    await authStore.startQqAuth()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'QQ 登录暂不可用，请稍后再试')
    qqLoading.value = false
  }
}

/** QQ 回调落地：已注册→直接登录；未注册→跳注册页预填 */
async function handleQqTicket(ticket: string) {
  qqLoading.value = true
  try {
    const res = await authStore.qqTicketLogin(ticket)
    if (res.loggedIn) {
      ElMessage.success('QQ 登录成功')
      router.replace('/dashboard')
    } else {
      router.replace(`/register?qq_ticket=${ticket}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || 'QQ 认证已过期，请重新发起')
  } finally {
    qqLoading.value = false
  }
}

function goRegister() {
  router.push('/register')
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

.login-footer {
  text-align: center;
  margin-top: 24px;
  color: var(--text-muted);
  font-size: 14px;
}

.login-register {
  margin-top: 16px;
  text-align: center;
  font-size: 14px;
}

.register-hint {
  color: var(--text-secondary);
  margin-right: 4px;
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

.login-icp {
  text-align: center;
  margin-top: 12px;
  padding-bottom: 4px;
}

.login-icp a {
  color: #666;
  font-size: 12px;
  text-decoration: none;
  transition: color 0.2s;
}

.login-icp a:hover {
  color: #999;
}

/* Override browser autofill white background */
:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 30px #0a0a0a inset !important;
  -webkit-text-fill-color: var(--text-primary) !important;
  transition: background-color 5000s ease-in-out 0s;
  caret-color: var(--text-primary);
}

/* ============ RESPONSIVE ============ */
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

  .login-header {
    margin-bottom: 24px;
  }

  .login-footer {
    font-size: 12px;
    margin-top: 20px;
  }
}
</style>
