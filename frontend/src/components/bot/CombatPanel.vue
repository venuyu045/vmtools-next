<template>
  <div class="combat-panel">
    <div class="combat-head">
      <span class="combat-title">⚔ 自动攻击（MF 独有）</span>
      <span v-if="activeMode" class="combat-badge">{{ activeMode === 'auto' ? '● 自动攻击中' : '● 守护中' }}</span>
    </div>

    <el-form label-width="92px" size="small" class="combat-form">
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" @change="saveAuto" />
      </el-form-item>
      <el-form-item label="移动攻击">
        <el-switch v-model="form.move_to_target" />
        <span class="form-hint">关 = 挂机原地攻击（假人不动）；开 = 寻路追击目标</span>
      </el-form-item>
      <el-form-item label="攻击半径">
        <el-input-number v-model="form.radius" :min="1" :max="64" /> 格
      </el-form-item>
      <el-form-item label="目标类型">
        <el-select v-model="form.target_types" multiple placeholder="空 = 全部实体" style="width: 100%">
          <el-option label="盔甲架" value="armor_stand" />
          <el-option label="玩家" value="player" />
          <el-option label="敌对生物（生物类）" value="hostile" />
          <el-option label="物件类（矿车/船等）" value="object" />
          <el-option label="全部实体" value="all" />
        </el-select>
      </el-form-item>
      <el-form-item label="攻击间隔">
        <el-input-number v-model="form.interval_ms" :min="100" :max="60000" :step="100" /> ms
      </el-form-item>
      <el-form-item label="耐久阈值">
        <el-input-number v-model="stopPct" :min="1" :max="100" /> %
        <span class="form-hint">低于此值自动停止并 QQ @主人</span>
      </el-form-item>
    </el-form>

    <div class="dur-row">
      <span class="dur-label">主手武器</span>
      <span class="mono dur-name">{{ dur.zh_name || dur.display_name || dur.name || '空手 / 无耐久' }}</span>
      <span class="mono dur-pct">{{ durPct }}%</span>
      <el-progress :percentage="durPct" :stroke-width="8" :show-text="false" :color="durColor" class="dur-bar" />
    </div>

    <div class="combat-actions">
      <button class="pixel-btn" @click="saveAuto">应用配置</button>
      <button class="pixel-btn warning" @click="stopAll">停止攻击</button>
      <button class="pixel-btn outline" @click="manualAttack">攻击最近</button>
      <button class="pixel-btn outline" @click="startGuard">守护当前位置</button>
      <button class="pixel-btn outline" @click="refreshAll">刷新</button>
    </div>

    <div class="entities">
      <div class="entities-head">
        <span>附近实体（{{ entities.length }}）</span>
        <button class="pixel-btn mini outline" @click="loadEntities">重新扫描</button>
      </div>
      <div v-if="entities.length === 0" class="empty-text mono">范围内无实体</div>
      <div v-for="e in entities" :key="e.id" class="entity-row">
        <span class="mono entity-name">{{ zhName(e.name) }}</span>
        <span class="entity-id">({{ e.name }})</span>
        <span class="mono entity-dist">{{ e.distance }}m</span>
        <button class="pixel-btn mini" @click="attackOne(e.id)">攻击</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { botApi } from '@/api/bot'

interface EntityInfo {
  id: number
  name: string
  displayName: string
  type: string
  distance: number
  position: { x: number; y: number; z: number }
}

// ── 实体名 → 中文（附近实体列表汉化，2026-08-10） ──
const ENTITY_ZH: Record<string, string> = {
  armor_stand: '盔甲架', item_frame: '物品展示框', painting: '画',
  item: '掉落物', experience_orb: '经验球', experience_bottle: '附魔之瓶',
  arrow: '箭', spectral_arrow: '光灵箭', trident: '三叉戟', snowball: '雪球',
  egg: '鸡蛋', ender_pearl: '末影珍珠', ender_eye: '末影之眼',
  fireball: '火球', small_fireball: '小火球', dragon_fireball: '末影龙火球',
  wither_skull: '凋灵之首', shulker_bullet: '潜影贝导弹', llama_spit: '羊驼唾沫',
  falling_block: '下落的方块', tnt: 'TNT', firework_rocket: '烟花火箭',
  area_effect_cloud: '区域效果云', lightning_bolt: '闪电', fishing_bobber: '鱼钩',
  minecart: '矿车', chest_minecart: '运输矿车', furnace_minecart: '动力矿车',
  hopper_minecart: '漏斗矿车', command_block_minecart: '命令方块矿车',
  tnt_minecart: 'TNT矿车', spawner_minecart: '刷怪笼矿车',
  boat: '船', chest_boat: '箱子船',
  zombie: '僵尸', husk: '尸壳', drowned: '溺尸', zombie_villager: '僵尸村民',
  skeleton: '骷髅', stray: '流髅', bogged: '沼骸', wither_skeleton: '凋灵骷髅',
  creeper: '苦力怕', spider: '蜘蛛', cave_spider: '洞穴蜘蛛',
  enderman: '末影人', endermite: '末影螨', shulker: '潜影贝',
  slime: '史莱姆', magma_cube: '岩浆怪', phantom: '幻翼',
  blaze: '烈焰人', ghast: '恶魂', wither: '凋灵', witch: '女巫',
  pillager: '掠夺者', vindicator: '卫道士', evoker: '唤魔者', ravager: '劫掠兽',
  iron_golem: '铁傀儡', snow_golem: '雪傀儡', silverfish: '蠹虫',
  guardian: '守卫者', elder_guardian: '远古守卫者', warden: '循声守卫',
  piglin: '猪灵', piglin_brute: '猪灵蛮兵', zombified_piglin: '僵尸猪灵',
  hoglin: '疣猪兽', zoglin: '僵尸疣猪兽', strider: '炽足兽',
  villager: '村民', wandering_trader: '流浪商人', player: '玩家',
  cow: '牛', pig: '猪', sheep: '羊', chicken: '鸡', rabbit: '兔子',
  wolf: '狼', cat: '猫', horse: '马', donkey: '驴', mule: '骡',
  skeleton_horse: '骷髅马', zombie_horse: '僵尸马', llama: '羊驼',
  trader_llama: '行商羊驼', mooshroom: '哞菇', ocelot: '豹猫', parrot: '鹦鹉',
  bat: '蝙蝠', bee: '蜜蜂', fox: '狐狸', panda: '熊猫', polar_bear: '北极熊',
  turtle: '海龟', dolphin: '海豚', squid: '鱿鱼', glow_squid: '发光鱿鱼',
  salmon: '鲑鱼', cod: '鳕鱼', pufferfish: '河豚', tropical_fish: '热带鱼',
  allay: '悦灵', axolotl: '美西螈', goat: '山羊', frog: '青蛙', tadpole: '蝌蚪',
  camel: '骆驼', sniffer: '嗅探兽', breeze: '旋风人', armadillo: '犰狳',
  ender_dragon: '末影龙', mark: '标记', interaction: '交互实体',
  item_display: '物品展示实体', block_display: '方块展示实体', text_display: '文字展示实体',
}

function zhName(name: string): string {
  return ENTITY_ZH[name] || name
}

const props = defineProps<{ botId: string }>()

const form = reactive({
  enabled: false,
  radius: 8,
  target_types: [] as string[],
  interval_ms: 1000,
  stop_durability: 0.1,
  move_to_target: false, // 2026-08-11：默认挂机（假人不动原地攻击）
})
const stopPct = ref(10)
const activeMode = ref<string | null>(null)
const dur = ref<{ hasDurability: boolean; ratio: number; name: string | null; display_name?: string | null; zh_name?: string | null }>({ hasDurability: false, ratio: 1, name: null })
const entities = ref<EntityInfo[]>([])

const durPct = computed(() => Math.round((dur.value?.ratio ?? 1) * 100))
const durColor = computed(() => (durPct.value < 10 ? '#e34d59' : durPct.value < 30 ? '#e6a23c' : '#67c23a'))

function syncFromStatus(data: any) {
  const cfg = data?.config
  if (cfg) {
    form.enabled = !!cfg.enabled
    form.radius = cfg.radius ?? 8
    form.target_types = Array.isArray(cfg.target_types) ? [...cfg.target_types] : []
    form.interval_ms = cfg.interval_ms ?? 1000
    form.stop_durability = cfg.stop_durability ?? 0.1
    form.move_to_target = !!cfg.move_to_target
    stopPct.value = Math.round((form.stop_durability ?? 0.1) * 100)
  }
  activeMode.value = data?.active_mode ?? null
  if (data?.durability) {
    dur.value = data.durability
  }
}

async function loadStatus() {
  try {
    const resp = await botApi.combatStatus(props.botId)
    syncFromStatus(resp.data)
  } catch (err: any) {
    // 实例离线等场景静默
  }
}

async function loadEntities() {
  try {
    const resp = await botApi.combatEntities(props.botId, form.radius, form.target_types)
    entities.value = resp.data?.entities || []
  } catch (err: any) {
    ElMessage.warning(err?.response?.data?.detail || '获取实体列表失败')
  }
}

async function saveAuto() {
  try {
    const resp = await botApi.combatAutoAttack(props.botId, {
      enabled: form.enabled,
      radius: form.radius,
      target_types: form.target_types,
      interval_ms: form.interval_ms,
      stop_durability: stopPct.value / 100,
      move_to_target: form.move_to_target,
    })
    syncFromStatus({ config: resp.data?.config, active_mode: form.enabled ? 'auto' : null })
    ElMessage.success(form.enabled ? '自动攻击已开启' : '自动攻击已关闭')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '配置失败')
  }
}

async function stopAll() {
  try {
    await botApi.combatStop(props.botId)
    form.enabled = false
    activeMode.value = null
    ElMessage.success('已停止攻击')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '停止失败')
  }
}

async function manualAttack() {
  try {
    const resp = await botApi.combatAttack(props.botId, { move_to_target: form.move_to_target })
    if (resp.data?.result?.success === false) {
      ElMessage.warning(resp.data.result.error || '未找到目标')
      return
    }
    ElMessage.success(`已攻击 ${resp.data?.result?.target || '目标'}`)
    loadEntities()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '攻击失败')
  }
}

async function attackOne(id: number) {
  try {
    const resp = await botApi.combatAttack(props.botId, { target_id: id, move_to_target: form.move_to_target })
    ElMessage.success(`已攻击 ${resp.data?.result?.target || id}`)
    loadEntities()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '攻击失败')
  }
}

async function startGuard() {
  try {
    const resp = await botApi.combatGuard(props.botId, {
      enabled: true,
      radius: form.radius,
      target_types: form.target_types,
      interval_ms: form.interval_ms,
      stop_durability: stopPct.value / 100,
      move_to_target: form.move_to_target,
    })
    syncFromStatus({ config: resp.data?.config, active_mode: 'guard' })
    form.enabled = true // 守护进行中，「启用」开关同步为开（避免误以为没生效）
    ElMessage.success('守护模式已开启（守护当前位置）')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '守护配置失败')
  }
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadEntities()])
}

onMounted(() => {
  refreshAll()
})
</script>

<style scoped>
.combat-panel {
  border: 1px solid var(--border-color, rgba(217, 119, 87, 0.25));
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--bg-card, #f5f3ec);
}
.combat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.combat-title {
  font-family: var(--font-display, inherit);
  font-weight: 600;
}
.combat-badge {
  font-size: 12px;
  color: #67c23a;
  font-weight: 600;
}
.combat-form {
  margin-bottom: 6px;
}
.form-hint {
  font-size: 11px;
  color: var(--text-muted, #83807a);
  margin-left: 8px;
}
.dur-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
  font-size: 12px;
}
.dur-label { color: var(--text-muted, #83807a); }
.dur-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dur-pct { width: 40px; text-align: right; }
.dur-bar { width: 140px; }
.combat-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0;
}
.entities {
  border-top: 1px dashed var(--border-color, rgba(217, 119, 87, 0.25));
  padding-top: 8px;
  max-height: 220px;
  overflow-y: auto;
}
.entities-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--text-muted, #83807a);
  margin-bottom: 6px;
}
.entity-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 12px;
}
.entity-name { flex: 1; }
.entity-id { color: var(--text-muted, #83807a); font-style: normal; }
.entity-dist { width: 56px; text-align: right; color: var(--text-muted, #83807a); }
.pixel-btn.mini { padding: 2px 8px; font-size: 12px; }
</style>