/**
 * 大标题「中心带淡入淡出」：标题仅在视口垂直中间区域完整显示，
 * 滚出中心带（向上/向下）后淡出消失 → 同一时刻屏幕上只有一个大标题，
 * 滚动翻页时旧标题淡出、新标题淡入，避免大屏上两个大标题同屏的杂乱感。
 *
 * - 观察区 = 视口中间 30%（rootMargin 上下各 -35%）
 * - 进入中心带 → titleOn=true（淡入）；离开 → false（淡出）
 * - 无 IntersectionObserver / prefers-reduced-motion → 直接常显（降级）
 * - 配合 CSS：.lx-section-title { opacity:0; transform:translateY(18px); transition:... }
 *             .lx-section-title.lx-title-on { opacity:1; transform:none }
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export function useTitleFade<T extends HTMLElement = HTMLElement>() {
  const titleRef = ref<T | null>(null)
  const titleOn = ref(false)
  let observer: IntersectionObserver | null = null

  onMounted(() => {
    const el = titleRef.value
    if (!el) return
    const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced || typeof IntersectionObserver === 'undefined') {
      // 降级：减少动效偏好 / 旧浏览器 → 标题常显
      titleOn.value = true
      return
    }
    observer = new IntersectionObserver(
      (entries) => {
        titleOn.value = entries.some((e) => e.isIntersecting)
      },
      { rootMargin: '-35% 0px -35% 0px', threshold: 0.1 },
    )
    observer.observe(el)
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
  })

  return { titleRef, titleOn }
}
