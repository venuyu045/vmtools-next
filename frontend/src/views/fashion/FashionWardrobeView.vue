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
          :disabled="saveDisabled"
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
            <div class="panel-tools">
              <el-input
                v-model="searchKeyword"
                size="small"
                clearable
                placeholder="搜索名称 / ID"
                aria-label="搜索时装名称或 ID"
                class="catalog-search"
              />
              <!-- B7：目录只在挂载时拉一次 → 管理员上新后玩家必须整页刷新。这里补一个刷新入口 -->
              <el-button
                size="small"
                text
                :loading="loadingCatalog"
                :disabled="loadingCatalog"
                @click="loadCatalog"
              >
                刷新
              </el-button>
            </div>
          </div>
          <el-radio-group
            v-model="activeCategory"
            size="small"
            class="catalog-filters"
            aria-label="按槽位筛选时装"
          >
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="slot in FASHION_SLOTS" :key="slot.value" :value="slot.value">
              {{ slot.label }}
            </el-radio-button>
          </el-radio-group>
        </template>

        <div v-loading="loadingCatalog" class="catalog-body" :aria-busy="loadingCatalog">
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
          <template v-else>
            <div class="catalog-grid" role="group" :aria-label="`时装目录，共 ${filteredCatalog.length} 件`">
              <div
                v-for="item in pagedCatalog"
                :key="item.cosmeticId"
                class="cosmetic-card"
                :class="{ equipped: isEquipped(item) }"
                role="button"
                tabindex="0"
                :aria-pressed="isEquipped(item)"
                :aria-label="`${displayName(item)}，${CATEGORY_LABELS[itemSlot(item)] || item.category}`"
                @click="equip(item)"
                @keydown.enter.prevent="equip(item)"
                @keydown.space.prevent="equip(item)"
              >
                <div class="cosmetic-thumb">
                  <img
                    v-if="previewUrls.has(item.cosmeticId) && !brokenThumbs.has(item.cosmeticId)"
                    :src="previewUrls.get(item.cosmeticId) || ''"
                    :alt="displayName(item)"
                    loading="lazy"
                    decoding="async"
                    @error="markThumbBroken(item.cosmeticId)"
                  />
                  <span v-else class="thumb-fallback">{{ (displayName(item) || '?').slice(0, 1) }}</span>
                </div>
                <div class="cosmetic-name" :title="displayName(item)">{{ displayName(item) }}</div>
                <div class="cosmetic-meta mono">
                  {{ CATEGORY_LABELS[itemSlot(item)] || item.category }}
                  <span v-if="isEquipped(item)" class="equipped-tag">已穿戴</span>
                  <span
                    v-else-if="item.assetKey && !previewUrls.has(item.cosmeticId)"
                    class="meta-tag"
                    title="该资产不是图片（glb / json / zip 等），网页衣柜无法预览"
                  >
                    无预览
                  </span>
                  <!-- B3：点卡片 = 立即穿戴，没有「先看大图/看元信息」的中间态 -->
                  <button
                    type="button"
                    class="detail-link"
                    :aria-label="`查看 ${displayName(item)} 的详情`"
                    @click.stop="openDetail(item)"
                    @keydown.enter.stop.prevent="openDetail(item)"
                    @keydown.space.stop.prevent="openDetail(item)"
                  >
                    详情
                  </button>
                </div>
              </div>
            </div>
            <!-- B2：一次渲染全部卡片，200 件时每张卡还要跑 4 次 isEquipped → 分页 -->
            <div v-if="filteredCatalog.length > pageSize" class="catalog-pager">
              <el-pagination
                layout="prev, pager, next"
                :total="filteredCatalog.length"
                :page-size="pageSize"
                :current-page="catalogPage"
                @current-change="catalogPage = $event"
              />
            </div>
          </template>
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
                  :min="MIN_SCALE"
                  :max="MAX_SCALE"
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
            <el-button type="primary" :loading="saving" :disabled="saveDisabled" @click="save">
              保存穿戴
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 详情弹窗（B3）：点卡片是「立即穿戴」，这里给一个先看大图/元信息的中间态 -->
    <el-dialog
      v-model="detailOpen"
      :title="detailItem ? displayName(detailItem) : '时装详情'"
      width="520px"
      class="detail-dialog"
    >
      <div v-if="detailItem" class="detail-body">
        <div class="detail-preview">
          <el-image
            v-if="detailUrl"
            :src="detailUrl"
            :preview-src-list="[detailUrl]"
            preview-teleported
            fit="contain"
            class="detail-image"
            :alt="displayName(detailItem)"
          />
          <span v-else class="detail-fallback">{{ (displayName(detailItem) || '?').slice(0, 1) }}</span>
        </div>
        <p v-if="!detailUrl" class="detail-hint mono">
          {{ detailItem.assetKey ? '该资产不是图片格式，网页无法预览。' : '这件时装还没有上传资产（assetKey 为空）。' }}
        </p>
        <el-descriptions :column="1" border size="small" class="detail-meta">
          <el-descriptions-item label="ID">
            <span class="mono">{{ detailItem.cosmeticId }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="槽位">{{ detailSlotLabel }}</el-descriptions-item>
          <el-descriptions-item label="时装包">
            <span class="mono">{{ detailItem.packId || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前缩放">
            <span class="mono">{{ detailScale.toFixed(2) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            {{ isEquipped(detailItem) ? '已穿戴（保存后生效）' : '未穿戴' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer>
        <el-button @click="detailOpen = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!detailItem || isEquipped(detailItem)"
          @click="equipFromDetail"
        >
          {{ detailItem ? `穿戴到${detailSlotLabel}` : '穿戴' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
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
const router = useRouter()

// 缩放区间：与后端 core/fashion_service.py:54-55 的 0.25 / 4.0 对齐
const MIN_SCALE = 0.25
const MAX_SCALE = 4
/** 合法槽位集合：用于过滤后端返回的历史脏数据（未知 slot 会让保存整条 400） */
const validSlots = new Set<string>(FASHION_SLOTS.map((slot) => slot.value))

const identities = ref<FashionIdentity[]>([])
const activeIdentityId = ref('')
const catalog = ref<CatalogItem[]>([])
// 预览图加载失败（目录条目填了 assetKey 但资产还没上传 / 文件被删）的时装：
// 退回首字占位，避免整面目录都是破图图标
const brokenThumbs = ref<Set<string>>(new Set())
const activeCategory = ref('all')
// B1：目录 200+ 件时只能靠肉眼扫 → 加搜索（名称 / ID，大小写不敏感）
const searchKeyword = ref('')
// B2：一次渲染全部卡片（每张卡还要跑 4 次 isEquipped）→ 分页，一页 60 张
const catalogPage = ref(1)
const pageSize = 60
// B3：详情弹窗（大图 + 元信息）
const detailOpen = ref(false)
const detailItem = ref<CatalogItem | null>(null)
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
// 身份失效自愈：正在重拉身份列表时不再嵌套触发，避免 404/403 循环
let identityRecovering = false

/**
 * 把当前生效的身份写回 URL（?identityId=）。
 *
 * 为什么需要：绑定页「去衣柜」会带上 identityId，但用户在下拉框里换了身份后
 * URL 仍是旧值 —— 此时刷新 / 收藏 / 分享都会回到另一个身份，看到的穿戴也不是
 * 刚才那一份。用 replace 而不是 push：切身份不该在浏览器历史里堆记录，
 * 否则用户按「后退」会莫名其妙切回上一个身份。
 */
function syncIdentityQuery(): void {
  const current = typeof route.query.identityId === 'string' ? route.query.identityId : ''
  const next = activeIdentityId.value
  if (current === next) return
  const query = { ...route.query }
  if (next) query.identityId = next
  else delete query.identityId
  void router.replace({ query })
}

/** 切换身份前确认是否丢弃未保存修改；返回 true 表示可以继续 */
async function confirmDiscardChanges(): Promise<boolean> {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm(
      '切换 Minecraft 身份会丢弃当前未保存的穿戴修改，是否继续？',
      '切换身份',
      { type: 'warning', confirmButtonText: '切换', cancelButtonText: '取消' }
    )
    return true
  } catch {
    return false
  }
}

/**
 * 身份在别处被解绑 / 转绑（后端 404 identity_not_found、403 forbidden）时自愈。
 *
 * 为什么需要：衣柜页的身份列表只在挂载时拉一次。若用户另一个标签页里解绑了
 * 这个 MC 账号，本页的「重试」会拿着同一个失效 identityId 反复失败，除了手动
 * 刷新页面没有任何出路 —— 等于把用户卡死在错误态。
 *
 * @returns 是否已回落到有效身份并重新读到穿戴配置
 */
async function recoverIdentity(staleId: string): Promise<boolean> {
  if (identityRecovering || !staleId) return false
  identityRecovering = true
  try {
    await loadIdentities()
    if (identitiesError.value || noIdentity.value) return false
    // loadIdentities 只在原身份不存在时才会改 activeIdentityId；没变说明不是身份问题
    if (!activeIdentityId.value || activeIdentityId.value === staleId) return false
    syncIdentityQuery()
    await loadLoadout()
    return true
  } finally {
    identityRecovering = false
  }
}

const currentIdentity = computed(
  () => identities.value.find((item) => item.id === activeIdentityId.value) || null
)

/**
 * 全局 ID 的 localId（`pack:local` → `local`；没有冒号时原样返回）。
 *
 * 为什么需要：后端把 loadout 统一存成全局 ID（`<packId>:<localId>`），而目录里可能还有
 * 历史「简单 ID」条目（只有 localId）。两种形态指同一件时装，UI 匹配必须兼容。
 */
function localIdOf(cosmeticId: string): string {
  const idx = cosmeticId.indexOf(':')
  return idx > 0 && idx < cosmeticId.length - 1 ? cosmeticId.slice(idx + 1) : cosmeticId
}

/**
 * 两个 ID 是否指同一件时装。
 *
 * 只有「一个全局 + 一个简单、且 localId 相同」才视为同一件；两个不同的全局 ID
 * （不同包的同名 localId）或两个不同的简单 ID 都不算 —— 避免串包误高亮。
 */
function sameCosmetic(a: string, b: string): boolean {
  if (a === b) return true
  const aGlobal = a.includes(':')
  const bGlobal = b.includes(':')
  if (aGlobal === bGlobal) return false
  return localIdOf(a) === localIdOf(b)
}

const catalogMap = computed(() => {
  const map = new Map<string, CatalogItem>()
  for (const item of catalog.value) {
    map.set(item.cosmeticId, item)
    // 全局 ID 再登记一个 localId 别名，供 loadout（可能存简单 ID）反查名称
    const local = localIdOf(item.cosmeticId)
    if (local !== item.cosmeticId && !map.has(local)) map.set(local, item)
  }
  return map
})

/**
 * 卡片/弹窗显示名：`name` 为空时回落 `cosmeticId`（B6）。
 * 后端 `name` 默认是空串，直接渲染会得到一张空白卡片。
 */
function displayName(item: CatalogItem): string {
  return (item.name || '').trim() || item.cosmeticId
}

const filteredCatalog = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return catalog.value.filter((item) => {
    if (activeCategory.value !== 'all' && itemSlot(item) !== activeCategory.value) return false
    if (!keyword) return true
    return (
      displayName(item).toLowerCase().includes(keyword) ||
      item.cosmeticId.toLowerCase().includes(keyword)
    )
  })
})

const pagedCatalog = computed(() => {
  const start = (catalogPage.value - 1) * pageSize
  return filteredCatalog.value.slice(start, start + pageSize)
})

// 搜索 / 切分类后回到第一页，否则可能停在一个空页上
watch([searchKeyword, activeCategory], () => {
  catalogPage.value = 1
})

/** 缩放夹紧（B9）：后端两条写路径都会夹，但载入时也夹一次，避免「值 99 / 滑块卡在 4」 */
function clampScale(value: unknown): number {
  const num = Number(value)
  if (!Number.isFinite(num)) return 1
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, num))
}

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

const emptyCatalogText = computed(() => {
  const keyword = searchKeyword.value.trim()
  if (keyword) return `没有匹配「${keyword}」的时装`
  return activeCategory.value === 'all'
    ? '目录里还没有可用的时装（站点管理员可在「时装管理」里导入）'
    : '该分类下暂无可用时装'
})

const equippedCount = computed(() => Object.keys(selection.value).length)

function snapshot(): string {
  const ordered: Record<string, { cosmeticId: string; scale: number }> = {}
  for (const key of Object.keys(selection.value).sort()) {
    ordered[key] = { ...selection.value[key] }
  }
  return JSON.stringify(ordered)
}

const dirty = computed(() => snapshot() !== savedSnapshot.value)

/**
 * 两处「保存穿戴」按钮共用一个 disabled 条件（B8）。
 * 原来顶部按钮含 `noIdentity / identitiesError`、底部按钮不含，是「两处真理」；
 * 现在虽然被 `v-else` 挡住不可达，但一旦布局改动就会漏。
 */
const saveDisabled = computed(
  () =>
    !dirty.value ||
    noIdentity.value ||
    identitiesError.value ||
    loadingIdentities.value ||
    loadingLoadout.value ||
    loadoutError.value ||
    saving.value
)

// ── 详情弹窗 ──
const detailUrl = computed(() => {
  const item = detailItem.value
  if (!item) return ''
  return previewUrls.value.get(item.cosmeticId) || ''
})

const detailSlotLabel = computed(() => {
  const item = detailItem.value
  if (!item) return ''
  return CATEGORY_LABELS[itemSlot(item)] || item.category || '其它'
})

const detailScale = computed(() => {
  const item = detailItem.value
  if (!item) return 1
  return selection.value[itemSlot(item)]?.scale ?? 1
})

function openDetail(item: CatalogItem): void {
  detailItem.value = item
  detailOpen.value = true
}

function equipFromDetail(): void {
  const item = detailItem.value
  if (!item) return
  equip(item)
  detailOpen.value = false
}

/** 目录分类归一化：大小写/非法分类归入合法槽位，避免写入后端不认的槽位 */
function itemSlot(item: CatalogItem): string {
  const category = String(item.category || 'other').trim().toLowerCase()
  return FASHION_SLOTS.some((slot) => slot.value === category) ? category : 'other'
}

function isEquipped(item: CatalogItem): boolean {
  const selected = selection.value[itemSlot(item)]
  return !!selected && sameCosmetic(selected.cosmeticId, item.cosmeticId)
}

/** 预览图 404 / 解码失败：记下来并退回首字占位（后端 asset_not_found 是合法返回） */
function markThumbBroken(cosmeticId: string): void {
  if (brokenThumbs.value.has(cosmeticId)) return
  const next = new Set(brokenThumbs.value)
  next.add(cosmeticId)
  brokenThumbs.value = next
}

function cosmeticName(slot: string): string {
  const selected = selection.value[slot]
  if (!selected) return ''
  // 先精确、再按 localId 兜底（catalog 简单 ID ↔ loadout 全局 ID 的历史数据）
  const item =
    catalogMap.value.get(selected.cosmeticId) ||
    catalogMap.value.get(localIdOf(selected.cosmeticId))
  if (item) return displayName(item)
  return missingSlots.value.has(slot) ? `${selected.cosmeticId}（已下架）` : selected.cosmeticId
}

function slotSelection(slot: string) {
  return selection.value[slot]
}

function slotScale(slot: string): number {
  return selection.value[slot]?.scale ?? 1
}

/** 槽位内容一换，它就不再是「已下架」条目：必须清掉标记 */
function clearMissingSlot(slot: string): void {
  if (!missingSlots.value.has(slot)) return
  const next = new Set(missingSlots.value)
  next.delete(slot)
  missingSlots.value = next
}

function equip(item: CatalogItem): void {
  const slot = itemSlot(item)
  const existing = selection.value[slot]
  selection.value = {
    ...selection.value,
    [slot]: { cosmeticId: item.cosmeticId, scale: existing?.scale ?? 1 },
  }
  // 目录里点得到的时装一定没下架。不清标记的话，保存时 save() 会把这件
  // 刚选好的时装当成「已下架」自动移除（只留一句误导性的警告），
  // 用户以为换装成功、进游戏却是旧的。
  clearMissingSlot(slot)
}

function unequip(slot: string): void {
  const next = { ...selection.value }
  delete next[slot]
  selection.value = next
  clearMissingSlot(slot)
}

function setScale(slot: string, value: number | number[]): void {
  const current = selection.value[slot]
  if (!current) return
  const raw = Array.isArray(value) ? value[0] : value
  const scale = clampScale(raw)
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
    // URL 里的 identityId 已失效（例如该 MC 账号刚被解绑）：改写成实际生效的身份，
    // 否则地址栏一直挂着一个后端不认的身份，刷新/分享出去都还要再回落一次
    if (queryId && queryId !== activeIdentityId.value) syncIdentityQuery()
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
    // B4（真 bug）：brokenThumbs 原来一旦标记就永不重置 —— 管理员补传资产后，
    // 玩家必须硬刷新才看得到缩略图。目录重新拉成功 = 资产可能已经补齐，全部重试一次。
    brokenThumbs.value = new Set()
    // 目录变短（下架）时把页码夹回有效范围，避免停在空页
    const maxPage = Math.max(1, Math.ceil(filteredCatalog.value.length / pageSize))
    if (catalogPage.value > maxPage) catalogPage.value = maxPage
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
      // B10：未知 slot 不可见但会计入 equippedCount、并在保存时回传 ——
      // 后端 put_loadout 对未知 slot 是**整条 400 失败**，所以载入时直接丢弃。
      if (!validSlots.has(item.slot)) continue
      // B9：载入时夹紧 scale（后端两条写路径都夹，这里再兜一层，避免手改 DB 后自相矛盾）
      next[item.slot] = { cosmeticId: item.cosmeticId, scale: clampScale(item.scale ?? 1) }
      if (item.missing) missing.add(item.slot)
    }
    selection.value = next
    missingSlots.value = missing
    savedSnapshot.value = snapshot()
  } catch (error) {
    if (seq !== loadoutSeq) return
    const code = fashionErrorCode(error)
    if (code === 'no_identity') {
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
    // 身份已失效（别处解绑 / 被转绑）：先回落到有效身份再读一次，
    // 否则「重试」会一直用同一个失效 identityId 失败，用户只能手动刷新页面
    if ((code === 'identity_not_found' || code === 'forbidden') && identityId) {
      if (await recoverIdentity(identityId)) {
        ElMessage.info('该 Minecraft 身份已失效，已自动切换到当前账号下的有效身份')
        return
      }
    }
    ElMessage.error(fashionErrorMessage(error, '读取穿戴配置失败'))
  } finally {
    if (seq === loadoutSeq) loadingLoadout.value = false
  }
}

async function onIdentityChange(): Promise<void> {
  if (!(await confirmDiscardChanges())) {
    activeIdentityId.value = previousIdentityId
    return
  }
  previousIdentityId = activeIdentityId.value
  // 下拉框换身份后同步 URL：刷新/收藏/分享都停在这一个身份上
  syncIdentityQuery()
  await loadLoadout()
}

// URL 里的 identityId 变化时反向同步下拉框与穿戴数据，避免「地址栏是 A、页面是 B」：
// 侧边栏「我的衣柜」是不带 query 的链接，浏览器前进/后退也可能落到别的 identityId 上。
watch(
  () => route.query.identityId,
  async (raw) => {
    const next = typeof raw === 'string' ? raw : ''
    if (!next) {
      // query 被清掉（例如点了侧边栏同名链接）：保留当前身份，把 URL 补回去
      syncIdentityQuery()
      return
    }
    if (next === activeIdentityId.value) return
    // 未知 / 无权访问的身份：切过去后端只会 403/404，忽略并把 URL 改回当前身份
    if (!identities.value.some((item) => item.id === next)) {
      syncIdentityQuery()
      return
    }
    // 保存中不允许换身份：保存成功的快照会记到另一个身份头上
    if (saving.value) {
      syncIdentityQuery()
      return
    }
    if (!(await confirmDiscardChanges())) {
      syncIdentityQuery()
      return
    }
    activeIdentityId.value = next
    previousIdentityId = next
    await loadLoadout()
  }
)

async function save(): Promise<void> {
  // 穿戴配置没加载成功时绝不允许保存：全量覆盖会把云端其它槽位清空
  if (saving.value || loadingIdentities.value || loadingLoadout.value || loadoutError.value) return
  // 已下架/已删除的时装提交上去也只会被后端跳过（warnings 里列出来），
  // 用户没动过的失效槽位在保存前先移除，免得每次保存都弹一串「未同步」
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
    const code = fashionErrorCode(error)
    if (code === 'no_identity') {
      noIdentity.value = true
      ElMessage.warning('请先在「时装绑定」页完成绑定')
      return
    }
    // 身份已失效（别处解绑 / 被转绑）：回落到有效身份，别让用户对着必然失败的
    // 保存按钮反复点。回落后会重读穿戴配置，本地未保存的修改随之作废 —— 必须说清楚。
    if ((code === 'identity_not_found' || code === 'forbidden') && identityId) {
      if (await recoverIdentity(identityId)) {
        ElMessage.warning('该 Minecraft 身份已失效，已自动切换身份，请确认穿戴后重新保存')
        return
      }
    }
    ElMessage.error(fashionErrorMessage(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  // 同步注册（放在 await 之前）：若初始化期间用户就离开了本页，onUnmounted 已经跑过，
  // 之后再 addEventListener 会留下一个永不释放的监听器（还会按旧状态弹刷新确认）
  window.addEventListener('beforeunload', onBeforeUnload)
  await loadIdentities()
  await Promise.all([loadCatalog(), identitiesError.value ? Promise.resolve() : loadLoadout()])
  applyStoreDeepLink()
})

/**
 * 「时装商店」的「去穿戴」深链：`/fashion/wardrobe?cosmeticId=xxx`。
 *
 * 只做定位提示（打开详情弹窗），**不强制穿戴** —— 用户仍可在目录里改选、调缩放，
 * 也不该因为从商店点进来就悄悄改掉他的穿戴。
 * 处理完把 query 删掉：否则刷新 / 前进后退都会再弹一次，且地址栏会挂着一个
 * 与当前状态无关的参数。
 */
function applyStoreDeepLink(): void {
  const cosmeticId = typeof route.query.cosmeticId === 'string' ? route.query.cosmeticId : ''
  if (!cosmeticId) return
  const item = catalogMap.value.get(cosmeticId) || catalogMap.value.get(localIdOf(cosmeticId))
  if (item) openDetail(item)
  else ElMessage.warning('商店里选中的时装已下架，可在目录里重新挑选')
  const query = { ...route.query }
  delete query.cosmeticId
  void router.replace({ query })
}

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

.panel-tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.catalog-search {
  width: 200px;
  max-width: 100%;
}

/* 分类按钮在窄屏必须换行，否则横向溢出卡片 */
.catalog-filters {
  display: flex;
  flex-wrap: wrap;
  row-gap: var(--space-2);
  margin-top: var(--space-3);
}

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

.meta-tag {
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  padding: 0 4px;
  border-radius: 4px;
}

/* 卡片内的「详情」按钮：用原生 button 以免多一层 el-button 的盒模型开销 */
.detail-link {
  margin-left: auto;
  background: none;
  border: none;
  padding: 0 2px;
  font: inherit;
  color: var(--text-secondary);
  text-decoration: underline;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 2px;
  cursor: pointer;
}

.detail-link:hover {
  color: var(--accent);
  text-decoration-color: var(--accent);
}

.detail-link:focus-visible {
  outline: 2px solid var(--accent-active);
  outline-offset: 1px;
  border-radius: 2px;
}

.catalog-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-3);
}

/* 详情弹窗 */
.detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.detail-preview {
  height: 200px;
  border-radius: var(--radius-md);
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.detail-image {
  max-width: 100%;
  max-height: 200px;
  cursor: zoom-in;
}

.detail-fallback {
  font-family: var(--font-display);
  font-size: 56px;
  color: var(--text-secondary);
}

.detail-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.7;
}

.detail-meta :deep(.el-descriptions__label) {
  width: 96px;
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
  /* B13：320px 下「提示 + 按钮」会挤成一行放不下 */
  flex-wrap: wrap;
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
}

.save-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
