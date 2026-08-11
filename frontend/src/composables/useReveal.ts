/**
 * 滚动显现：元素进入视口后添加 is-revealed（淡入上移动效）。
 * - 支持 IntersectionObserver；不支持时直接显示（无 JS 降级）。
 * - 配合 CSS：.lx-section { opacity:0; transform:translateY(24px); transition:... }
 *            .lx-section.is-revealed { opacity:1; transform:none }
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export function useReveal<T extends HTMLElement = HTMLElement>(threshold = 0.12) {
  const rootRef = ref<T | null>(null)
  const revealed = ref(false)
  let observer: IntersectionObserver | null = null

  onMounted(() => {
    const el = rootRef.value
    if (!el) return
    // 兼容：无 IntersectionObserver（旧浏览器）或用户偏好减少动效 → 直接显示
    const prefersReduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced || typeof IntersectionObserver === 'undefined') {
      revealed.value = true
      return
    }
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            revealed.value = true
            observer?.disconnect()
            break
          }
        }
      },
      { threshold, rootMargin: '0px 0px -8% 0px' },
    )
    observer.observe(el)
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
  })

  return { rootRef, revealed }
}
