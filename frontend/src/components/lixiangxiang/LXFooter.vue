<template>
  <footer class="lx-footer">
    <div class="lx-footer-inner">
      <div class="lx-footer-brand">
        <span class="lx-footer-logo">理</span>
        <span class="lx-footer-name">理想乡 · 组织官网</span>
      </div>

      <div class="lx-footer-links">
        <a href="#intro">组织介绍</a>
        <a href="#members">成员</a>
        <a href="#bases">地图基地</a>
        <a href="#gallery">相册</a>
        <router-link to="/dashboard">控制台</router-link>
      </div>

      <div class="lx-footer-meta">
        <p>Minecraft 生存服务器 · 理想乡</p>
        <a href="https://beian.miit.gov.cn" target="_blank" rel="noopener noreferrer">渝ICP备2026011793号-1</a>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
</script>

<style scoped>
.lx-footer {
  background: var(--bg-deep);
  border-top: 1px solid var(--border-subtle);
  padding: 48px 24px 56px;
}

.lx-footer-inner {
  max-width: 1120px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  text-align: center;
}

.lx-footer-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.lx-footer-logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--accent), #B85C38);
  color: #FFF8F2;
  font-family: var(--font-display);
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.lx-footer-name {
  font-family: var(--font-display);
  font-size: 17px;
  color: var(--text-inverse);
}

.lx-footer-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px 24px;
}

.lx-footer-links a {
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 14px;
  text-decoration: none;
  transition: color 150ms var(--ease-out);
}

.lx-footer-links a:hover {
  color: var(--accent);
}

.lx-footer-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
}

.lx-footer-meta p {
  margin: 0;
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-muted);
}

.lx-footer-meta a {
  color: var(--text-muted);
  font-size: 12px;
  text-decoration: none;
}

.lx-footer-meta a:hover {
  color: var(--text-secondary);
}
</style>