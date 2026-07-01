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
</style>
