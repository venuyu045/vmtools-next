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
      />
      <button class="pixel-btn outline" @click="findPrevious">上一个</button>
      <button class="pixel-btn outline" @click="findNext">下一个</button>
      <el-select v-model="inputMode" class="mode-select" size="small">
        <el-option label="命令模式" value="command" />
        <el-option label="聊天模式" value="chat" />
      </el-select>
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
      <span>{{ connectionHint }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { Unicode11Addon } from '@xterm/addon-unicode11'
import '@xterm/xterm/css/xterm.css'
import { useMccInstanceStore } from '@/stores/mccInstance'
import { useSocketIO } from '@/composables/useSocketIO'
import type { MccTerminalLine } from '@/api/mccInstance'

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
  tailLines: 800,
})

const store = useMccInstanceStore()
const socket = useSocketIO()
const terminalContainer = ref<HTMLElement | null>(null)
const searchKeyword = ref('')
const inputMode = ref<'command' | 'chat'>('command')
const autoScroll = ref(true)
const connectionHint = ref('ready')
const lineCount = computed(() => terminalLines.value.length)
const terminalLines = computed(() => store.terminalLines[props.instanceId] || [])

let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let searchAddon: SearchAddon | null = null
let resizeObserver: ResizeObserver | null = null
let lastSeq = 0
let commandBuffer = ''
let historyCursor = -1
let commandHistory: string[] = []

const commandDictionary = [
  'help', 'status', 'exit', 'connect', 'disconnect', 'respawn', 'inventory', 'move',
  'login', 'logout', 'reco', 'script', 'send', 'say', 'list', 'look', 'dig', 'place', 'useitem', 'drop', 'dropall', 'hotbar', 'health', 'food', 'position', 'players', 'terrain', 'help settings', 'set', 'reload', 'quit', '/help', '/list', '/tell', '/msg', '/tpaccept', '/spawn', '/home', '/back']


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
  terminal.onData(handleTerminalInput)
  terminal.writeln('\x1b[32mVMTools MCC Web Terminal\x1b[0m')
  terminal.writeln('\x1b[90mCommand mode sends MCC/internal commands. Chat mode prefixes text with say.\x1b[0m')
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

function replaceInputBuffer(value: string) {
  if (!terminal) return
  while (commandBuffer.length > 0) {
    terminal.write('\b \b')
    commandBuffer = commandBuffer.slice(0, -1)
  }
  commandBuffer = value
  terminal.write(value)
}

function recallCommand(direction: number) {
  if (!commandHistory.length) return
  historyCursor += direction < 0 ? 1 : -1
  if (historyCursor < 0) {
    historyCursor = -1
    replaceInputBuffer('')
    return
  }
  if (historyCursor >= commandHistory.length) historyCursor = commandHistory.length - 1
  replaceInputBuffer(commandHistory[historyCursor])
}

function promptText(): string {
  return inputMode.value === 'chat' ? '\x1b[35mchat> \x1b[0m' : '\x1b[32m> \x1b[0m'
}

function autocompleteCommand() {
  const token = commandBuffer.trimStart().toLowerCase()
  if (!token) return
  const candidates = [...commandHistory, ...commandDictionary]
  const match = candidates.find(command => command.toLowerCase().startsWith(token))
  if (match && match !== commandBuffer) replaceInputBuffer(match)
}

function normalizeCommand(command: string): string {
  const trimmed = command.trim()
  if (inputMode.value === 'chat' && trimmed && !trimmed.startsWith('/') && !trimmed.startsWith('say ')) {
    return `say ${trimmed}`
  }
  return trimmed
}

async function submitCommand(command: string) {
  const normalized = normalizeCommand(command)
  if (!normalized) return
  try {
    await store.sendInput(props.instanceId, normalized)
    saveCommand(command.trim())
    connectionHint.value = 'sent'
  } catch (error: any) {
    connectionHint.value = 'send failed'
    ElMessage.error(error.response?.data?.detail || '命令发送失败')
  }
}

function handleTerminalInput(data: string) {
  if (!terminal) return
  if (data === '\r') {
    const command = commandBuffer.trim()
    terminal.write('\r\n')
    void submitCommand(command)
    commandBuffer = ''
    historyCursor = -1
    terminal.write(promptText())
    return
  }
  if (data === '\u007F') {
    if (commandBuffer.length > 0) {
      commandBuffer = commandBuffer.slice(0, -1)
      terminal.write('\b \b')
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
  const time = line.created_at ? new Date(line.created_at).toLocaleTimeString() : '--:--:--'
  const streamColor = line.stream === 'stderr' ? '\x1b[31m' : line.stream === 'stdin' ? '\x1b[36m' : '\x1b[90m'
  return `\x1b[90m[${time}]\x1b[0m ${streamColor}[${line.stream}]\x1b[0m ${line.content}`
}

function renderAllLines() {
  if (!terminal) { console.warn('[Terminal] renderAllLines: terminal is null'); return }
  const count = terminalLines.value.length
  console.log('[Terminal] renderAllLines: rendering', count, 'lines, lastSeq was', lastSeq)
  terminal.clear()
  lastSeq = 0
  for (const line of terminalLines.value) {
    terminal.writeln(formatLine(line))
    lastSeq = Math.max(lastSeq, line.seq)
  }
  terminal.write('\r\n\x1b[32m> \x1b[0m' + commandBuffer)
  if (autoScroll.value) terminal.scrollToBottom()
  console.log('[Terminal] renderAllLines: done, lastSeq =', lastSeq)
}

function appendNewLines(lines: MccTerminalLine[]) {
  if (!terminal) {
    console.warn('[Terminal] appendNewLines: terminal is null, queueing', lines.length, 'lines')
    return
  }
  const nextLines = lines.filter(line => line.seq > lastSeq)
  if (!nextLines.length) return
  console.log('[Terminal] appendNewLines: writing', nextLines.length, 'new lines (seq >', lastSeq, ')')
  for (const line of nextLines) {
    terminal.writeln(formatLine(line))
    lastSeq = Math.max(lastSeq, line.seq)
  }
  terminal.write('\x1b[32m> \x1b[0m' + commandBuffer)
  if (autoScroll.value) terminal.scrollToBottom()
}

async function joinTerminalRoom() {
  socket.connect()
  socket.emit('mcc_join_instance', { instance_id: props.instanceId, tail_lines: props.tailLines })
  connectionHint.value = 'joined room'
}

function leaveTerminalRoom() {
  socket.emit('mcc_leave_instance', { instance_id: props.instanceId })
}

async function reloadHistory() {
  console.log('[Terminal] reloadHistory: fetching history...')
  await store.fetchTerminalHistory(props.instanceId)
  const count = terminalLines.value.length
  console.log('[Terminal] reloadHistory: received', count, 'lines')
  if (count > 0) {
    renderAllLines()
  } else {
    console.warn('[Terminal] reloadHistory: no lines to render')
  }
  connectionHint.value = 'history reloaded'
}

function fitTerminal() {
  try {
    fitAddon?.fit()
  } catch {
    // Ignore fit errors while the drawer/page is still animating.
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

function downloadLog() {
  const content = terminalLines.value
    .map(line => `[${line.created_at}] [${line.stream}] ${line.content.replace(/\x1b\[[0-9;]*m/g, '')}`)
    .join('\n')
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.slug || props.instanceId}-terminal.log`
  link.click()
  URL.revokeObjectURL(url)
}

watch(terminalLines, (lines) => {
  const newLines = lines.filter(l => l.seq > lastSeq)
  // If a large batch arrived at once (snapshot or history), do a full re-render
  if (newLines.length > 10 && terminal) {
    console.log('[Terminal] watch: large batch detected (', newLines.length, 'lines), re-rendering all')
    renderAllLines()
  } else {
    appendNewLines(lines)
  }
}, { deep: true })
watch(() => props.instanceId, async () => {
  lastSeq = 0
  commandBuffer = ''
  loadCommandHistory()
  await joinTerminalRoom()
  await reloadHistory()
})

onMounted(async () => {
  initTerminal()
  loadCommandHistory()
  await joinTerminalRoom()
  await reloadHistory()
})

onBeforeUnmount(() => {
  leaveTerminalRoom()
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
.xterm-shell { width: 100%; min-height: 260px; padding: 8px; background: #000; border: 1px solid var(--border-card); overflow: hidden; }
.terminal-status { display: flex; justify-content: space-between; gap: 12px; color: var(--text-muted); font-size: 12px; }
:deep(.xterm) { height: 100%; }
:deep(.xterm-viewport) { scrollbar-color: var(--green-primary) #000; }
:deep(.xterm-screen) { text-shadow: 0 0 6px rgba(0, 255, 65, .28); }
</style>
