<template>
  <div>
    <div class="page-header">
      <button class="pixel-btn" @click="showCreate = true">+ 注册 Bot</button>
    </div>
    <div class="bot-grid">
      <div v-if="botStore.bots.length === 0" class="empty-text mono">-- 暂无 Bot，点击上方按钮注册 --</div>
      <BotCard
        v-for="bot in botStore.bots"
        :key="bot.bot_id"
        :bot="bot"
        @connect="handleConnect"
        @disconnect="handleDisconnect"
        @delete="handleDelete"
      />
    </div>
    <el-dialog v-model="showCreate" title="注册 Bot" width="480px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="Bot ID">
          <el-input v-model="createForm.bot_id" placeholder="例如: builder-01" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="例如: Alice" />
        </el-form-item>
        <el-form-item label="MC 用户名">
          <el-input v-model="createForm.mc_username" placeholder="Minecraft 账号名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useBotStore } from '@/stores/bot'
import BotCard from '@/components/bot/BotCard.vue'
import { ElMessage } from 'element-plus'

const botStore = useBotStore()
const showCreate = ref(false)
const createForm = ref({ bot_id: '', name: '', mc_username: '' })

async function handleCreate() {
  if (!createForm.value.bot_id) {
    ElMessage.warning('请输入 Bot ID')
    return
  }
  await botStore.createBot(createForm.value)
  showCreate.value = false
  createForm.value = { bot_id: '', name: '', mc_username: '' }
  ElMessage.success('Bot 已注册')
}

async function handleConnect(bot: any) {
  await botStore.connectBot(bot.bot_id)
  ElMessage.success('连接成功')
}

async function handleDisconnect(bot: any) {
  await botStore.disconnectBot(bot.bot_id)
  ElMessage.success('已断开')
}

async function handleDelete(bot: any) {
  await botStore.deleteBot(bot.bot_id)
  ElMessage.success('已删除')
}

onMounted(() => botStore.fetchBots())
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.bot-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.empty-text { color: var(--text-muted); text-align: center; padding: 60px 0; font-size: 18px; }
@media (max-width: 1200px) { .bot-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 800px) { .bot-grid { grid-template-columns: 1fr; } }
</style>
