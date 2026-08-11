<template>
  <div class="lx-admin">
    <header class="lx-admin-header">
      <div class="lx-admin-header-inner">
        <router-link to="/lixiangxiang" class="lx-admin-back">← 返回官网</router-link>
        <div class="lx-admin-title-wrap">
          <h1 class="lx-admin-title">理想乡 · 后台</h1>
          <p class="lx-admin-sub">{{ authStore.user?.game_id || '未知' }} · {{ roleLabel(authStore.user?.role) }}</p>
        </div>
        <router-link to="/dashboard" class="lx-admin-console">控制台 →</router-link>
      </div>
    </header>

    <main class="lx-admin-main">
      <!-- 权限兜底：路由守卫已拦截，这里双保险 -->
      <el-result v-if="!isAdmin" icon="warning" title="无权访问" sub-title="仅管理员可进入后台管理">
        <template #extra>
          <el-button type="primary" @click="$router.push('/lixiangxiang')">返回官网</el-button>
        </template>
      </el-result>

      <template v-else>
        <el-tabs v-model="activeTab" class="lx-admin-tabs">
          <!-- ============ 1. 组织介绍 ============ -->
          <el-tab-pane label="组织介绍" name="info">
            <div class="lx-pane">
              <el-form :model="infoForm" label-position="top" class="lx-form">
                <el-form-item label="标语（首页大标题下方）">
                  <el-input v-model="infoForm.slogan" placeholder="例如：方块之间，是家与远方" maxlength="60" show-word-limit />
                </el-form-item>
                <el-form-item label="组织介绍（支持 **加粗** 与换行）">
                  <el-input v-model="infoForm.intro" type="textarea" :rows="8" placeholder="组织设定、宗旨…" />
                </el-form-item>
                <el-form-item label="发展历程（每行一条）">
                  <el-input v-model="infoForm.history" type="textarea" :rows="8" placeholder="2023 年 1 月 · 理想乡开服…" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" :loading="savingInfo" @click="saveInfo">保存组织介绍</el-button>
                </el-form-item>
              </el-form>
            </div>
          </el-tab-pane>

          <!-- ============ 2. 成员管理 ============ -->
          <el-tab-pane label="成员管理" name="members">
            <div class="lx-pane">
              <div class="lx-pane-toolbar">
                <span class="lx-pane-count">共 {{ members.length }} 位成员</span>
                <el-button type="primary" @click="openMemberDialog()">新增成员</el-button>
              </div>
              <el-table :data="members" size="small" class="lx-table" :header-cell-style="headerCellStyle" :cell-style="cellStyle">
                <el-table-column label="头像" width="70">
                  <template #default="{ row }">
                    <el-avatar :size="34" :src="row.avatar_path || undefined" shape="square" :style="{ borderRadius: '8px' }">
                      {{ (row.nickname || row.game_id).slice(0, 1) }}
                    </el-avatar>
                  </template>
                </el-table-column>
                <el-table-column prop="nickname" label="昵称" min-width="90" />
                <el-table-column prop="game_id" label="游戏 ID" min-width="120" />
                <el-table-column prop="title" label="职位/称号" min-width="110" />
                <el-table-column prop="joined_at" label="加入时间" width="100" />
                <el-table-column prop="specialty" label="擅长领域" min-width="130" show-overflow-tooltip />
                <el-table-column label="操作" width="140" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click="openMemberDialog(row)">编辑</el-button>
                    <el-button size="small" text type="danger" @click="removeMember(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>

          <!-- ============ 3. 基地管理 ============ -->
          <el-tab-pane label="基地管理" name="bases">
            <div class="lx-pane">
              <div class="lx-pane-toolbar">
                <span class="lx-pane-count">共 {{ bases.length }} 个基地</span>
                <el-button type="primary" @click="openBaseDialog()">新增基地</el-button>
              </div>
              <el-table :data="bases" size="small" class="lx-table" :header-cell-style="headerCellStyle" :cell-style="cellStyle">
                <el-table-column label="截图" width="110">
                  <template #default="{ row }">
                    <el-image v-if="row.image_path" :src="row.image_path" fit="cover" class="lx-thumb" :preview-src-list="[row.image_path]" preview-teleported />
                    <span v-else class="lx-thumb-empty">无</span>
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="基地名称" min-width="150" />
                <el-table-column prop="description" label="介绍" min-width="220" show-overflow-tooltip />
                <el-table-column prop="coordinates" label="坐标" width="140" />
                <el-table-column label="操作" width="140" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click="openBaseDialog(row)">编辑</el-button>
                    <el-button size="small" text type="danger" @click="removeBase(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>

          <!-- ============ 4. 相册管理 ============ -->
          <el-tab-pane label="相册管理" name="gallery">
            <div class="lx-pane">
              <div class="lx-pane-toolbar">
                <span class="lx-pane-count">共 {{ images.length }} 张图片 · {{ categories.length }} 个分类</span>
                <el-button @click="openCategoryDialog()">新增分类</el-button>
                <el-button type="primary" @click="openImageDialog()">上传图片</el-button>
              </div>

              <!-- 分类列表 -->
              <div class="lx-cat-list">
                <div v-for="c in categories" :key="c.id" class="lx-cat-chip">
                  <span class="lx-cat-name">{{ c.name }}</span>
                  <span class="lx-cat-count">{{ c.image_count ?? 0 }}</span>
                  <el-button size="small" text type="primary" @click="openCategoryDialog(c)">编辑</el-button>
                  <el-button size="small" text type="danger" @click="removeCategory(c)">删除</el-button>
                </div>
              </div>

              <!-- 图片列表 -->
              <el-table :data="images" size="small" class="lx-table" :header-cell-style="headerCellStyle" :cell-style="cellStyle">
                <el-table-column label="预览" width="110">
                  <template #default="{ row }">
                    <el-image v-if="row.image_path" :src="row.image_path" fit="cover" class="lx-thumb" :preview-src-list="[row.image_path]" preview-teleported />
                  </template>
                </el-table-column>
                <el-table-column prop="title" label="标题" min-width="140" />
                <el-table-column label="分类" width="120">
                  <template #default="{ row }">
                    <span>{{ categoryName(row.category_id) }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
                <el-table-column label="操作" width="180" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click="openImageDialog(row)">编辑</el-button>
                    <el-button size="small" text type="danger" @click="removeImage(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </main>

    <!-- ============ 成员弹窗 ============ -->
    <el-dialog v-model="memberDialog.visible" :title="memberDialog.isEdit ? '编辑成员' : '新增成员'" width="560px" destroy-on-close class="lx-dialog">
      <el-form :model="memberDialog.form" label-width="88px" class="lx-dialog-form">
        <el-form-item label="头像">
          <div class="lx-upload-row">
            <el-avatar :size="52" :src="memberDialog.form.avatar_path || undefined" shape="square" :style="{ borderRadius: '10px' }">
              {{ (memberDialog.form.nickname || memberDialog.form.game_id || '?').slice(0, 1) }}
            </el-avatar>
            <el-upload
              :show-file-list="false"
              accept="image/*"
              :http-request="(opt: any) => uploadAvatar(opt)"
            >
              <el-button size="small">上传头像</el-button>
            </el-upload>
            <el-button v-if="memberDialog.form.avatar_path" size="small" text type="danger" @click="memberDialog.form.avatar_path = ''">清除</el-button>
          </div>
        </el-form-item>
        <el-form-item label="游戏 ID" required>
          <el-input v-model="memberDialog.form.game_id" placeholder="MC 游戏 ID" />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="memberDialog.form.nickname" placeholder="展示昵称（可选）" />
        </el-form-item>
        <el-form-item label="职位/称号">
          <el-input v-model="memberDialog.form.title" placeholder="如：建筑师 / 管理员" />
        </el-form-item>
        <el-form-item label="加入时间">
          <el-input v-model="memberDialog.form.joined_at" placeholder="如：2023-06" />
        </el-form-item>
        <el-form-item label="擅长领域">
          <el-input v-model="memberDialog.form.specialty" placeholder="如：红石机械 / 大型建筑" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="memberDialog.form.bio" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="memberDialog.form.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="memberDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="memberDialog.saving" @click="saveMember">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 基地弹窗 ============ -->
    <el-dialog v-model="baseDialog.visible" :title="baseDialog.isEdit ? '编辑基地' : '新增基地'" width="560px" destroy-on-close class="lx-dialog">
      <el-form :model="baseDialog.form" label-width="88px" class="lx-dialog-form">
        <el-form-item label="基地截图">
          <div class="lx-upload-row">
            <el-image v-if="baseDialog.form.image_path" :src="baseDialog.form.image_path" fit="cover" class="lx-upload-preview" />
            <el-upload
              :show-file-list="false"
              accept="image/*"
              :http-request="(opt: any) => uploadBaseImage(opt)"
            >
              <el-button size="small">上传截图</el-button>
            </el-upload>
            <el-button v-if="baseDialog.form.image_path" size="small" text type="danger" @click="baseDialog.form.image_path = ''">清除</el-button>
          </div>
        </el-form-item>
        <el-form-item label="基地名称" required>
          <el-input v-model="baseDialog.form.name" placeholder="如：主城 · 风起之地" />
        </el-form-item>
        <el-form-item label="介绍">
          <el-input v-model="baseDialog.form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="坐标">
          <el-input v-model="baseDialog.form.coordinates" placeholder="如：-2673, 57, 9627" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="baseDialog.form.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="baseDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="baseDialog.saving" @click="saveBase">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 分类弹窗 ============ -->
    <el-dialog v-model="categoryDialog.visible" :title="categoryDialog.isEdit ? '编辑分类' : '新增分类'" width="420px" destroy-on-close class="lx-dialog">
      <el-form :model="categoryDialog.form" label-width="72px" class="lx-dialog-form">
        <el-form-item label="分类名" required>
          <el-input v-model="categoryDialog.form.name" placeholder="如：建筑风景" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="categoryDialog.form.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="categoryDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="categoryDialog.saving" @click="saveCategory">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 图片弹窗 ============ -->
    <el-dialog v-model="imageDialog.visible" :title="imageDialog.isEdit ? '编辑图片' : '上传图片'" width="560px" destroy-on-close class="lx-dialog">
      <el-form :model="imageDialog.form" label-width="72px" class="lx-dialog-form">
        <el-form-item label="图片">
          <div class="lx-upload-row">
            <el-image v-if="imageDialog.form.image_path" :src="imageDialog.form.image_path" fit="cover" class="lx-upload-preview" />
            <el-upload
              :show-file-list="false"
              accept="image/*"
              :http-request="(opt: any) => uploadGalleryImage(opt)"
            >
              <el-button size="small">{{ imageDialog.isEdit ? '更换图片' : '选择图片' }}</el-button>
            </el-upload>
          </div>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="imageDialog.form.category_id" clearable placeholder="未分类" style="width: 100%">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="imageDialog.form.title" placeholder="图片标题" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="imageDialog.form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="imageDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="imageDialog.saving" @click="saveImage">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { lxAdminApi, lxPublicApi } from '@/api/lixiangxiang'
import type { LxInfo, LxMember, LxBase, LxCategory, LxImage } from '@/api/lixiangxiang'
import { useAuthStore, roleLabel } from '@/stores/auth'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const activeTab = ref('info')

/** el-table 表头/单元格统一样式（去 EP 默认蓝） */
function headerCellStyle() {
  return {
    background: 'var(--bg-card)',
    color: 'var(--text-secondary)',
    fontWeight: 600,
    fontFamily: 'var(--font-sans)',
    fontSize: '12.5px',
    letterSpacing: '0.5px',
    borderBottom: '1px solid var(--border-subtle)',
  }
}

function cellStyle() {
  return { borderBottom: '1px solid var(--border-subtle)', background: 'transparent' }
}

// ────────────────────── 数据 ──────────────────────
const infoForm = reactive({ slogan: '', intro: '', history: '' })
const members = ref<LxMember[]>([])
const bases = ref<LxBase[]>([])
const categories = ref<LxCategory[]>([])
const images = ref<LxImage[]>([])

const savingInfo = ref(false)

async function loadAll() {
  try {
    const [infoRes, membersRes, basesRes, catsRes, imgsRes] = await Promise.all([
      lxPublicApi.info(),
      lxPublicApi.members(),
      lxPublicApi.bases(),
      lxPublicApi.categories(),
      lxPublicApi.images(),
    ])
    const info = infoRes.data as LxInfo
    infoForm.slogan = info.slogan || ''
    infoForm.intro = info.intro || ''
    infoForm.history = info.history || ''
    members.value = membersRes.data
    bases.value = basesRes.data
    categories.value = catsRes.data
    images.value = imgsRes.data
  } catch {
    ElMessage.error('数据加载失败')
  }
}

onMounted(() => {
  if (isAdmin.value) loadAll()
})

// ────────────────────── 组织介绍 ──────────────────────
async function saveInfo() {
  savingInfo.value = true
  try {
    await lxAdminApi.updateInfo({
      slogan: infoForm.slogan,
      intro: infoForm.intro,
      history: infoForm.history,
    })
    ElMessage.success('组织介绍已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingInfo.value = false
  }
}

// ────────────────────── 通用上传 ──────────────────────
/** 上传文件并回调设置 URL */
async function uploadAndSet(file: File, setUrl: (url: string) => void) {
  try {
    const url = await lxAdminApi.upload(file)
    setUrl(url)
    ElMessage.success('上传成功')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  }
}

/** 成员头像上传 */
function uploadAvatar(opt: { file: File }) {
  return uploadAndSet(opt.file, (url) => { memberDialog.form.avatar_path = url })
}

/** 基地截图上传 */
function uploadBaseImage(opt: { file: File }) {
  return uploadAndSet(opt.file, (url) => { baseDialog.form.image_path = url })
}

/** 相册图片上传 */
function uploadGalleryImage(opt: { file: File }) {
  return uploadAndSet(opt.file, (url) => { imageDialog.form.image_path = url })
}

// ────────────────────── 成员管理 ──────────────────────
const memberDialog = reactive({
  visible: false,
  isEdit: false,
  saving: false,
  form: {} as Omit<LxMember, 'id'>,
})

function openMemberDialog(row?: LxMember) {
  memberDialog.isEdit = !!row
  memberDialog.form = row
    ? { ...row }
    : { game_id: '', nickname: '', title: '', joined_at: '', specialty: '', avatar_path: '', bio: '', sort_order: members.value.length }
  memberDialog.visible = true
}

async function saveMember() {
  if (!memberDialog.form.game_id?.trim()) {
    ElMessage.warning('请填写游戏 ID')
    return
  }
  memberDialog.saving = true
  try {
    if (memberDialog.isEdit) {
      await lxAdminApi.updateMember((memberDialog.form as LxMember).id, memberDialog.form)
    } else {
      await lxAdminApi.createMember(memberDialog.form)
    }
    ElMessage.success('成员已保存')
    memberDialog.visible = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    memberDialog.saving = false
  }
}

async function removeMember(row: LxMember) {
  try {
    await ElMessageBox.confirm(`确认删除成员「${row.nickname || row.game_id}」？`, '删除确认', { type: 'warning' })
  } catch { return } // 用户取消
  await lxAdminApi.deleteMember(row.id)
  ElMessage.success('已删除')
  await loadAll()
}

// ────────────────────── 基地管理 ──────────────────────
const baseDialog = reactive({
  visible: false,
  isEdit: false,
  saving: false,
  form: {} as Omit<LxBase, 'id'>,
})

function openBaseDialog(row?: LxBase) {
  baseDialog.isEdit = !!row
  baseDialog.form = row
    ? { ...row }
    : { name: '', description: '', image_path: '', coordinates: '', sort_order: bases.value.length }
  baseDialog.visible = true
}

async function saveBase() {
  if (!baseDialog.form.name?.trim()) {
    ElMessage.warning('请填写基地名称')
    return
  }
  baseDialog.saving = true
  try {
    if (baseDialog.isEdit) {
      await lxAdminApi.updateBase((baseDialog.form as LxBase).id, baseDialog.form)
    } else {
      await lxAdminApi.createBase(baseDialog.form)
    }
    ElMessage.success('基地已保存')
    baseDialog.visible = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    baseDialog.saving = false
  }
}

async function removeBase(row: LxBase) {
  try {
    await ElMessageBox.confirm(`确认删除基地「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch { return } // 用户取消
  await lxAdminApi.deleteBase(row.id)
  ElMessage.success('已删除')
  await loadAll()
}

// ────────────────────── 分类管理 ──────────────────────
const categoryDialog = reactive({
  visible: false,
  isEdit: false,
  saving: false,
  form: { id: '' as string, name: '', sort_order: 0 },
})

function openCategoryDialog(row?: LxCategory) {
  categoryDialog.isEdit = !!row
  categoryDialog.form = row
    ? { id: row.id, name: row.name, sort_order: row.sort_order }
    : { id: '', name: '', sort_order: categories.value.length }
  categoryDialog.visible = true
}

async function saveCategory() {
  if (!categoryDialog.form.name?.trim()) {
    ElMessage.warning('请填写分类名')
    return
  }
  categoryDialog.saving = true
  try {
    if (categoryDialog.isEdit) {
      await lxAdminApi.updateCategory(categoryDialog.form.id, { name: categoryDialog.form.name, sort_order: categoryDialog.form.sort_order })
    } else {
      await lxAdminApi.createCategory({ name: categoryDialog.form.name, sort_order: categoryDialog.form.sort_order })
    }
    ElMessage.success('分类已保存')
    categoryDialog.visible = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    categoryDialog.saving = false
  }
}

async function removeCategory(row: LxCategory) {
  try {
    await ElMessageBox.confirm(`确认删除分类「${row.name}」？其下图片将变为未分类（不删除图片）。`, '删除确认', { type: 'warning' })
  } catch { return } // 用户取消
  await lxAdminApi.deleteCategory(row.id)
  ElMessage.success('已删除')
  await loadAll()
}

// ────────────────────── 图片管理 ──────────────────────
const imageDialog = reactive({
  visible: false,
  isEdit: false,
  saving: false,
  form: {} as Omit<LxImage, 'id' | 'uploaded_at'>,
})

function openImageDialog(row?: LxImage) {
  imageDialog.isEdit = !!row
  imageDialog.form = row
    ? { image_path: row.image_path, category_id: row.category_id, title: row.title, description: row.description }
    : { image_path: '', category_id: null, title: '', description: '' }
  imageDialog.visible = true
}

async function saveImage() {
  if (!imageDialog.form.image_path) {
    ElMessage.warning('请先上传图片')
    return
  }
  imageDialog.saving = true
  try {
    if (imageDialog.isEdit) {
      await lxAdminApi.updateImage((imageDialog.form as LxImage).id, imageDialog.form)
    } else {
      await lxAdminApi.createImage(imageDialog.form)
    }
    ElMessage.success('图片已保存')
    imageDialog.visible = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    imageDialog.saving = false
  }
}

async function removeImage(row: LxImage) {
  try {
    await ElMessageBox.confirm(`确认删除图片「${row.title || '未命名'}」？`, '删除确认', { type: 'warning' })
  } catch { return } // 用户取消
  await lxAdminApi.deleteImage(row.id)
  ElMessage.success('已删除')
  await loadAll()
}

function categoryName(id: string | null): string {
  if (!id) return '未分类'
  return categories.value.find(c => c.id === id)?.name || '未分类'
}
</script>

<style scoped>
/* ================= 拓荒测绘志 Token 层（后台页独立，与官网一致） ================= */
.lx-admin {
  --bg-page: #F1ECE1;
  --bg-card: #F7F4EC;
  --bg-elevated: #FBF8F1;
  --bg-hover: rgba(43, 38, 32, 0.05);
  --bg-active: rgba(43, 38, 32, 0.08);
  --text-primary: #2B2620;
  --text-secondary: #5E574D;
  --text-muted: #8B8277;
  --text-disabled: #B4AC9F;
  --accent: #D97757;
  --accent-hover: #C86645;
  --accent-active: #B85C38;
  --accent-soft: rgba(217, 119, 87, 0.10);
  --accent-ring: rgba(217, 119, 87, 0.35);
  --border-subtle: #DCD4C4;
  --border-default: #CCC2AE;
  --border-strong: #A99E89;
  --lx-pin: #C0503C;
  --lx-blue: #6A7A8C;
  --lx-moss: #7C8B7E;
}

html[data-theme="dark"] .lx-admin {
  --bg-page: #1B1915;
  --bg-card: #232019;
  --bg-elevated: #2C2820;
  --bg-hover: rgba(237, 230, 217, 0.05);
  --bg-active: rgba(237, 230, 217, 0.09);
  --text-primary: #EDE6D9;
  --text-secondary: #A49B8C;
  --text-muted: #857C6E;
  --text-disabled: #615A4E;
  --accent: #E08A6C;
  --accent-hover: #E69A7F;
  --accent-active: #ECAB93;
  --accent-soft: rgba(224, 138, 108, 0.14);
  --accent-ring: rgba(224, 138, 108, 0.45);
  --border-subtle: #302C24;
  --border-default: #3D382E;
  --border-strong: #514A3C;
  --lx-pin: #D96A55;
  --lx-blue: #7E90A2;
  --lx-moss: #8FA08F;
}

.lx-admin {
  min-height: 100vh;
  min-height: 100dvh;
  background-color: var(--bg-page);
  color: var(--text-primary);
  background-image:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48'%3E%3Cpath d='M48 0H0V48' fill='none' stroke='%232B2620' stroke-opacity='0.045'/%3E%3C/svg%3E"),
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
  background-attachment: fixed;
}

html[data-theme="dark"] .lx-admin {
  background-image:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48'%3E%3Cpath d='M48 0H0V48' fill='none' stroke='%23EDE6D9' stroke-opacity='0.045'/%3E%3C/svg%3E"),
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
}

/* ================= Header ================= */
.lx-admin-header {
  border-bottom: 1px dashed var(--border-default);
  background: color-mix(in srgb, var(--bg-card) 86%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 50;
}

.lx-admin-header-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 18px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.lx-admin-back,
.lx-admin-console {
  font-family: var(--font-sans);
  font-size: 13.5px;
  letter-spacing: 0.3px;
  color: var(--accent);
  text-decoration: none;
  white-space: nowrap;
  transition: color 200ms var(--ease-out);
}

.lx-admin-back:hover,
.lx-admin-console:hover {
  color: var(--accent-hover);
}

.lx-admin-title {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 400;
  color: var(--text-primary);
  margin: 0 0 3px;
  letter-spacing: 2px;
}

.lx-admin-sub {
  font-family: var(--font-sans);
  font-size: 12.5px;
  color: var(--text-muted);
  margin: 0;
}

/* ================= Main ================= */
.lx-admin-main {
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 24px 80px;
}

/* ================= EP 深度定制（去默认蓝） ================= */
/* ---- Tabs ---- */
.lx-admin-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background-color: var(--border-subtle);
}

.lx-admin-tabs :deep(.el-tabs__item) {
  font-family: var(--font-sans);
  font-size: 14.5px;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  height: 44px;
  line-height: 44px;
  transition: color 200ms var(--ease-out);
}

.lx-admin-tabs :deep(.el-tabs__item:hover) {
  color: var(--accent);
}

.lx-admin-tabs :deep(.el-tabs__item.is-active) {
  color: var(--text-primary);
}

.lx-admin-tabs :deep(.el-tabs__active-bar) {
  background-color: var(--accent);
  height: 2px;
}

/* ---- Table ---- */
.lx-table {
  --el-table-border-color: var(--border-subtle);
  --el-table-header-bg-color: transparent;
  --el-table-row-hover-bg-color: var(--bg-hover);
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-text-color: var(--text-secondary);
  --el-table-text-color: var(--text-secondary);
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}

.lx-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.lx-table :deep(.el-button.is-text) {
  font-size: 13px;
}

/* ---- Buttons ---- */
.lx-pane :deep(.el-button--primary),
.lx-dialog-form :deep(.el-button--primary) {
  --el-button-bg-color: var(--accent);
  --el-button-border-color: var(--accent);
  --el-button-hover-bg-color: var(--accent-hover);
  --el-button-hover-border-color: var(--accent-hover);
  --el-button-active-bg-color: var(--accent-active);
  --el-button-active-border-color: var(--accent-active);
  border-radius: 7px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.lx-pane :deep(.el-button:not(.is-text):not(.el-button--primary)),
.lx-dialog-form :deep(.el-button:not(.is-text):not(.el-button--primary)) {
  border-radius: 7px;
  --el-button-border-color: var(--border-default);
  --el-button-text-color: var(--text-secondary);
  --el-button-hover-border-color: var(--accent);
  --el-button-hover-text-color: var(--accent);
  --el-button-hover-bg-color: var(--accent-soft);
}

/* ---- Dialog ---- */
.lx-dialog :deep(.el-dialog) {
  border-radius: 14px;
  background: var(--bg-elevated);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--border-subtle);
}

.lx-dialog :deep(.el-dialog__header) {
  padding: 22px 24px 12px;
  border-bottom: 1px dashed var(--border-default);
}

.lx-dialog :deep(.el-dialog__title) {
  font-family: var(--font-display);
  font-size: 18px;
  letter-spacing: 0.5px;
  color: var(--text-primary);
}

.lx-dialog :deep(.el-dialog__body) {
  padding: 22px 24px;
}

.lx-dialog :deep(.el-dialog__footer) {
  padding: 12px 24px 20px;
  border-top: 1px solid var(--border-subtle);
}

/* ---- Inputs / Selects / Textarea ---- */
.lx-dialog-form :deep(.el-input__wrapper),
.lx-dialog-form :deep(.el-textarea__inner),
.lx-form :deep(.el-input__wrapper),
.lx-form :deep(.el-textarea__inner) {
  border-radius: 7px;
  background: var(--bg-page);
  box-shadow: 0 0 0 1px var(--border-default) inset;
  transition: box-shadow 200ms var(--ease-out);
}

.lx-dialog-form :deep(.el-input__wrapper.is-focus),
.lx-dialog-form :deep(.el-textarea__inner:focus),
.lx-form :deep(.el-input__wrapper.is-focus),
.lx-form :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px var(--accent) inset;
}

.lx-dialog-form :deep(.el-input-number) {
  border-radius: 7px;
}

.lx-dialog-form :deep(.el-input-number .el-input__wrapper) {
  border-radius: 7px 0 0 7px;
}

/* ---- Upload ---- */
.lx-dialog-form :deep(.el-upload) {
  display: inline-flex;
}

.lx-dialog-form :deep(.el-upload .el-button) {
  border-radius: 7px;
}

/* ---- Form label ---- */
.lx-dialog-form :deep(.el-form-item__label) {
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-secondary);
  letter-spacing: 0.3px;
}

.lx-form :deep(.el-form-item__label) {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  letter-spacing: 0.3px;
}

/* ================= Panes ================= */
.lx-pane {
  padding: 20px 0;
}

.lx-pane-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding-bottom: 16px;
  border-bottom: 1px dashed var(--border-default);
}

.lx-pane-count {
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-muted);
  letter-spacing: 0.3px;
}

.lx-thumb {
  width: 72px;
  height: 44px;
  border-radius: 6px;
  display: block;
}

.lx-thumb-empty {
  color: var(--text-disabled);
  font-size: 12px;
}

/* 分类 chips（去胶囊化） */
.lx-cat-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 20px;
}

.lx-cat-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 7px;
  border: 1px solid var(--border-default);
  background: var(--bg-elevated);
  transition: border-color 200ms var(--ease-out);
}

.lx-cat-chip:hover {
  border-color: var(--accent);
}

.lx-cat-name {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.3px;
}

.lx-cat-count {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
  background: var(--bg-hover);
  border-radius: 5px;
  padding: 1px 7px;
}

/* 弹窗内上传 */
.lx-upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.lx-upload-preview {
  width: 120px;
  height: 72px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
}

/* ================= Responsive ================= */
@media (max-width: 768px) {
  .lx-admin-main {
    padding: 16px 12px 60px;
  }

  .lx-admin-header-inner {
    padding: 14px 16px;
  }
}
</style>