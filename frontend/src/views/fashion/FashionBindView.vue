<template>
  <div class="fashion-bind-page">
    <h2 class="page-title">时装绑定</h2>
    <p class="page-subtitle mono">
      把 Minecraft 账号绑定到本站账号 · 绑定后可在网页衣柜里换装，游戏内 mod 与网页共用同一份穿戴配置
    </p>

    <div class="bind-grid">
      <!-- 已绑定身份 -->
      <el-card shadow="never" class="bind-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">我的 Minecraft 账号</span>
            <el-button
              size="small"
              text
              :loading="loadingIdentities"
              :disabled="loadingIdentities"
              @click="loadIdentities"
            >
              刷新
            </el-button>
          </div>
        </template>

        <div v-loading="loadingIdentities" class="card-body">
          <el-alert
            v-if="identitiesError"
            class="panel-error"
            type="error"
            :closable="false"
            show-icon
            title="读取绑定信息失败"
          >
            <template #default>
              <el-button size="small" text type="primary" @click="loadIdentities">重试</el-button>
            </template>
          </el-alert>
          <el-empty
            v-if="!loadingIdentities && !identitiesError && identities.length === 0"
            description="还没有绑定任何 Minecraft 账号"
            :image-size="72"
          />
          <div v-else-if="identities.length > 0" class="identity-list">
            <div v-for="identity in identities" :key="identity.id" class="identity-item">
              <div class="identity-main">
                <span class="mc-name">{{ identity.mcName }}</span>
                <span class="pixel-badge" :class="identity.authType === 'mojang' ? 'green' : 'yellow'">
                  <span class="badge-dot"></span>
                  {{ identity.authType === 'mojang' ? '正版' : '皮肤站' }}
                </span>
              </div>
              <div class="identity-meta mono">{{ identity.mcUuid }}</div>
              <div class="identity-meta mono">
                认证于 {{ formatTime(identity.verifiedAt) }}
                <template v-if="identity.lastSeenAt"> · 最近上线 {{ formatTime(identity.lastSeenAt) }}</template>
              </div>
              <div class="identity-actions">
                <el-button size="small" :disabled="!!unbindingId" @click="goWardrobe(identity.id)">去衣柜</el-button>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :loading="unbindingId === identity.id"
                  :disabled="!!unbindingId"
                  @click="handleUnbind(identity)"
                >
                  解绑
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 输入绑定码 -->
      <el-card shadow="never" class="bind-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">输入绑定码</span>
          </div>
        </template>
        <div class="card-body">
          <p class="hint mono">
            在游戏内执行 <code>/vmfashion bind</code>，mod 会在聊天栏显示 6 位绑定码（10 分钟内有效）。
            在下面输入该码即可完成绑定。
          </p>

          <div class="code-row">
            <el-input
              v-model="userCode"
              class="code-input"
              maxlength="12"
              placeholder="例如 7K2M9Q"
              aria-label="6 位绑定码"
              autocomplete="one-time-code"
              :disabled="approving"
              clearable
              @keyup.enter="handleApprove"
            />
            <el-button
              type="primary"
              :loading="approving"
              :disabled="normalizedCode.length !== 6 || approving"
              @click="handleApprove"
            >
              绑定
            </el-button>
          </div>

          <el-alert
            v-if="lastBound"
            class="bound-alert"
            type="success"
            :closable="true"
            show-icon
            :title="`已绑定 ${lastBound.mcName}`"
            :description="lastBound.mcUuid"
            @close="lastBound = null"
          />

          <p class="hint mono">
            绑定成功后可用
            <router-link class="link" to="/fashion/wardrobe">衣柜</router-link>
            管理穿戴。
          </p>
        </div>
      </el-card>
    </div>

    <!-- 说明 -->
    <el-card shadow="never" class="bind-card explain-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">为什么不是「输入 MC 密码」？</span>
        </div>
      </template>
      <div class="card-body">
        <p class="hint mono">
          网页拿不到 Minecraft 的 accessToken，所以本站不会、也不需要你输入 MC 密码。
          绑定走的是设备码流程：mod 端已经用标准 serverId 流程（Mojang 正版 / 皮肤站 Yggdrasil）
          向会话服务器验证过身份，网页只需要确认「这次绑定是我发起的」。
        </p>
        <ul class="explain-list mono">
          <li>绑定码 6 位、10 分钟有效、一次性使用；</li>
          <li>一个网站账号可以绑定多个 Minecraft 账号；</li>
          <li>解绑只会解除网站关联，不影响 mod 的认证状态。</li>
        </ul>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fashionApi,
  fashionErrorMessage,
  type DeviceApproveResult,
  type FashionIdentity,
} from '@/api/fashion'

const router = useRouter()

const identities = ref<FashionIdentity[]>([])
const loadingIdentities = ref(false)
const identitiesError = ref(false)
const userCode = ref('')
const approving = ref(false)
const unbindingId = ref('')
const lastBound = ref<DeviceApproveResult | null>(null)

// 身份列表请求竞态保护：刷新与绑定后的重新加载可能并发
let identitiesSeq = 0

const normalizedCode = computed(() => userCode.value.replace(/[\s-_]/g, '').toUpperCase())

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function loadIdentities(): Promise<void> {
  const seq = ++identitiesSeq
  loadingIdentities.value = true
  identitiesError.value = false
  try {
    const { data } = await fashionApi.myIdentities()
    if (seq !== identitiesSeq) return // 已被更新的请求取代，丢弃本次响应
    identities.value = data.items || []
  } catch (error) {
    if (seq !== identitiesSeq) return
    identitiesError.value = true
    ElMessage.error(fashionErrorMessage(error, '读取绑定信息失败'))
  } finally {
    if (seq === identitiesSeq) loadingIdentities.value = false
  }
}

async function handleApprove(): Promise<void> {
  if (approving.value) return
  const code = normalizedCode.value
  if (code.length !== 6) {
    ElMessage.warning('请输入 6 位绑定码')
    return
  }
  approving.value = true
  try {
    const { data } = await fashionApi.approveDevice(code)
    lastBound.value = data
    userCode.value = ''
    ElMessage.success(`绑定成功：${data.mcName}`)
    await loadIdentities()
  } catch (error) {
    ElMessage.error(fashionErrorMessage(error, '绑定失败，请确认绑定码是否正确/未过期'))
  } finally {
    approving.value = false
  }
}

async function handleUnbind(identity: FashionIdentity): Promise<void> {
  if (unbindingId.value) return
  try {
    await ElMessageBox.confirm(
      `确定解绑 ${identity.mcName}（${identity.mcUuid}）吗？解绑后网页将无法再管理该账号的穿戴。`,
      '解绑确认',
      { type: 'warning', confirmButtonText: '解绑', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  unbindingId.value = identity.id
  try {
    await fashionApi.unbind(identity.id)
    ElMessage.success('已解绑')
    await loadIdentities()
  } catch (error) {
    ElMessage.error(fashionErrorMessage(error, '解绑失败'))
  } finally {
    unbindingId.value = ''
  }
}

function goWardrobe(identityId: string): void {
  router.push({ path: '/fashion/wardrobe', query: { identityId } })
}

onMounted(loadIdentities)
</script>

<style scoped>
.fashion-bind-page {
  padding: var(--space-4);
  max-width: 1180px;
  margin: 0 auto;
}

.page-title {
  font-family: var(--font-display);
  font-size: 26px;
  color: var(--text-primary);
  margin: 0 0 var(--space-2);
}

.page-subtitle {
  color: var(--text-secondary);
  font-size: 13px;
  margin: 0 0 var(--space-5);
}

.bind-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

@media (max-width: 900px) {
  .bind-grid {
    grid-template-columns: 1fr;
  }
}

.bind-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-family: var(--font-display);
  font-size: 16px;
  color: var(--text-primary);
}

.card-body {
  min-height: 120px;
}

.panel-error {
  margin-bottom: var(--space-3);
}

.identity-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.identity-item {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  background: var(--bg-elevated);
}

.identity-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.mc-name {
  font-family: var(--font-display);
  font-size: 17px;
  color: var(--text-primary);
}

.identity-meta {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.7;
  word-break: break-all;
}

.identity-actions {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.code-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: var(--space-3) 0;
}

.code-input {
  flex: 1 1 160px;
  min-width: 0;
  max-width: 240px;
}

.code-input :deep(input) {
  font-family: var(--font-mono);
  font-size: 20px;
  letter-spacing: 4px;
  text-transform: uppercase;
}

.bound-alert {
  margin-bottom: var(--space-3);
}

.hint {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.8;
  margin: 0 0 var(--space-2);
}

.link {
  color: var(--text-primary);
  text-decoration: underline;
  text-decoration-color: var(--accent);
  text-underline-offset: 2px;
}

.explain-card {
  margin-top: var(--space-2);
}

.explain-list {
  margin: var(--space-2) 0 0;
  padding-left: 20px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.9;
}
</style>
