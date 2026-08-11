<template>
  <div class="lx-home">
    <LXHeader />

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
/* ================= 纸感背景（极细噪点 + 极淡暖晕） ================= */
.lx-home {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--bg-page);
  color: var(--text-primary);
  /* 细纸纹噪点（feTurbulence，几乎不可察觉的颗粒质感） */
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
  background-attachment: fixed;
}

.lx-home::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  /* 极淡暖橙晕，模拟纸张受光 */
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