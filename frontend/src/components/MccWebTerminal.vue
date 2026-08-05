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

type ConnState = { text: string; color: string }
const connState = ref<ConnState>({ text: 'ready', color: '#888' })

let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let searchAddon: SearchAddon | null = null
let resizeObserver: ResizeObserver | null = null
let lastSeq = 0
let commandBuffer = ''
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
    disableStdin: false,
    fontFamily: 'Consolas, "Courier New", monospace',
    fontSize: 14,
    lineHeight: 1.25,
    scrollback: 5000,
    theme: {
      background: '#000000',
      foreground: '#00ff41',
      cursor: '#00ff41',
      selectionBackground: '#00ff4166',
      black: '#000000',
      red: '#ff4d4f',
      green: '#00ff41',
      yellow: '#ffcc00',
      blue: '#2f80ff',
      magenta: '#ff00ff',
      cyan: '#00ffff',
      white: '#d6ffe0',
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

  // Prevent touch scrolling from propagating to the page
  terminalContainer.value.addEventListener('touchmove', (e) => {
    e.stopPropagation()
  }, { passive: false })

  terminal.onData(handleTerminalInput)
  terminal.writeln('\x1b[32mVMTools MCC Web Terminal\x1b[0m')
  terminal.writeln('\x1b[90m以 / 开头的内容作为服务器命令；其他内容自动作为游戏聊天发送。\x1b[0m')
  terminal.write(`\r\n${promptText()}`)

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

/** Display width of a code point (CJK/full-width chars take 2 columns). */
function charWidth(ch: string): number {
  const code = ch.codePointAt(0)!
  if (code >= 0x1100 && (
    code <= 0x115f || // Hangul Jamo
    code === 0x2329 || code === 0x232a ||
    (code >= 0x2e80 && code <= 0xa4cf && code !== 0x303f) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe10 && code <= 0xfe19) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6) ||
    (code >= 0x1f300 && code <= 0x1faff) ||
    (code >= 0x20000 && code <= 0x3fffd)
  )) return 2
  return 1
}

function eraseChars(count: number) {
  if (!terminal) return
  for (let i = 0; i < count; i++) terminal.write('\b \b')
}

function replaceInputBuffer(value: string) {
  if (!terminal) return
  // Erase current input, accounting for wide (CJK) characters.
  const chars = [...commandBuffer]
  let cols = 0
  for (const ch of chars) cols += charWidth(ch)
  eraseChars(cols)
  commandBuffer = value
  terminal.write(value)
}

function recallCommand(direction: number) {
  if (!commandHistory.length) return
  // Preserve the user's in-progress draft on the first arrow press.
  if (historyCursor === -1) pendingDraft = commandBuffer
  historyCursor += direction < 0 ? 1 : -1
  if (historyCursor < 0) {
    historyCursor = -1
    replaceInputBuffer(pendingDraft)
    pendingDraft = ''
    return
  }
  if (historyCursor >= commandHistory.length) historyCursor = commandHistory.length - 1
  replaceInputBuffer(commandHistory[historyCursor])
}

function promptText(): string {
  return '\x1b[32m> \x1b[0m'
}

function autocompleteCommand() {
  const token = commandBuffer.trimStart().toLowerCase()
  if (!token) return
  const candidates = [...commandHistory, ...commandDictionary]
  const match = candidates.find(command => command.toLowerCase().startsWith(token))
  if (match && match !== commandBuffer) replaceInputBuffer(match)
}

let lastSubmitted = ''

async function submitCommand(command: string) {
  const trimmed = command.trim()
  if (!trimmed) return
  lastSubmitted = trimmed
  // 原样发送：/xxx 走服务器命令、其余自动作为聊天，路由统一由后端处理
  await store.sendInput(props.instanceId, trimmed)
  saveCommand(trimmed)
  connState.value = { text: 'sent', color: '#00ff41' }
}

function handleTerminalInput(data: string) {
  if (!terminal) return
  if (data === '\r') {
    const command = commandBuffer.trim()
    terminal.write('\r\n')
    commandBuffer = ''
    historyCursor = -1
    pendingDraft = ''
    if (command) void submitCommand(command)
    terminal.write(promptText())
    return
  }
  if (data === '\u007F') {
    const chars = [...commandBuffer]
    if (chars.length > 0) {
      const last = chars[chars.length - 1]
      commandBuffer = chars.slice(0, -1).join('')
      eraseChars(charWidth(last))
    }
    return
  }
  if (data === '\t') {
    autocompleteCommand()
    return
  }
  if (data === '\x1b[A') {
    recallCommand(-1)
    return
  }
  if (data === '\x1b[B') {
    recallCommand(1)
    return
  }
  if (data >= ' ' && !data.startsWith('\x1b')) {
    commandBuffer += data
    terminal.write(data)
  }
}

function formatLine(line: MccTerminalLine): string {
  if (line.stream === 'stdin') {
    // 输入行（仅其他观察者可见，本机已本地回显）：弱化前缀与时间戳
    return `\x1b[36m> ${line.content.replace(/^>\s*/, '')}\x1b[0m`
  }
  const time = line.created_at ? new Date(line.created_at).toLocaleTimeString() : '--:--:--'
  const streamColor = line.stream === 'stderr' ? '\x1b[31m' : '\x1b[90m'
  return `\x1b[90m[${time}]\x1b[0m ${streamColor}[${line.stream}]\x1b[0m ${line.content}`
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
  terminal.write('\r\n\x1b[32m> \x1b[0m' + commandBuffer)
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
      terminal?.write(promptText() + commandBuffer)
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
    terminal.write(promptText() + commandBuffer)
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
  terminal?.write('\x1b[32m> \x1b[0m' + commandBuffer)
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
  commandBuffer = ''
  pendingDraft = ''
  joinRetries = 0
  loadCommandHistory()
  // Clear terminal display for new instance
  if (terminal) {
    terminal.clear()
    terminal.writeln('\x1b[32mVMTools MCC Web Terminal\x1b[0m')
    terminal.write('\r\n' + promptText())
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
.xterm-shell { width: 100%; min-height: 260px; padding: 8px; background: #000; border: 1px solid var(--border-card); overflow: hidden; touch-action: none; }
.terminal-status { display: flex; justify-content: space-between; gap: 12px; color: var(--text-muted); font-size: 12px; }
.conn-state { display: inline-flex; align-items: center; gap: 6px; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.search-icon-btn { cursor: pointer; padding: 2px; margin-left: 4px; }
.search-icon-btn:hover { color: var(--green-primary); }
:deep(.xterm) { height: 100%; }
:deep(.xterm-viewport) { scrollbar-color: var(--green-primary) #000; }
:deep(.xterm-screen) { text-shadow: 0 0 6px rgba(0, 255, 65, .28); }

/* ============ RESPONSIVE ============ */
@media (max-width: 768px) {
  .terminal-toolbar { gap: 6px; }
  .search-input { width: 100%; flex-basis: 100%; }
  .terminal-toolbar .pixel-btn { font-size: 12px; padding: 6px 10px; min-height: 36px; }
  .terminal-status { font-size: 10px; gap: 6px; flex-wrap: wrap; }
  .xterm-shell { min-height: 200px; }
}
</style>
