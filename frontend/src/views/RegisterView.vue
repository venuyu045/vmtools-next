<template>
  <div class="login-page">
    <div class="login-card pixel-card">
      <div class="login-header">
        <h1 class="pixel">注册账号</h1>
        <p>提交后等待管理员审核</p>
      </div>
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
            placeholder="密码"
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
          > 提交注册申请
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
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const form = reactive({ game_id: '', password: '', confirm_password: '' })

async function handleRegister() {
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
    await authStore.register(form.game_id.trim(), form.password)
    ElMessage.success('注册申请已提交，请等待管理员审核')
    router.push('/login')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push('/login')
}
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
