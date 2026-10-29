<template>
  <div class="wardrobe-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">我的衣柜</h2>
        <p class="page-subtitle mono">
          选好每个槽位的时装后保存 · 游戏内 mod 会按 UUID 自动拉取同一份配置
        </p>
      </div>
      <div class="head-actions">
        <el-select
          v-if="identities.length > 1"
          v-model="activeIdentityId"
          size="small"
          class="identity-select"
          aria-label="选择 Minecraft 身份"
          :disabled="saving"
          @change="onIdentityChange"
        >
          <el-option
            v-for="identity in identities"
            :key="identity.id"
            :label="`${identity.mcName}（${identity.mcUuid.slice(0, 8)}…）`"
            :value="identity.id"
          />
        </el-select>
        <span v-else-if="currentIdentity" class="identity-chip mono">
          {{ currentIdentity.mcName }} · {{ currentIdentity.authType === 'mojang' ? '正版' : '皮肤站' }}
        </span>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!dirty || noIdentity || identitiesError || loadingIdentities || loadingLoadout || loadoutError"
          @click="save"
        >
          保存穿戴
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="identitiesError"
      type="error"
      show-icon
      :closable="false"
      class="no-identity-alert"
      title="读取 Minecraft 身份失败"
    >
      <template #default>
        <el-button size="small" text type="primary" @click="reloadIdentities">重试</el-button>
      </template>
    </el-alert>

    <el-alert
      v-else-if="noIdentity"
      type="warning"
      show-icon
      :closable="false"
      class="no-identity-alert"
      title="当前账号还没有绑定 Minecraft 身份"
    >
      <template #default>
        请先到
        <router-link class="link" to="/fashion/bind">时装绑定</router-link>
        页输入 mod 显示的 6 位绑定码。
      </template>
    </el-alert>

    <div v-else v-loading="loadingIdentities" class="wardrobe-grid">
      <!-- 左：目录 -->
      <el-card shadow="never" class="panel">
        <template #header>
          <div class="panel-header">
            <span class="panel-title">时装目录</span>
            <el-radio-group v-model="activeCategory" size="small" aria-label="按槽位筛选时装">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button v-for="slot in FASHION_SLOTS" :key="slot.value" :value="slot.value">
                {{ slot.label }}
              </el-radio-button>
            </el-radio-group>
          </div>
        </template>

        <div v-loading="loadingCatalog" class="catalog-body">
          <el-alert
            v-if="catalogError"
            class="panel-error"
            type="error"
            :closable="false"
            show-icon
            title="时装目录加载失败"
          >
            <template #default>
              <el-button size="small" text type="primary" @click="loadCatalog">重试</el-button>
            </template>
          </el-alert>
          <el-empty
            v-else-if="filteredCatalog.length === 0"
            :description="emptyCatalogText"
            :image-size="72"
          />
          <div v-else class="catalog-grid">
            <div
              v-for="item in filteredCatalog"
              :key="item.cosmeticId"
              class="cosmetic-card"
              :class="{ equipped: isEquipped(item) }"
              role="button"
              tabindex="0"
              :aria-pressed="isEquipped(item)"
              :aria-label="`${item.name || item.cosmeticId}，${CATEGORY_LABELS[itemSlot(item)] || item.category}`"
              @click="equip(item)"
              @keydown.enter.prevent="equip(item)"
              @keydown.space.prevent="equip(item)"
            >
              <div class="cosmetic-thumb">
                <img
                  v-if="previewUrls.has(item.cosmeticId)"
                  :src="previewUrls.get(item.cosmeticId) || ''"
                  :alt="item.name || '时装预览'"
                  loading="lazy"
                  decoding="async"
                />
                <span v-else class="thumb-fallback">{{ (item.name || '?').slice(0, 1) }}</span>
              </div>
              <div class="cosmetic-name" :title="item.name">{{ item.name }}</div>
              <div class="cosmetic-meta mono">
                {{ CATEGORY_LABELS[itemSlot(item)] || item.category }}
                <span v-if="isEquipped(item)" class="equipped-tag">已穿戴</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 右：穿戴 -->
      <el-card shadow="never" class="panel">
        <template #header>
          <div class="panel-header">
            <span class="panel-title">当前穿戴</span>
            <span class="mono count-hint">{{ equippedCount }} 个槽位</span>
          </div>
        </template>

        <div v-loading="loadingLoadout" class="loadout-body">
          <el-alert
            v-if="loadoutError"
            class="panel-error"
            type="error"
            :closable="false"
            show-icon
            title="穿戴配置加载失败"
          >
            <template #default>
              <el-button size="small" text type="primary" @click="loadLoadout">重试</el-button>
            </template>
          </el-alert>
          <div v-for="slot in FASHION_SLOTS" :key="slot.value" class="slot-row">
            <div class="slot-head">
              <span class="slot-label">{{ slot.label }}</span>
              <el-button
                v-if="slotSelection(slot.value)"
                size="small"
                text
                type="danger"
                :aria-label="`卸下${slot.label}`"
                @click="unequip(slot.value)"
              >
                卸下
              </el-button>
            </div>

            <template v-if="slotSelection(slot.value)">
              <div class="slot-cosmetic">{{ cosmeticName(slot.value) }}</div>
              <div class="scale-row">
                <span class="mono scale-label">缩放</span>
                <el-slider
                  :model-value="slotScale(slot.value)"
                  :aria-label="`${slot.label}缩放`"
                  :min="0.25"
                  :max="4"
                  :step="0.05"
                  size="small"
                  class="scale-slider"
                  @input="(value: number | number[]) => setScale(slot.value, value)"
                />
                <span class="mono scale-value">{{ slotScale(slot.value).toFixed(2) }}</span>
              </div>
            </template>
            <div v-else class="slot-empty mono">未穿戴</div>
          </div>

          <div class="save-row">
            <span class="mono save-hint" role="status" aria-live="polite">
              {{ loadingLoadout ? '正在读取穿戴配置…' : dirty ? '有未保存的修改' : '已与服务器同步' }}
            </span>
            <el-button type="primary" :loading="saving" :disabled="!dirty || loadingIdentities || loadingLoadout || loadoutError" @click="save">
              保存穿戴
            </el-button>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CATEGORY_LABELS,
  FASHION_SLOTS,
  fashionApi,
  fashionErrorCode,
  fashionErrorMessage,
  type CatalogItem,
  type FashionIdentity,
} from '@/api/fashion'

const route = useRoute()

const identities = ref<FashionIdentity[]>([])
const activeIdentityId = ref('')
const catalog = ref<CatalogItem[]>([])
const activeCategory = ref('all')
const selection = ref<Record<string, { cosmeticId: string; scale: number }>>({})
const missingSlots = ref<Set<string>>(new Set())
const savedSnapshot = ref('{}')
const loadingCatalog = ref(false)
const loadingLoadout = ref(false)
const loadingIdentities = ref(false)
const saving = ref(false)
const noIdentity = ref(false)
const identitiesError = ref(false)
const catalogError = ref(false)
const loadoutError = ref(false)

// 请求竞态保护：切换身份时旧响应不得覆盖新身份的数据
let loadoutSeq = 0
// 身份列表请求竞态保护：重试期间只采纳最后一次响应
let identitiesSeq = 0
// 目录请求竞态保护：连点重试时只采纳最后一次响应
let catalogSeq = 0
// 记住切换前的身份，用于用户取消「放弃未保存修改」时回退下拉框
let previousIdentityId = ''

const currentIdentity = computed(
  () => identities.value.find((item) => item.id === activeIdentityId.value) || null
)

const catalogMap = computed(() => {
  const map = new Map<string, CatalogItem>()
  for (const item of catalog.value) map.set(item.cosmeticId, item)
  return map
})

const filteredCatalog = computed(() =>
  activeCategory.value === 'all'
    ? catalog.value
    : catalog.value.filter((item) => itemSlot(item) === activeCategory.value)
)

// 预览图地址只算一次，模板里用 Map 取值（避免 v-if 与 :src 各自重复计算）
const previewUrls = computed(() => {
  const map = new Map<string, string>()
  for (const item of catalog.value) {
    if (!item.assetKey) continue
    if (!/\.(png|jpe?g|webp|gif)$/i.test(item.assetKey)) continue
    map.set(item.cosmeticId, fashionApi.assetUrl(item.assetKey))
  }
  return map
})

const emptyCatalogText = computed(() =>
  activeCategory.value === 'all'
    ? '目录里还没有可用的时装（管理员可在后台导入）'
    : '该分类下暂无可用时装'
)

const equippedCount = computed(() => Object.keys(selection.value).length)

function snapshot(): string {
  const ordered: Record<string, { cosmeticId: string; scale: number }> = {}
  for (const key of Object.keys(selection.value).sort()) {
    ordered[key] = { ...selection.value[key] }
  }
  return JSON.stringify(ordered)
}

const dirty = computed(() => snapshot() !== savedSnapshot.value)

/** 目录分类归一化：大小写/非法分类归入合法槽位，避免写入后端不认的槽位 */
function itemSlot(item: CatalogItem): string {
  const category = String(item.category || 'other').trim().toLowerCase()
  return FASHION_SLOTS.some((slot) => slot.value === category) ? category : 'other'
}

function isEquipped(item: CatalogItem): boolean {
  return selection.value[itemSlot(item)]?.cosmeticId === item.cosmeticId
}

function cosmeticName(slot: string): string {
  const selected = selection.value[slot]
  if (!selected) return ''
  const name = catalogMap.value.get(selected.cosmeticId)?.name
  if (name) return name
  return missingSlots.value.has(slot) ? `${selected.cosmeticId}（已下架）` : selected.cosmeticId
}

function slotSelection(slot: string) {
  return selection.value[slot]
}

function slotScale(slot: string): number {
  return selection.value[slot]?.scale ?? 1
}

function equip(item: CatalogItem): void {
  const slot = itemSlot(item)
  const existing = selection.value[slot]
  selection.value = {
    ...selection.value,
    [slot]: { cosmeticId: item.cosmeticId, scale: existing?.scale ?? 1 },
  }
}

function unequip(slot: string): void {
  const next = { ...selection.value }
  delete next[slot]
  selection.value = next
}

function setScale(slot: string, value: number | number[]): void {
  const current = selection.value[slot]
  if (!current) return
  const raw = Array.isArray(value) ? value[0] : value
  const scale = Math.min(4, Math.max(0.25, Number(raw) || 1))
  selection.value = { ...selection.value, [slot]: { ...current, scale } }
}

async function loadIdentities(): Promise<void> {
  const seq = ++identitiesSeq
  loadingIdentities.value = true
  identitiesError.value = false
  try {
    const { data } = await fashionApi.myIdentities()
    if (seq !== identitiesSeq) return // 已被更新的请求取代，丢弃本次响应
    identities.value = data.items || []
    const queryId = typeof route.query.identityId === 'string' ? route.query.identityId : ''
    const activeStillExists = identities.value.some((item) => item.id === activeIdentityId.value)
    if (!activeStillExists) {
      // 原身份已被解绑/删除时回落到 query 指定或第一个，避免拿失效 identityId 请求
      const preferred =
        queryId && identities.value.some((item) => item.id === queryId)
          ? queryId
          : identities.value[0]?.id || ''
      activeIdentityId.value = preferred
    }
    previousIdentityId = activeIdentityId.value
    noIdentity.value = identities.value.length === 0
  } catch (error) {
    if (seq !== identitiesSeq) return
    identitiesError.value = true
    ElMessage.error(fashionErrorMessage(error, '读取绑定信息失败'))
  } finally {
    if (seq === identitiesSeq) loadingIdentities.value = false
  }
}

async function reloadIdentities(): Promise<void> {
  await loadIdentities()
  if (!identitiesError.value) await loadLoadout()
}

async function loadCatalog(): Promise<void> {
  const seq = ++catalogSeq
  loadingCatalog.value = true
  catalogError.value = false
  try {
    const { data } = await fashionApi.catalog()
    if (seq !== catalogSeq) return // 已被更新的请求取代，丢弃本次响应
    catalog.value = data.items || []
  } catch (error) {
    if (seq !== catalogSeq) return
    catalogError.value = true
    ElMessage.error(fashionErrorMessage(error, '读取时装目录失败'))
  } finally {
    if (seq === catalogSeq) loadingCatalog.value = false
  }
}

async function loadLoadout(): Promise<void> {
  const seq = ++loadoutSeq
  loadoutError.value = false
  if (noIdentity.value) {
    loadingLoadout.value = false
    selection.value = {}
    missingSlots.value = new Set()
    savedSnapshot.value = snapshot()
    return
  }
  loadingLoadout.value = true
  const identityId = activeIdentityId.value || undefined
  try {
    const { data } = await fashionApi.getLoadout(identityId)
    if (seq !== loadoutSeq) return // 已被更新的请求取代，丢弃本次响应
    const next: Record<string, { cosmeticId: string; scale: number }> = {}
    const missing = new Set<string>()
    for (const item of data.items || []) {
      next[item.slot] = { cosmeticId: item.cosmeticId, scale: item.scale ?? 1 }
      if (item.missing) missing.add(item.slot)
    }
    selection.value = next
    missingSlots.value = missing
    savedSnapshot.value = snapshot()
  } catch (error) {
    if (seq !== loadoutSeq) return
    if (fashionErrorCode(error) === 'no_identity') {
      noIdentity.value = true
      selection.value = {}
      missingSlots.value = new Set()
      savedSnapshot.value = snapshot()
      return
    }
    loadoutError.value = true
    // 加载失败时清空选择，避免旧身份的穿戴被误存到当前身份
    selection.value = {}
    missingSlots.value = new Set()
    savedSnapshot.value = snapshot()
    ElMessage.error(fashionErrorMessage(error, '读取穿戴配置失败'))
  } finally {
    if (seq === loadoutSeq) loadingLoadout.value = false
  }
}

async function onIdentityChange(): Promise<void> {
  if (dirty.value) {
    try {
      await ElMessageBox.confirm(
        '切换 Minecraft 身份会丢弃当前未保存的穿戴修改，是否继续？',
        '切换身份',
        { type: 'warning', confirmButtonText: '切换', cancelButtonText: '取消' }
      )
    } catch {
      activeIdentityId.value = previousIdentityId
      return
    }
  }
  previousIdentityId = activeIdentityId.value
  await loadLoadout()
}

async function save(): Promise<void> {
  // 穿戴配置没加载成功时绝不允许保存：全量覆盖会把云端其它槽位清空
  if (saving.value || loadingIdentities.value || loadingLoadout.value || loadoutError.value) return
  // 已下架/已删除的时装不能提交（后端会 404/409 导致整次保存失败），保存前自动移除
  const missingToDrop = Object.keys(selection.value).filter((slot) => missingSlots.value.has(slot))
  if (missingToDrop.length > 0) {
    const next = { ...selection.value }
    for (const slot of missingToDrop) delete next[slot]
    selection.value = next
    const remaining = new Set(missingSlots.value)
    for (const slot of missingToDrop) remaining.delete(slot)
    missingSlots.value = remaining
    ElMessage.warning(`已自动移除 ${missingToDrop.length} 件已下架时装`)
  }
  const identityId = activeIdentityId.value || undefined
  // 记录点击保存时的快照：请求期间用户继续改动的部分仍应保持「未保存」
  const snapshotAtSave = snapshot()
  saving.value = true
  try {
    const items = Object.entries(selection.value).map(([slot, value]) => ({
      slot,
      cosmeticId: value.cosmeticId,
      scale: value.scale,
    }))
    const { data } = await fashionApi.putLoadout(items, identityId)
    if ((activeIdentityId.value || undefined) !== identityId) return
    savedSnapshot.value = snapshotAtSave
    // 后端会跳过目录里不存在的条目（例如本地包里的时装），只保存其余槽位：
    // 这里必须把"被跳过"告诉用户，否则他会以为全部保存成功了。
    const skipped = data.warnings || []
    if (skipped.length > 0) {
      ElMessage.warning(
        `已保存其余槽位；${skipped.length} 件时装不在站点目录里，未同步：` +
          skipped.map((item) => item.cosmeticId).join('、')
      )
    } else {
      ElMessage.success('已保存，进入服务器后生效')
    }
  } catch (error) {
    if (fashionErrorCode(error) === 'no_identity') {
      noIdentity.value = true
      ElMessage.warning('请先在「时装绑定」页完成绑定')
      return
    }
    ElMessage.error(fashionErrorMessage(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadIdentities()
  await Promise.all([loadCatalog(), identitiesError.value ? Promise.resolve() : loadLoadout()])
  window.addEventListener('beforeunload', onBeforeUnload)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
})

/**
 * 有未保存修改时，刷新/关标签页先弹浏览器原生确认。
 *
 * 为什么需要：衣柜是「本地改 → 点保存才提交」的模型，直接刷新会把整页修改丢掉，
 * 而用户往往以为已经生效（页面上确实显示着新时装）。路由内跳转由
 * onBeforeRouteLeave 拦，浏览器级刷新/关闭只能靠 beforeunload。
 */
function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value || saving.value) return
  event.preventDefault()
  // 部分浏览器（旧版 Chrome / Safari）仍要求设置 returnValue 才会弹确认框
  event.returnValue = ''
}

// 路由内跳转（点侧边栏去别的页面）同样要拦住未保存的修改
onBeforeRouteLeave(async () => {
  if (!dirty.value || saving.value) return true
  try {
    await ElMessageBox.confirm(
      '当前穿戴还有未保存的修改，离开后这些修改会丢失，确定离开吗？',
      '未保存的修改',
      { type: 'warning', confirmButtonText: '离开', cancelButtonText: '留在此页' }
    )
    return true
  } catch {
    return false
  }
})
</script>

<style scoped>
.wardrobe-page {
  padding: var(--space-4);
  max-width: 1320px;
  margin: 0 auto;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
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
  margin: 0;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.identity-select {
  width: 220px;
  max-width: 100%;
}

.identity-chip {
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--bg-elevated);
}

.no-identity-alert {
  margin-bottom: var(--space-4);
}

.link {
  color: var(--text-primary);
  text-decoration: underline;
  text-decoration-color: var(--accent);
  text-underline-offset: 2px;
}

.wardrobe-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr);
  gap: var(--space-4);
}

@media (max-width: 1000px) {
  .wardrobe-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

/* 8 个槽位按钮在窄屏必须换行，否则横向溢出卡片 */
.panel-header :deep(.el-radio-group) {
  flex-wrap: wrap;
  row-gap: var(--space-2);
}

.panel-title {
  font-family: var(--font-display);
  font-size: 16px;
  color: var(--text-primary);
}

.count-hint {
  color: var(--text-secondary);
  font-size: 12px;
}

.panel-error {
  margin-bottom: var(--space-3);
}

.catalog-body,
.loadout-body {
  min-height: 200px;
}

.catalog-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: var(--space-3);
}

.cosmetic-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  padding: var(--space-2);
  cursor: pointer;
  transition: border-color 150ms var(--ease-out), transform 150ms var(--ease-out);
}

.cosmetic-card:hover {
  border-color: var(--accent-active);
  transform: translateY(-2px);
}

.cosmetic-card:focus-visible {
  outline: 2px solid var(--accent-active);
  outline-offset: 2px;
  border-color: var(--accent-active);
}

.cosmetic-card.equipped {
  border-color: var(--accent-active);
  box-shadow: 0 0 0 1px var(--accent-ring, var(--accent-active)) inset;
}

.cosmetic-thumb {
  height: 84px;
  border-radius: var(--radius-md);
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  margin-bottom: var(--space-2);
}

.cosmetic-thumb img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.thumb-fallback {
  font-family: var(--font-display);
  font-size: 28px;
  color: var(--text-secondary);
}

.cosmetic-name {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cosmetic-meta {
  font-size: 11px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.equipped-tag {
  color: var(--text-primary);
  background: var(--accent-soft);
  padding: 0 4px;
  border-radius: 4px;
}

.slot-row {
  border-bottom: 1px dashed var(--border-subtle);
  padding: var(--space-3) 0;
}

.slot-row:last-of-type {
  border-bottom: none;
}

.slot-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.slot-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.slot-cosmetic {
  font-size: 14px;
  color: var(--text-primary);
  margin: 2px 0 var(--space-2);
}

.slot-empty {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 0;
}

.scale-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.scale-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.scale-slider {
  flex: 1;
}

.scale-value {
  font-size: 11px;
  color: var(--text-secondary);
  width: 36px;
  text-align: right;
}

.save-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.save-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
