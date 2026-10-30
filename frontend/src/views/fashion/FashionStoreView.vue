<template>
  <div class="fashion-store-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">时装商店</h2>
        <p class="page-subtitle mono">
          浏览站点全部时装 · 挑中后到「我的衣柜」穿戴，游戏内 mod 会同步生效
        </p>
      </div>
      <div class="head-actions">
        <span class="stat-chip mono">{{ filteredCatalog.length }} 件</span>
        <el-button size="small" text :loading="loading" :disabled="loading" @click="loadCatalog">
          刷新
        </el-button>
        <el-button size="small" type="primary" plain @click="goWardrobe">去我的衣柜</el-button>
      </div>
    </div>

    <el-card shadow="never" class="store-card">
      <template #header>
        <div class="store-toolbar">
          <el-input
            v-model="keyword"
            size="small"
            clearable
            placeholder="搜索名称 / ID"
            aria-label="搜索时装名称或 ID"
            class="store-search"
          />
          <el-radio-group v-model="activeCategory" size="small" class="store-filters" aria-label="按槽位筛选时装">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="slot in FASHION_SLOTS" :key="slot.value" :value="slot.value">
              {{ slot.label }}
            </el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <div v-loading="loading" class="store-body" :aria-busy="loading">
        <el-alert
          v-if="loadError"
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

        <el-empty v-else-if="filteredCatalog.length === 0" :description="emptyText" :image-size="80" />

        <template v-else>
          <div class="store-grid" role="list" :aria-label="`时装商店，共 ${filteredCatalog.length} 件`">
            <article
              v-for="item in pagedCatalog"
              :key="item.cosmeticId"
              class="store-item"
              role="listitem"
            >
              <button
                type="button"
                class="item-thumb"
                :aria-label="`查看 ${displayName(item)} 详情`"
                @click="openDetail(item)"
              >
                <img
                  v-if="previewUrls.has(item.cosmeticId) && !brokenThumbs.has(item.cosmeticId)"
                  :src="previewUrls.get(item.cosmeticId) || ''"
                  :alt="displayName(item)"
                  loading="lazy"
                  decoding="async"
                  @error="markThumbBroken(item.cosmeticId)"
                />
                <span v-else class="thumb-fallback">{{ (displayName(item) || '?').slice(0, 1) }}</span>
              </button>
              <div class="item-info">
                <div class="item-name" :title="displayName(item)">{{ displayName(item) }}</div>
                <div class="item-meta mono">
                  <span class="slot-tag">{{ CATEGORY_LABELS[itemSlot(item)] || item.category }}</span>
                  <span v-if="item.packId" class="pack-tag" :title="`时装包：${item.packId}`">
                    {{ item.packId }}
                  </span>
                </div>
                <div class="item-actions">
                  <el-button size="small" text class="detail-btn" @click="openDetail(item)">详情</el-button>
                  <el-button size="small" text type="primary" class="equip-btn" @click="goWardrobe(item)">
                    去穿戴 →
                  </el-button>
                </div>
              </div>
            </article>
          </div>

          <div v-if="filteredCatalog.length > pageSize" class="store-pager">
            <el-pagination
              layout="prev, pager, next"
              :total="filteredCatalog.length"
              :page-size="pageSize"
              :current-page="page"
              @current-change="page = $event"
            />
          </div>
        </template>
      </div>
    </el-card>

    <!-- 详情弹窗：先看大图 / 元信息，再决定去衣柜穿戴 -->
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
          <el-descriptions-item label="槽位">
            {{ CATEGORY_LABELS[itemSlot(detailItem)] || detailItem.category || '其它' }}
          </el-descriptions-item>
          <el-descriptions-item label="时装包">
            <span class="mono">{{ detailItem.packId || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="资源大小">
            <span class="mono">{{ formatBytes(detailItem.bytes) }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer>
        <el-button @click="detailOpen = false">关闭</el-button>
        <el-button type="primary" @click="goWardrobe(detailItem || undefined)">去我的衣柜穿戴</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  CATEGORY_LABELS,
  FASHION_SLOTS,
  fashionApi,
  fashionErrorMessage,
  type CatalogItem,
} from '@/api/fashion'

const router = useRouter()

const catalog = ref<CatalogItem[]>([])
const keyword = ref('')
const activeCategory = ref('all')
const page = ref(1)
const pageSize = 48
const loading = ref(false)
const loadError = ref(false)
const brokenThumbs = ref<Set<string>>(new Set())

const detailOpen = ref(false)
const detailItem = ref<CatalogItem | null>(null)

// 目录请求竞态保护：连点刷新时只采纳最后一次响应
let catalogSeq = 0

/** 槽位归一化：后端历史脏数据（大小写 / 未知分类）统一落到 other */
function itemSlot(item: CatalogItem): string {
  const category = String(item.category || 'other').trim().toLowerCase()
  return FASHION_SLOTS.some((slot) => slot.value === category) ? category : 'other'
}

/** 显示名：name 为空时回落 cosmeticId，避免渲染成空白卡片 */
function displayName(item: CatalogItem): string {
  return (item.name || '').trim() || item.cosmeticId
}

function formatBytes(bytes: number): string {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value <= 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

const filteredCatalog = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return catalog.value.filter((item) => {
    if (activeCategory.value !== 'all' && itemSlot(item) !== activeCategory.value) return false
    if (!kw) return true
    return (
      displayName(item).toLowerCase().includes(kw) ||
      item.cosmeticId.toLowerCase().includes(kw)
    )
  })
})

const pagedCatalog = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredCatalog.value.slice(start, start + pageSize)
})

const emptyText = computed(() => {
  const kw = keyword.value.trim()
  if (kw) return `没有匹配「${kw}」的时装`
  return activeCategory.value === 'all'
    ? '目录里还没有时装（站点管理员可在「时装管理」里导入）'
    : '该分类下暂无时装'
})

// 预览图只接受图片扩展名；其余资产（glb/json/zip）无法在网页预览
const previewUrls = computed(() => {
  const map = new Map<string, string>()
  for (const item of catalog.value) {
    if (!item.assetKey) continue
    if (!/\.(png|jpe?g|webp|gif)$/i.test(item.assetKey)) continue
    map.set(item.cosmeticId, fashionApi.assetUrl(item.assetKey))
  }
  return map
})

const detailUrl = computed(() => {
  const item = detailItem.value
  if (!item) return ''
  return previewUrls.value.get(item.cosmeticId) || ''
})

// 搜索 / 切分类后回到第一页，否则可能停在一个空页上
watch([keyword, activeCategory], () => {
  page.value = 1
})

function markThumbBroken(cosmeticId: string): void {
  if (brokenThumbs.value.has(cosmeticId)) return
  const next = new Set(brokenThumbs.value)
  next.add(cosmeticId)
  brokenThumbs.value = next
}

function openDetail(item: CatalogItem): void {
  detailItem.value = item
  detailOpen.value = true
}

/**
 * 去衣柜穿戴。
 *
 * 带上 cosmeticId 让衣柜能定位到这一件（衣柜只把它当提示，不强制穿戴），
 * 用户仍可在衣柜里自由改选 / 调缩放。
 */
function goWardrobe(item?: CatalogItem): void {
  const query = item ? { cosmeticId: item.cosmeticId } : {}
  void router.push({ path: '/fashion/wardrobe', query })
}

async function loadCatalog(): Promise<void> {
  const seq = ++catalogSeq
  loading.value = true
  loadError.value = false
  try {
    const { data } = await fashionApi.catalog()
    if (seq !== catalogSeq) return
    catalog.value = data.items || []
    // 目录重拉成功 = 资产可能已补齐，全部缩略图重试一次
    brokenThumbs.value = new Set()
    const maxPage = Math.max(1, Math.ceil(filteredCatalog.value.length / pageSize))
    if (page.value > maxPage) page.value = maxPage
  } catch (error) {
    if (seq !== catalogSeq) return
    loadError.value = true
    ElMessage.error(fashionErrorMessage(error, '读取时装目录失败'))
  } finally {
    if (seq === catalogSeq) loading.value = false
  }
}

onMounted(loadCatalog)
</script>

<style scoped>
/* 与主站 / 衣柜页共用同一套 Token 与排版，保证「时装中心风格和主站一致」 */
.fashion-store-page {
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

.stat-chip {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--bg-elevated);
}

.store-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
}

.store-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.store-search {
  width: 220px;
  max-width: 100%;
}

.store-filters {
  display: flex;
  flex-wrap: wrap;
  row-gap: var(--space-2);
}

.store-toolbar :deep(.el-radio-group) {
  flex-wrap: wrap;
  row-gap: var(--space-2);
}

.store-body {
  min-height: 240px;
}

.panel-error {
  margin-bottom: var(--space-3);
}

.store-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: var(--space-3);
}

.store-item {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-elevated);
  padding: var(--space-2);
  transition: border-color 150ms var(--ease-out), transform 150ms var(--ease-out);
}

.store-item:hover {
  border-color: var(--accent-active);
  transform: translateY(-2px);
}

.item-thumb {
  height: 104px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  margin-bottom: var(--space-2);
  cursor: pointer;
  padding: 0;
}

.item-thumb:focus-visible {
  outline: 2px solid var(--accent-active);
  outline-offset: 2px;
}

.item-thumb img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.thumb-fallback {
  font-family: var(--font-display);
  font-size: 30px;
  color: var(--text-secondary);
}

.item-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  min-height: 18px;
}

.slot-tag {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
}

.pack-tag {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
}

.item-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  margin-top: auto;
  padding-top: 2px;
}

/* 卡片内两个动作都走文字按钮：12 张卡各一个实心主按钮会把整页压成一片橙色，
   与主站「卡片只给一处强调」的克制风格不符 */
.detail-btn {
  color: var(--text-secondary);
}

.detail-btn:hover {
  color: var(--text-primary);
}

.equip-btn {
  padding: 0 4px;
  /* global.css 用 !important 把 el-button--primary 的文字统一压成深色，
     这里要「文字链接」观感，必须同等优先级地改回强调色 */
  color: var(--accent) !important;
}

.equip-btn:hover {
  color: var(--accent-hover) !important;
}

.store-pager {
  display: flex;
  justify-content: center;
  margin-top: var(--space-4);
}

/* ---- 详情弹窗 ---- */
.detail-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.detail-preview {
  height: 220px;
  border-radius: var(--radius-md);
  background: var(--bg-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.detail-image {
  max-width: 100%;
  max-height: 100%;
}

.detail-fallback {
  font-family: var(--font-display);
  font-size: 56px;
  color: var(--text-secondary);
}

.detail-hint {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}

.detail-meta {
  margin-top: var(--space-2);
}

@media (max-width: 768px) {
  .fashion-store-page {
    padding: var(--space-2);
  }

  .page-title {
    font-size: 22px;
  }

  .store-search {
    width: 100%;
  }

  .store-grid {
    grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  }

  .item-thumb {
    height: 88px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .store-item { transition: none; }
  .store-item:hover { transform: none; }
}
</style>
