<template>
  <div>
    <div class="cfg-header">
      <el-button size="small" @click="goBack">← 返回插件列表</el-button>
      <h2 style="margin: 0 0 0 12px; display: inline-block">
        {{ pluginName }} 配置
      </h2>
      <el-tag v-if="meta.enabled !== undefined" :type="meta.enabled ? 'success' : 'info'" style="margin-left: 12px">
        {{ meta.enabled ? '已启用' : '已禁用' }}
      </el-tag>
      <span v-if="meta.version" class="cfg-version">v{{ meta.version }}</span>
    </div>
    <p v-if="meta.description" class="cfg-desc">{{ meta.description }}</p>

    <div v-loading="loading">
      <template v-if="fields.length">
        <div v-for="field in fields" :key="field.key" class="cfg-card">
          <h3>{{ field.schema.title || field.key }}</h3>
          <p v-if="field.schema.description" class="cfg-card-desc">{{ field.schema.description }}</p>

          <!-- 动态键值对（如指令表） -->
          <template v-if="field.schema.type === 'object' && field.schema.additionalProperties">
            <div v-for="(row, idx) in kvState[field.key] || []" :key="idx" class="kv-row">
              <el-input v-model="row.key" :placeholder="field.schema.keyTitle || '键'" style="flex: 1" />
              <el-input v-model="row.value" :placeholder="field.schema.valueTitle || '值'" style="flex: 2" />
              <el-button size="small" type="danger" plain @click="removeKvRow(field.key, idx)">删除</el-button>
            </div>
            <el-button size="small" type="primary" plain @click="addKvRow(field.key)">
              + 添加{{ field.schema.keyTitle || '条目' }}
            </el-button>
          </template>

          <!-- 布尔 -->
          <el-switch
            v-else-if="field.schema.type === 'boolean'"
            v-model="config[field.key]"
            active-text="开启"
            inactive-text="关闭"
          />

          <!-- 文本 -->
          <el-input
            v-else
            v-model="config[field.key]"
            :placeholder="field.schema.title || field.key"
          />
        </div>

        <div class="cfg-actions">
          <el-button @click="resetToDefault" :disabled="saving">恢复默认</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="该插件暂无配置项" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { pluginApi } from '@/api/plugin'
import { ElMessage } from 'element-plus'

interface KvRow { key: string; value: string }

const route = useRoute()
const router = useRouter()
const pluginName = String(route.params.name || '')

const loading = ref(false)
const saving = ref(false)
const meta = reactive<Record<string, any>>({})
const config = reactive<Record<string, any>>({})
const defaultConfig = ref<Record<string, any>>({})
const schema = ref<Record<string, any>>({})
/** 动态键值表的可编辑行（v-model 直接作用于这些行对象） */
const kvState = reactive<Record<string, KvRow[]>>({})

/** schema.properties 的有序字段列表 */
const fields = computed(() => {
  const props = schema.value?.properties || {}
  return Object.keys(props).map((key) => ({ key, schema: props[key] }))
})

function isKvField(fieldKey: string): boolean {
  const prop = schema.value?.properties?.[fieldKey]
  return !!(prop && prop.type === 'object' && prop.additionalProperties)
}

function goBack() {
  router.push('/plugins')
}

/** 从 config[fieldKey] 对象同步出可编辑行（加载/重置后调用） */
function syncKvFromConfig(fieldKey: string) {
  const val = config[fieldKey]
  kvState[fieldKey] = val && typeof val === 'object'
    ? Object.keys(val).map((k) => ({ key: String(k), value: String(val[k] ?? '') }))
    : []
}

function addKvRow(fieldKey: string) {
  if (!kvState[fieldKey]) kvState[fieldKey] = []
  kvState[fieldKey].push({ key: '', value: '' })
}

function removeKvRow(fieldKey: string, idx: number) {
  if (!kvState[fieldKey]) return
  kvState[fieldKey].splice(idx, 1)
}

function resetToDefault() {
  const d = defaultConfig.value || {}
  Object.keys(config).forEach((k) => delete config[k])
  Object.assign(config, JSON.parse(JSON.stringify(d)))
  fields.value.forEach((f) => { if (isKvField(f.key)) syncKvFromConfig(f.key) })
  ElMessage.info('已重置为默认配置，点击「保存配置」生效')
}

async function save() {
  if (!pluginName) return
  saving.value = true
  try {
    const payload: Record<string, any> = {}
    for (const field of fields.value) {
      if (isKvField(field.key)) {
        // 从行状态组装对象（过滤空键）
        const cleaned: Record<string, any> = {}
        for (const row of kvState[field.key] || []) {
          const key = String(row.key ?? '').trim()
          const value = String(row.value ?? '').trim()
          if (key) cleaned[key] = value
        }
        payload[field.key] = cleaned
      } else {
        payload[field.key] = config[field.key]
      }
    }
    const { data } = await pluginApi.savePluginConfig(pluginName, payload)
    Object.keys(config).forEach((k) => delete config[k])
    Object.assign(config, data.config || {})
    fields.value.forEach((f) => { if (isKvField(f.key)) syncKvFromConfig(f.key) })
    ElMessage.success('配置已保存并立即生效')
  } catch (e: any) {
    ElMessage.error(`保存失败：${e?.response?.data?.detail || e?.message || '未知错误'}`)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (!pluginName) return
  loading.value = true
  try {
    const { data } = await pluginApi.getPluginConfig(pluginName)
    meta.name = data.name
    meta.version = data.version
    meta.enabled = data.enabled
    meta.description = data.description
    schema.value = data.schema || {}
    defaultConfig.value = data.default_config || {}
    Object.assign(config, data.config || {})
    fields.value.forEach((f) => { if (isKvField(f.key)) syncKvFromConfig(f.key) })
  } catch (e: any) {
    ElMessage.error(`加载配置失败：${e?.response?.data?.detail || e?.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.cfg-header {
  display: flex;
  align-items: center;
}
.cfg-version {
  margin-left: 8px;
  color: var(--text-muted, #008800);
  font-size: 13px;
}
.cfg-desc {
  color: var(--text-muted, #008800);
  font-size: 13px;
  margin: 8px 0 0;
}
.cfg-card {
  background: var(--bg-card, #101010);
  border: 1px solid var(--border-subtle, #1d1d1d);
  border-radius: 0;
  padding: 16px;
  margin-top: 16px;
}
.cfg-card h3 {
  margin: 0 0 4px;
  font-size: 15px;
}
.cfg-card-desc {
  color: var(--text-muted, #008800);
  font-size: 12px;
  margin: 0 0 12px;
  line-height: 1.6;
}
.kv-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
.cfg-actions {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>