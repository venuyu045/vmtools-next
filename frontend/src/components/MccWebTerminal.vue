<template>
  <div class="mcc-terminal" :class="{ embedded }">
    <div class="terminal-toolbar">
      <el-input
        v-model="searchKeyword"
        class="search-input"
        placeholder="搜索终端内容"
        clearable
        @keyup.enter="findNext"
        @clear="clearSearch"
      >
        <template #suffix>
          <el-icon class="search-icon-btn" title="上一个" @click="findPrevious"><ArrowUp /></el-icon>
          <el-icon class="search-icon-btn" title="下一个" @click="findNext"><ArrowDown /></el-icon>
        </template>
      </el-input>
      <el-checkbox v-model="autoScroll">自动滚动</el-checkbox>
      <button class="pixel-btn outline" @click="fitTerminal">适配</button>
      <button class="pixel-btn outline" @click="clearScreen">清屏</button>
      <button class="pixel-btn outline" @click="downloadLog">下载日志</button>
      <button class="pixel-btn outline" @click="reloadHistory">重载历史</button>
    </div>

    <div ref="terminalContainer" class="xterm-shell" :style="{ height }"></div>

    <div class="terminal-input-row">
      <el-input
        ref="cmdInputRef"
        v-model="inputDraft"
        class="terminal-input"
        placeholder="输入命令或聊天内容，回车发送（↑/↓ 历史 · Tab 补全）"
        clearable
        @keydown.enter.prevent="submitFromInput"
        @keydown.up.prevent="recallFromInput(-1)"
        @keydown.down.prevent="recallFromInput(1)"
        @keydown.tab.prevent="autocompleteFromInput"
      >
        <template #prefix><span class="mono input-prefix">&gt;</span></template>
      </el-input>
      <button class="pixel-btn" @click="submitFromInput">发送</button>
    </div>

    <div class="terminal-status mono">
      <span>{{ title || slug || instanceId }}</span>
      <span>{{ lineCount }} lines</span>
      <span class="conn-state" :style="{ color: connState.color }">
        <span class="conn-dot" :style="{ background: connState.color }"></span>
        {{ connState.text }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { Unicode11Addon } from '@xterm/addon-unicode11'
import '@xterm/xterm/css/xterm.css'
import { useMccInstanceStore, TERMINAL_MAX_LINES } from '@/stores/mccInstance'
import { useSocketIO } from '@/composables/useSocketIO'
import { mccInstanceApi, type MccTerminalLine } from '@/api/mccInstance'

const props = withDefaults(defineProps<{
  instanceId: string
  slug?: string
  title?: string
  height?: string
  embedded?: boolean
  tailLines?: number
}>(), {
  slug: '',
  title: '',
  height: '560px',
  embedded: false,
  tailLines: TERMINAL_MAX_LINES,
})

const store = useMccInstanceStore()
const socket = useSocketIO()
const terminalContainer = ref<HTMLElement | null>(null)
const searchKeyword = ref('')
const autoScroll = ref(true)
const lineCount = computed(() => terminalLines.value.length)
const terminalLines = computed(() => store.terminalLines[props.instanceId] || [])

/** 独立输入框：xterm 只做显示，输入统一走这里，避免输出行截断输入。 */
const inputDraft = ref('')
const cmdInputRef = ref()

type ConnState = { text: string; color: string }
const connState = ref<ConnState>({ text: 'ready', color: '#888' })

let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let searchAddon: SearchAddon | null = null
let resizeObserver: ResizeObserver | null = null
let lastSeq = 0
let historyCursor = -1
let commandHistory: string[] = []
let pendingDraft = '' // input preserved while browsing history
let joinConfirmTimer: ReturnType<typeof setTimeout> | null = null

const commandDictionary = [
  'help', 'status', 'exit', 'connect', 'disconnect', 'respawn', 'inventory', 'move',
  'login', 'logout', 'reco', 'script', 'send', 'list', 'look', 'dig', 'place', 'useitem', 'drop', 'dropall', 'hotbar', 'health', 'food', 'position', 'players', 'terrain', 'help settings', 'set', 'reload', 'quit', '/help', '/list', '/tell', '/msg', '/tpaccept', '/spawn', '/home', '/back']


function initTerminal() {
  if (!terminalContainer.value || terminal) return
  console.log('[Terminal] initTerminal: creating xterm instance')
  fitAddon = new FitAddon()
  searchAddon = new SearchAddon()
  terminal = new Terminal({
    allowProposedApi: true,
    convertEol: true,
    cursorBlink: true,
    // 输入统一走下方输入框，xterm 仅作显示（避免输出行截断输入）
    disableStdin: true,
    fontFamily: 'Consolas, "Courier New", monospace',
    fontSize: 14,
    lineHeight: 1.25,
    scrollback: 5000,
    theme: {
      background: '#000000',
      foreground: '#e8e8e8', // 默认文本白色（原绿色）
      cursor: '#e8e8e8',     // 光标白色
      selectionBackground: '#ffffff44',
      black: '#000000',
      red: '#ff4d4f',
      green: '#00ff41',      // ANSI 色板保留：chat/成功等仍可显示绿色
      yellow: '#ffcc00',
      blue: '#2f80ff',
      magenta: '#ff00ff',
      cyan: '#00ffff',
      white: '#e8e8e8',
      brightBlack: '#555555',
      brightRed: '#ff7875',
      brightGreen: '#7cff9b',
      brightYellow: '#ffe066',
      brightBlue: '#69a7ff',
      brightMagenta: '#ff75ff',
      brightCyan: '#75ffff',
      brightWhite: '#ffffff',
    },
  })
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(searchAddon)
  terminal.loadAddon(new WebLinksAddon())
  terminal.loadAddon(new Unicode11Addon())
  terminal.unicode.activeVersion = '11'
  terminal.open(terminalContainer.value)
  console.log('[Terminal] initTerminal: xterm opened on container', terminalContainer.value)

  terminal.writeln('\x1b[32mVMTools Bot Web Terminal\x1b[0m')
  terminal.writeln('\x1b[90m请在下方输入框输入：/xxx 为服务器命令，其他内容自动作为游戏聊天发送。\x1b[0m')
  terminal.writeln('')

  // 移动端触摸滚动：不依赖浏览器原生滚动（xterm 自身触摸处理器会拦截原生滚动导致"滑不动"），
  // 改为 JS 手动接管——在整个终端区域(.xterm-shell)监听，手点到哪里都能滑历史：
  //  - 有历史且方向允许 → preventDefault + viewport.scrollTop -= dy（手动滚动）
  //  - 已到顶/底或无历史 → 不拦截，手势交给页面滚动
  //  viewport 的 scroll 事件仍联动"自动滚动"开关。
  const viewport = terminalContainer.value.querySelector('.xterm-viewport') as HTMLElement | null
  if (viewport) {
    viewport.addEventListener('scroll', () => {
      if (!terminal) return
      const atBottom = viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 2
      if (!atBottom) {
        if (autoScroll.value) autoScroll.value = false
      } else if (!autoScroll.value) {
        autoScroll.value = true
      }
    }, { passive: true })

    let touchStartY = 0
    let touchLastY = 0
    let touchMode: 'none' | 'scroll' = 'none'
    const shell = terminalContainer.value
    shell.addEventListener('touchstart', (e) => {
      touchStartY = e.touches[0].clientY
      touchLastY = e.touches[0].clientY
      touchMode = 'none'
    }, { passive: true })
    shell.addEventListener('touchmove', (e) => {
      if (!terminal) return
      const y = e.touches[0].clientY
      const dy = y - touchLastY
      touchLastY = y
      // 纵向位移超过阈值才判定为滚动手势（避免误伤点击/轻扫）
      if (touchMode === 'none') {
        if (Math.abs(y - touchStartY) < 10) return
        touchMode = 'scroll'
      }
      if (touchMode !== 'scroll') return
      const maxScroll = viewport.scrollHeight - viewport.clientHeight
      if (maxScroll <= 0) return // 终端无历史可滚 → 交还页面滚动
      const goingUp = dy < 0   // 手指上滑 → 看新内容（scrollTop 增大）
      const goingDown = dy > 0 // 手指下滑 → 看更早历史（scrollTop 减小）
      const canScrollUp = viewport.scrollTop > 0
      const canScrollDown = viewport.scrollTop < maxScroll - 1
      if ((goingUp && canScrollDown) || (goingDown && canScrollUp)) {
        e.preventDefault()
        viewport.scrollTop -= dy
      }
      // 到边界：不 preventDefault → 手势交给页面滚动
    }, { passive: false })
    shell.addEventListener('touchend', () => { touchMode = 'none' }, { passive: true })
    shell.addEventListener('touchcancel', () => { touchMode = 'none' }, { passive: true })
  }

  resizeObserver = new ResizeObserver(() => fitTerminal())
  resizeObserver.observe(terminalContainer.value)
  nextTick(() => fitTerminal())
}

function historyKey(): string {
  return `mcc-command-history:${props.instanceId}`
}

function loadCommandHistory() {
  try {
    commandHistory = JSON.parse(localStorage.getItem(historyKey()) || '[]')
  } catch {
    commandHistory = []
  }
  historyCursor = -1
}

function saveCommand(command: string) {
  commandHistory = [command, ...commandHistory.filter(item => item !== command)].slice(0, 100)
  localStorage.setItem(historyKey(), JSON.stringify(commandHistory))
}

/** ↑/↓ 浏览命令历史（方向键操作输入框内容）。 */
function recallFromInput(direction: number) {
  if (!commandHistory.length) return
  // 首次按键时暂存用户正在输入的内容
  if (historyCursor === -1) pendingDraft = inputDraft.value
  historyCursor += direction < 0 ? 1 : -1
  if (historyCursor < 0) {
    historyCursor = -1
    inputDraft.value = pendingDraft
    pendingDraft = ''
    return
  }
  if (historyCursor >= commandHistory.length) historyCursor = commandHistory.length - 1
  inputDraft.value = commandHistory[historyCursor]
}

/** Tab 自动补全（历史 + 内置命令字典）。 */
function autocompleteFromInput() {
  const token = inputDraft.value.trimStart().toLowerCase()
  if (!token) return
  const candidates = [...commandHistory, ...commandDictionary]
  const match = candidates.find(command => command.toLowerCase().startsWith(token))
  if (match && match !== inputDraft.value) inputDraft.value = match
}

async function submitCommand(command: string) {
  const trimmed = command.trim()
  if (!trimmed) return
  // 原样发送：/xxx 走服务器命令、其余自动作为聊天，路由统一由后端处理
  await store.sendInput(props.instanceId, trimmed)
  saveCommand(trimmed)
  connState.value = { text: 'sent', color: '#00ff41' }
}

/** 输入框回车 / 发送按钮。 */
function submitFromInput() {
  const command = inputDraft.value.trim()
  if (!command) return
  void submitCommand(command)
  inputDraft.value = ''
  historyCursor = -1
  pendingDraft = ''
}

/**
 * Minecraft 遗留格式码（§a/§r/§l 等）→ ANSI 转义序列。
 * 服务器聊天/系统消息（mineflayer bot.on('message') toString()）带 § 颜色码，
 * xterm 不识别 § 码，需先转成 ANSI 才能按服务器配色渲染（MF 终端彩色文字修复）。
 * 使用 bright 色系（xterm 主题已定义 bright* 色板），k（随机闪烁）忽略。
 */
const MC_FORMAT_TO_ANSI: Record<string, string> = {
  '0': '\x1b[30m', '1': '\x1b[34m', '2': '\x1b[32m', '3': '\x1b[36m',
  '4': '\x1b[31m', '5': '\x1b[35m', '6': '\x1b[33m', '7': '\x1b[37m',
  '8': '\x1b[90m', '9': '\x1b[94m', a: '\x1b[92m', b: '\x1b[96m',
  c: '\x1b[91m', d: '\x1b[95m', e: '\x1b[93m', f: '\x1b[97m',
  l: '\x1b[1m', m: '\x1b[9m', n: '\x1b[4m', o: '\x1b[3m', r: '\x1b[0m',
}

function mcFormatToAnsi(text: string): string {
  return text.replace(/[\u00a7§]([0-9a-fk-or])/gi, (_, code: string) => MC_FORMAT_TO_ANSI[code.toLowerCase()] ?? '')
}

function formatLine(line: MccTerminalLine): string {
  const content = mcFormatToAnsi(line.content)
  if (line.stream === 'stdin') {
    // 输入行（仅其他观察者可见，本机已本地回显）：弱化前缀与时间戳
    return `\x1b[36m> ${content.replace(/^>\s*/, '')}\x1b[0m`
  }
  const time = line.created_at ? new Date(line.created_at).toLocaleTimeString() : '--:--:--'
  const streamColor = line.stream === 'stderr' ? '\x1b[31m' : '\x1b[90m'
  return `\x1b[90m[${time}]\x1b[0m ${streamColor}[${line.stream}]\x1b[0m ${content}`
}

/** True when this stdin echo line was produced by the current browser tab. */
function isOwnEcho(line: MccTerminalLine): boolean {
  if (line.stream !== 'stdin' || !line.from_sid) return false
  return line.from_sid === socket.getSocket()?.id
}

function renderAllLines() {
  if (!terminal) return
  terminal.clear()
  lastSeq = 0
  for (const line of terminalLines.value) {
    if (isOwnEcho(line)) continue
    terminal.writeln(formatLine(line))
    lastSeq = Math.max(lastSeq, line.seq)
  }
  if (autoScroll.value) terminal.scrollToBottom()
}

function appendNewLines(lines: MccTerminalLine[]) {
  if (!terminal) return
  const nextLines = lines.filter(line => line.seq > lastSeq && !isOwnEcho(line))
  if (!nextLines.length) return
  for (const line of nextLines) {
    terminal.writeln(formatLine(line))
    lastSeq = Math.max(lastSeq, line.seq)
  }
  // 不重写 prompt：避免打断用户正在输入的内容（回车后 prompt 已在本地写入）
  if (autoScroll.value) terminal.scrollToBottom()
}

let joinRetries = 0
function joinTerminalRoom() {
  socket.connect()
  connState.value = { text: 'joining…', color: '#ffcc00' }
  socket.emit('mcc_join_instance', { instance_id: props.instanceId, tail_lines: props.tailLines })
  scheduleJoinConfirm()
}

/** 5s 内未收到 snapshot 则重试 join（最多 2 次），仍失败才提示超时。 */
function scheduleJoinConfirm() {
  if (joinConfirmTimer) clearTimeout(joinConfirmTimer)
  joinConfirmTimer = setTimeout(() => {
    if (connState.value.text !== 'joining…') return
    if (joinRetries < 2) {
      joinRetries += 1
      socket.connect()
      socket.emit('mcc_join_instance', { instance_id: props.instanceId, tail_lines: props.tailLines })
      scheduleJoinConfirm()
    } else {
      connState.value = { text: 'timeout', color: '#ff4d4f' }
      terminal?.writeln('\x1b[31m[error] 加入终端房间超时，请检查连接\x1b[0m')
    }
  }, 5000)
}

function leaveTerminalRoom() {
  if (joinConfirmTimer) { clearTimeout(joinConfirmTimer); joinConfirmTimer = null }
  joinRetries = 0
  socket.emit('mcc_leave_instance', { instance_id: props.instanceId })
}

function onTerminalSnapshot(payload: any) {
  if (!payload || payload.instance_id !== props.instanceId) return
  if (joinConfirmTimer) { clearTimeout(joinConfirmTimer); joinConfirmTimer = null }
  joinRetries = 0
  connState.value = { text: 'joined', color: '#00ff41' }
}

function onTerminalError(payload: any) {
  if (!payload || (payload.instance_id && payload.instance_id !== props.instanceId)) return
  connState.value = { text: 'error', color: '#ff4d4f' }
  if (terminal) {
    terminal.writeln(`\x1b[31m[error] ${payload.message || '终端错误'}\x1b[0m`)
  }
  ElMessage.error(payload.message || '终端错误')
}

function onSocketDisconnect() {
  connState.value = { text: '已断开', color: '#ff4d4f' }
}

async function onSocketConnect() {
  // 断线后自动重连：重新加入房间并补齐断线期间的历史
  if (connState.value.text === '已断开') {
    connState.value = { text: 'rejoining…', color: '#ffcc00' }
    await joinTerminalRoom()
    await reloadHistory()
  }
}

async function reloadHistory() {
  try {
    await store.fetchTerminalHistory(props.instanceId)
    const count = terminalLines.value.length
    if (count > 0) renderAllLines()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '加载终端历史失败')
    connState.value = { text: 'history error', color: '#ff4d4f' }
  }
}

let lastResizeAt = 0
function fitTerminal() {
  try {
    fitAddon?.fit()
  } catch {
    // Ignore fit errors while the drawer/page is still animating.
  }
  // 通知后端调整 PTY 窗口尺寸（Linux 真终端生效；Windows 回退静默忽略）。
  // 节流 500ms，避免 ResizeObserver 高频触发。
  const term = terminal
  const now = Date.now()
  if (term && now - lastResizeAt > 500) {
    lastResizeAt = now
    socket.emit('mcc_terminal_resize', {
      instance_id: props.instanceId,
      cols: term.cols,
      rows: term.rows,
    })
  }
}

function findNext() {
  if (!searchKeyword.value.trim()) return
  searchAddon?.findNext(searchKeyword.value)
}

function findPrevious() {
  if (!searchKeyword.value.trim()) return
  searchAddon?.findPrevious(searchKeyword.value)
}

function clearSearch() {
  ;(searchAddon as any)?.clearDecorations?.()
}

function clearScreen() {
  terminal?.clear()
}

async function downloadLog() {
  try {
    const res = await mccInstanceApi.exportLog(props.instanceId)
    const blob = res.data as Blob
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${props.slug || props.instanceId}-terminal.log`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '日志导出失败')
  }
}

watch(terminalLines, (lines) => {
  if (lastSeq === 0 && lines.length > 0) {
    // 首批（快照/历史）到达：全量渲染一次，避免逐行闪烁与重复重绘
    renderAllLines()
  } else {
    appendNewLines(lines)
  }
})
watch(() => props.instanceId, async () => {
  lastSeq = 0
  inputDraft.value = ''
  pendingDraft = ''
  joinRetries = 0
  historyCursor = -1
  loadCommandHistory()
  // Clear terminal display for new instance
  if (terminal) {
    terminal.clear()
    terminal.writeln('\x1b[32mVMTools Bot Web Terminal\x1b[0m')
    terminal.writeln('\x1b[90m请在下方输入框输入：/xxx 为服务器命令，其他内容自动作为游戏聊天发送。\x1b[0m')
    terminal.writeln('')
  }
  await joinTerminalRoom()
  await reloadHistory()
})

onMounted(async () => {
  initTerminal()
  loadCommandHistory()
  socket.connect() // 确保 socket 实例存在，再注册事件
  socket.on('mcc_terminal_snapshot', onTerminalSnapshot)
  socket.on('mcc_terminal_error', onTerminalError)
  socket.on('disconnect', onSocketDisconnect)
  socket.on('connect', onSocketConnect)
  await joinTerminalRoom()
  await reloadHistory()
})

onBeforeUnmount(() => {
  leaveTerminalRoom()
  socket.off('mcc_terminal_snapshot', onTerminalSnapshot)
  socket.off('mcc_terminal_error', onTerminalError)
  socket.off('disconnect', onSocketDisconnect)
  socket.off('connect', onSocketConnect)
  resizeObserver?.disconnect()
  terminal?.dispose()
  terminal = null
  fitAddon = null
  searchAddon = null
})
</script>

<style scoped>
.mcc-terminal { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.terminal-toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.search-input { width: 220px; }
.terminal-toolbar .pixel-btn { padding: 8px 14px; }
.xterm-shell { width: 100%; min-height: 260px; padding: 8px; background: #000; border: 1px solid var(--border-card); overflow: hidden; touch-action: pan-y; overscroll-behavior: contain; }
.terminal-input-row { display: flex; gap: 10px; align-items: center; }
.terminal-input { flex: 1; }
.terminal-input :deep(.el-input__wrapper) { background: #000; border: 1px solid var(--border-card); box-shadow: none; }
.terminal-input :deep(.el-input__wrapper.is-focus) { border-color: var(--green-primary); }
.terminal-input :deep(.el-input__inner) { font-family: var(--font-mono); color: #00ff41; }
.input-prefix { color: var(--green-primary); font-weight: bold; }
.terminal-status { display: flex; justify-content: space-between; gap: 12px; color: var(--text-muted); font-size: 12px; }
.conn-state { display: inline-flex; align-items: center; gap: 6px; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.search-icon-btn { cursor: pointer; padding: 2px; margin-left: 4px; }
.search-icon-btn:hover { color: var(--green-primary); }
/* 移动端：搜索箭头/发送按钮加大触控区（≥40px，防误触） */
.search-icon-btn { display: inline-flex; align-items: center; justify-content: center; }
@media (max-width: 768px) {
  .search-icon-btn { padding: 8px; margin-left: 2px; }
  .terminal-input-row .pixel-btn { min-height: 44px; }
}
:deep(.xterm) { height: 100%; }
:deep(.xterm-viewport) {
  scrollbar-color: var(--green-primary) #000;
  /* 阻断滚动链：终端内滚动到边界后不再把滚动传递给页面（防穿透） */
  overscroll-behavior: contain;
  /* 老 iOS 惯性滚动 */
  -webkit-overflow-scrolling: touch;
  /* 纵向滚动手势直接交给 viewport（避免浏览器等待双击缩放判定造成延迟/卡顿） */
  touch-action: pan-y;
}
:deep(.xterm-screen) {
  /* 触摸实际落在 screen 上：声明允许纵向平移，滚动才跟手（xterm 默认 auto 会与页面手势抢） */
  touch-action: pan-y;
}
:deep(.xterm-screen) { /* 去掉绿色辉光，默认白色文本更干净 */ }

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .terminal-toolbar { gap: 6px; }
  .search-input { width: 100%; flex-basis: 100%; }
  .terminal-toolbar .pixel-btn { font-size: 12px; padding: 6px 10px; min-height: 36px; }
  .terminal-status { font-size: 10px; gap: 6px; flex-wrap: wrap; }
  .xterm-shell { min-height: 200px; }
}
</style>
