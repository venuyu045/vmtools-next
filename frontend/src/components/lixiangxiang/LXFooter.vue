<template>
  <footer class="lx-footer">
    <div class="lx-footer-inner">
      <div class="lx-footer-brand">
        <span class="lx-footer-logo">理</span>
        <span class="lx-footer-name">理想乡</span>
        <span class="lx-footer-sub">LIXIANGXIANG · EST. 2023</span>
      </div>

      <nav class="lx-footer-links">
        <a href="#intro">组织介绍</a>
        <a href="#members">成员</a>
        <a href="#bases">地图基地</a>
        <a href="#gallery">光影集</a>
        <router-link to="/dashboard">控制台</router-link>
      </nav>

      <div class="lx-footer-meta">
        <span>Minecraft 生存服务器</span>
        <a href="https://beian.miit.gov.cn" target="_blank" rel="noopener noreferrer">渝ICP备2026011793号-1</a>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
</script>

<style scoped>
.lx-footer {
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-page);
  padding: 56px 24px 64px;
}

.lx-footer-inner {
  max-width: 1120px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 28px;
  text-align: center;
}

.lx-footer-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.lx-footer-logo {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: var(--text-primary);
  color: var(--bg-page);
  font-family: var(--font-display);
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.lx-footer-name {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--text-primary);
  letter-spacing: 2px;
}

.lx-footer-sub {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 2.5px;
  color: var(--text-muted);
  padding-left: 12px;
  border-left: 1px solid var(--border-default);
}

.lx-footer-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px 28px;
}

.lx-footer-links a {
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13.5px;
  text-decoration: none;
  transition: color 200ms var(--ease-out);
}

.lx-footer-links a:hover {
  color: var(--accent);
}

.lx-footer-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
}

.lx-footer-meta span {
  font-family: var(--font-sans);
  font-size: 12.5px;
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