<template>
  <div class="login-page">
    <!-- 右上角主题切换（三态：跟随系统 / 亮 / 暗，localStorage 持久化） -->
    <ThemeSwitch class="login-theme-switch" />
    <!-- 左：深色 Hero（品牌区） -->
    <div class="login-hero">
      <div class="hero-inner">
        <div class="hero-brand">VMTools</div>
        <h1 class="hero-title">Minecraft 假人控制面板</h1>
        <p class="hero-desc">把服务器运维，像一本精装书一样排版——数据清晰、克制、可信。</p>
        <div class="hero-accent-line"></div>
        <p class="hero-foot">MCC · Mineflayer · Warehouse · Monitor</p>
      </div>
    </div>

    <!-- 右：米色表单区 -->
    <div class="login-form-area">
      <div class="form-inner">
        <h2 class="form-title">欢迎回来</h2>
        <p class="form-sub">登录以继续管理你的 Minecraft 服务器</p>
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
            登录
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
        <div class="login-icp">
          <a href="https://beian.miit.gov.cn" target="_blank" rel="noopener noreferrer">渝ICP备2026011793号-1</a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import ThemeSwitch from '@/components/ThemeSwitch.vue'
import { errMsg } from '@/utils/error'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const qqLoading = ref(false)
const form = reactive({ game_id: '', password: '' })

/** 访客被引导登录（点击受限区域/受限操作）：以通知形式提示「前面的区域以后再来探索吧」 */
const lockedReason = computed(() => route.query.reason === 'locked')

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
    ElMessage.error(errMsg(e, '登录失败'))
  } finally {
    loading.value = false
  }
}

async function handleQqLogin() {
  qqLoading.value = true
  try {
    await authStore.startQqAuth()
  } catch (e: any) {
    ElMessage.error(errMsg(e, 'QQ 登录暂不可用，请稍后再试'))
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
    ElMessage.error(errMsg(e, 'QQ 认证已过期，请重新发起'))
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
  // 访客被引导登录（点击受限区域/受限操作）：以通知形式提示
  if (lockedReason.value) {
    ElMessage.warning('前面的区域以后再来探索吧')
  }
})
</script>

<style scoped>
.login-page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  background: var(--bg-page);
  position: relative;
}

/* 右上角主题切换：固定悬浮，避让刘海屏安全区 */
.login-theme-switch {
  position: fixed;
  top: calc(env(safe-area-inset-top, 0px) + 12px);
  right: 14px;
  z-index: 50;
}

/* ---- 左：深色 Hero（始终深色，不随主题反转） ---- */
.login-hero {
  flex: 1 1 55%;
  background: var(--terminal-bg);
  background-image: radial-gradient(1200px 600px at 85% -10%, rgba(217, 119, 87, 0.10), transparent 60%);
  color: var(--terminal-text);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 64px 48px;
  position: relative;
  overflow: hidden;
}

.hero-inner {
  max-width: 480px;
}

.hero-brand {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 400;
  letter-spacing: -0.5px;
  color: var(--accent);
  margin-bottom: 24px;
}

.hero-title {
  font-family: var(--font-display);
  font-size: 40px;
  font-weight: 400;
  letter-spacing: -1.5px;
  line-height: 1.25;
  color: var(--terminal-text);
  margin-bottom: 16px;
}

.hero-desc {
  font-family: var(--font-body);
  font-size: 16px;
  line-height: 1.75;
  color: rgba(245, 243, 236, 0.72);
  max-width: 36ch;
  margin-bottom: 32px;
}

.hero-accent-line {
  width: 48px;
  height: 2px;
  background: var(--accent);
  border-radius: 1px;
  margin-bottom: 32px;
}

.hero-foot {
  font-family: var(--font-mono);
  font-size: 13px;
  letter-spacing: 0.5px;
  color: rgba(245, 243, 236, 0.45);
}

/* ---- 右：米色表单区 ---- */
.login-form-area {
  flex: 1 1 45%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
  background: var(--bg-page);
}

.form-inner {
  width: 360px;
  max-width: 100%;
}

.form-title {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 400;
  letter-spacing: -1px;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.form-sub {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 32px;
}

.login-register {
  margin-top: 20px;
  text-align: center;
  font-size: 14px;
}

.register-hint {
  color: var(--text-secondary);
  margin-right: 4px;
}

.qq-btn {
  /* 覆盖 EP 相邻按钮默认 margin-left:12px（.el-button + .el-button），
     否则 QQ 登录按钮会整体右偏 12px（与上方「登录」按钮不对齐） */
  margin-left: 0 !important;
  background: #12b7f5;
  border-color: #12b7f5;
  color: #fff;
}
.qq-btn:hover {
  background: #0aa3dc;
  border-color: #0aa3dc;
  color: #fff;
}
/* 深色下 #12b7f5 满色块面积大且亮度高（L≈62%），在暖墨底上过于刺眼；
   改为低饱和半透明底 + 品牌色描边与文字，既保留 QQ 品牌识别又不扎眼。 */
[data-theme="dark"] .qq-btn,
html.dark .qq-btn {
  background: rgba(18, 183, 245, 0.14) !important;
  border-color: rgba(18, 183, 245, 0.45) !important;
  color: #6fd3fa !important;
}
[data-theme="dark"] .qq-btn:hover,
html.dark .qq-btn:hover {
  background: rgba(18, 183, 245, 0.22) !important;
  border-color: rgba(18, 183, 245, 0.65) !important;
  color: #9ce2ff !important;
}
[data-theme="dark"] .qq-icon,
html.dark .qq-icon {
  background: rgba(18, 183, 245, 0.9);
  color: #0d1b22;
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
  margin-top: 16px;
}

.login-icp a {
  color: var(--text-muted);
  font-size: 12px;
  text-decoration: none;
  transition: color 0.2s;
}

.login-icp a:hover {
  color: var(--text-secondary);
}

/* Override browser autofill white background */
:deep(.el-input__inner:-webkit-autofill),
:deep(.el-input__inner:-webkit-autofill:hover),
:deep(.el-input__inner:-webkit-autofill:focus),
:deep(.el-input__inner:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 30px var(--bg-input) inset !important;
  -webkit-text-fill-color: var(--text-primary) !important;
  transition: background-color 5000s ease-in-out 0s;
  caret-color: var(--text-primary);
}

/* ============ RESPONSIVE ============ */
@media (max-width: 900px) {
  .login-hero { display: none; }
  /* 单列时 flex-basis 必须归零：保留 45% 基准会让「基准宽度 + 左右 padding」
     超出视口（360px 屏实测表单区被撑到 400px，整页横向溢出、右侧内容被裁）。 */
  .login-form-area {
    flex: 1 1 auto;
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
  }
}

@media (max-width: 480px) {
  .login-form-area { padding: 40px 20px; }
  .form-title { font-size: 26px; }
  .form-sub { margin-bottom: 24px; }
}
</style>
