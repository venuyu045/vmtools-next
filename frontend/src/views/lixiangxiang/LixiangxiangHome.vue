<template>
  <div class="lx-home">
    <LXHeader :member-count="members.length" />

    <main>
      <div v-if="loadError" class="lx-load-error" role="alert">
        官网数据加载失败，请稍后刷新重试。
      </div>
      <LXIntroSection :info="info" :member-count="members.length" :base-count="bases.length" />
      <LXMembersSection :members="members" />
      <LXBaseSection :bases="bases" />
      <LXGallerySection :categories="categories" :images="images" />
    </main>

    <!-- 管理员快捷入口（仅已登录管理员可见） -->
    <router-link v-if="isAdmin" to="/lixiangxiang/admin" class="lx-admin-entry" title="后台管理">
      后台管理
    </router-link>

    <LXFooter />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { lxPublicApi } from '@/api/lixiangxiang'
import type { LxInfo, LxMember, LxBase, LxCategory, LxImage } from '@/api/lixiangxiang'
import { useAuthStore } from '@/stores/auth'
import LXHeader from '@/components/lixiangxiang/LXHeader.vue'
import LXIntroSection from '@/components/lixiangxiang/LXIntroSection.vue'
import LXMembersSection from '@/components/lixiangxiang/LXMembersSection.vue'
import LXBaseSection from '@/components/lixiangxiang/LXBaseSection.vue'
import LXGallerySection from '@/components/lixiangxiang/LXGallerySection.vue'
import LXFooter from '@/components/lixiangxiang/LXFooter.vue'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const info = ref<LxInfo | null>(null)
const members = ref<LxMember[]>([])
const bases = ref<LxBase[]>([])
const categories = ref<LxCategory[]>([])
const images = ref<LxImage[]>([])
const loadError = ref(false)

onMounted(async () => {
  try {
    const [infoRes, membersRes, basesRes, catsRes, imgsRes] = await Promise.all([
      lxPublicApi.info(),
      lxPublicApi.members(),
      lxPublicApi.bases(),
      lxPublicApi.categories(),
      lxPublicApi.images(),
    ])
    info.value = infoRes.data
    members.value = membersRes.data
    bases.value = basesRes.data
    categories.value = catsRes.data
    images.value = imgsRes.data
  } catch {
    loadError.value = true
  }
})
</script>

<style scoped>
/* ================= 拓荒测绘志 Token 层（仅官网，不影响 /dashboard） =================
   主题语汇：地图纸底 + 墨线 + 图钉橙/红 + 测绘蓝绿；"暖米"成为地图纸材质而非默认底色 */
.lx-home {
  /* ---- 亮色：地图纸 ---- */
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
  /* 测绘语汇辅助色 */
  --lx-pin: #C0503C;      /* 图钉红：坐标标记 */
  --lx-blue: #6A7A8C;     /* 测绘蓝：等高线/数据 */
  --lx-moss: #7C8B7E;     /* 苔绿：地形统计 */
  --lx-grid-line: rgba(43, 38, 32, 0.05);
}

/* 暗色：夜航测绘纸 */
html[data-theme="dark"] .lx-home {
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
  --lx-grid-line: rgba(237, 230, 217, 0.05);
}

/* ================= 纸感背景（坐标网格 + 极细噪点） ================= */
.lx-home {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  background-color: var(--bg-page);
  color: var(--text-primary);
  /* 坐标纸网格 + 细纸纹噪点（测绘图纸质感） */
  background-image:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48'%3E%3Cpath d='M48 0H0V48' fill='none' stroke='%232B2620' stroke-opacity='0.045'/%3E%3C/svg%3E"),
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
  background-attachment: fixed;
}

html[data-theme="dark"] .lx-home {
  background-image:
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48'%3E%3Cpath d='M48 0H0V48' fill='none' stroke='%23EDE6D9' stroke-opacity='0.045'/%3E%3C/svg%3E"),
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
}

.lx-home::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  /* 极淡暖橙晕，模拟图纸受光 */
  background: radial-gradient(ellipse 80% 50% at 85% -10%, var(--accent-soft), transparent 60%);
}

.lx-home > * {
  position: relative;
  z-index: 1;
}

.lx-load-error {
  max-width: 1120px;
  margin: 24px auto 0;
  padding: 13px 20px;
  border-radius: 8px;
  background: var(--danger-bg);
  border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
  color: var(--danger);
  font-family: var(--font-sans);
  font-size: 14px;
  text-align: center;
}

/* 管理员后台入口（固定右下角，方形小圆角） */
.lx-admin-entry {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 90;
  padding: 9px 18px;
  border-radius: 7px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.3px;
  text-decoration: none;
  box-shadow: var(--shadow-md);
  transition: all 200ms var(--ease-out);
}

.lx-admin-entry:hover {
  border-color: var(--accent);
  color: var(--accent);
  transform: translateY(-2px);
}

@media (max-width: 768px) {
  .lx-admin-entry {
    right: 14px;
    bottom: 14px;
    padding: 8px 14px;
    font-size: 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lx-admin-entry { transition: none; }
}
</style>