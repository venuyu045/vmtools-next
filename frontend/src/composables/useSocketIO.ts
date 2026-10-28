import { io, Socket } from 'socket.io-client'
import { useBotStore } from '@/stores/bot'
import { useWarehouseStore } from '@/stores/warehouse'
import { useMapArtStore } from '@/stores/mapArt'
import { useLogisticsStore } from '@/stores/logistics'
import { useMonitorStore } from '@/stores/monitor'
import { useMccInstanceStore } from '@/stores/mccInstance'
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'
import { useAuthStore } from '@/stores/auth'
import { ElNotification } from 'element-plus'

let socket: Socket | null = null

type SocketHandler = (...args: any[]) => void

/**
 * 组件级 handler 注册表（与 socket 实例解耦）。
 *
 * 原实现 `on()` 直接 `socket?.on`：深链进入 / 未登录 / 断线重建时 socket 可能
 * 还没创建或已被销毁 → 监听被**静默丢弃**，该事件从此永久收不到
 * （索引 §8.2 A4 的同类根因；`disconnect()` 后重新登录也会踩到）。
 * 现在改为「先登记、建连时补挂」，`off()` 同步从注册表移除。
 */
const handlerRegistry = new Map<string, Set<SocketHandler>>()

/** 已被忽略过 emit 的事件名（控制台告警去重） */
const warnedEvents = new Set<string>()

/** 登记 handler；已登记过返回 false（防同一 handler 被挂两次 → 事件重复处理） */
function rememberHandler(event: string, handler: SocketHandler): boolean {
  let set = handlerRegistry.get(event)
  if (!set) {
    set = new Set()
    handlerRegistry.set(event, set)
  }
  if (set.has(handler)) return false
  set.add(handler)
  return true
}

/** 把注册表里所有 handler 补挂到新 socket 实例上 */
function attachAllHandlers(sock: Socket) {
  for (const [event, set] of handlerRegistry) {
    for (const handler of set) sock.on(event, handler)
  }
}

export function useSocketIO() {
  function connect() {
    if (socket?.connected) return

    // Reuse an existing (disconnected) instance instead of recreating it:
    // recreating via io() drops every component-level handler registered on
    // the old instance (e.g. mcc_terminal_snapshot), which makes terminal
    // join handshakes time out even though the backend responds normally.
    if (socket) {
      socket.connect()
      return
    }

    const authStore = useAuthStore()
    socket = io(window.location.origin, {
      transports: ['websocket', 'polling'],
      auth: { token: authStore.token || '' },
    })

    // 建连后补挂此前登记过的组件 handler（深链场景下 on() 早于建连）
    attachAllHandlers(socket)

    socket.on('connect', () => {
      console.log('[SIO] connected')
    })

    socket.on('disconnect', (reason) => {
      console.log('[SIO] disconnected:', reason)
    })

    // Bot updates
    socket.on('bot_status_update', (payload) => {
      const botStore = useBotStore()
      botStore.updateBotFromSocket(payload)
    })

    socket.on('bot_connected', (payload) => {
      const botStore = useBotStore()
      botStore.updateBotFromSocket({ bot_id: payload.bot_id, status: 'online' })
    })

    socket.on('bot_disconnected', (payload) => {
      const botStore = useBotStore()
      botStore.updateBotFromSocket({ bot_id: payload.bot_id, status: 'offline' })
    })

    // Task progress
    socket.on('task_progress', (payload) => {
      const logisticsStore = useLogisticsStore()
      logisticsStore.updateRunFromSocket(payload)
    })

    socket.on('task_log', (payload) => {
      console.log('[SIO] task_log:', payload)
    })

    socket.on('task_completed', (payload) => {
      const logisticsStore = useLogisticsStore()
      logisticsStore.updateRunFromSocket({ run_id: payload.run_id, status: payload.status })
      ElNotification({
        title: '任务完成',
        message: `任务 ${payload.run_id} 已完成`,
        type: 'success',
      })
    })

    // Build progress（地图画建造任务进度）
    socket.on('build_progress', (payload) => {
      const mapArtStore = useMapArtStore()
      mapArtStore.updateFromSocket(payload)
    })

    // Scan progress
    socket.on('scan_progress', (payload) => {
      console.log('[SIO] scan_progress:', payload)
    })

    // MCC remote instance updates
    socket.on('mcc_instance_status', (payload) => {
      const mccStore = useMccInstanceStore()
      mccStore.updateInstanceStatus(payload.instance_id, payload)
    })

    socket.on('mcc_terminal_output', (payload) => {
      const mccStore = useMccInstanceStore()
      mccStore.pushTerminalLine(payload)
    })

    socket.on('mcc_terminal_snapshot', (payload) => {
      const mccStore = useMccInstanceStore()
      if (payload?.instance_id && Array.isArray(payload.items)) {
        mccStore.mergeTerminalLines(payload.instance_id, payload.items)
      }
    })

    // Metrics
    socket.on('metrics_update', (payload) => {
      const monitorStore = useMonitorStore()
      monitorStore.pushMetric(payload)
    })

    // Monitor processes snapshot
    socket.on('monitor_processes', (payload) => {
      const monitorStore = useMonitorStore()
      monitorStore.pushProcesses(payload)
    })

    // Alerts（告警事件时间线 + 浏览器通知）
    socket.on('alert', (payload) => {
      const monitorStore = useMonitorStore()
      monitorStore.pushAlertEvent(payload)
      ElNotification({
        title: `系统告警·${payload.severity}`,
        message: payload.message,
        type: payload.severity === 'critical' ? 'error' : 'warning',
      })
    })

    // Sync update
    socket.on('sync_update', (payload) => {
      if (payload.bots) {
        const botStore = useBotStore()
        botStore.bots = payload.bots
      }
    })

    // BlueMap online players (from BlueMap API polling)
    socket.on('online_players_update', (payload) => {
      const playerStore = useOnlinePlayersStore()
      if (payload?.players) {
        playerStore.setPlayers(payload.players)
      }
    })

    socket.on('player_event', (payload) => {
      const playerStore = useOnlinePlayersStore()
      if (payload?.name && payload?.event) {
        playerStore.addEvent({
          name: payload.name,
          event: payload.event,
          world: payload.world || '',
          position: payload.position,
          residence: payload.residence,
          region: payload.region,
        })
      }
    })

    // BlueMap marker caches (slow poll, 60s)
    socket.on('regions_update', (payload) => {
      if (payload?.regions) {
        useOnlinePlayersStore().setRegions(payload.regions)
      }
    })

    socket.on('residences_update', (payload) => {
      if (payload?.residences) {
        useOnlinePlayersStore().setResidences(payload.residences)
      }
    })

    socket.on('markers_update', (payload) => {
      if (payload?.markers) {
        useOnlinePlayersStore().setMarkers(payload.markers)
      }
    })

    // BlueMap new marker sets: landmarks / metro lines / metro stations
    socket.on('landmarks_update', (payload) => {
      if (payload?.landmarks) {
        useOnlinePlayersStore().setLandmarks(payload.landmarks)
      }
    })

    socket.on('metro_lines_update', (payload) => {
      if (payload?.metro_lines) {
        useOnlinePlayersStore().setMetroLines(payload.metro_lines)
      }
    })

    socket.on('metro_stations_update', (payload) => {
      if (payload?.metro_stations) {
        useOnlinePlayersStore().setMetroStations(payload.metro_stations)
      }
    })
  }

  function disconnect() {
    if (socket) {
      socket.disconnect()
      socket = null
    }
  }

  function emit(event: string, data?: any) {
    if (!socket) {
      // 不静默丢弃：深链 / 未登录时 socket 可能还没建，调用方应先用 connectAsync() 确保建连
      // （同一事件只告警一次，避免终端逐键输入把控制台刷满）
      if (!warnedEvents.has(event)) {
        warnedEvents.add(event)
        console.warn(`[SIO] emit('${event}') 被忽略：socket 尚未创建（请先 connect/connectAsync）`)
      }
      return
    }
    socket.emit(event, data)
  }

  function on(event: string, handler: SocketHandler) {
    if (!rememberHandler(event, handler)) return
    socket?.on(event, handler)
  }

  function off(event: string, handler?: SocketHandler) {
    const set = handlerRegistry.get(event)
    if (!handler) {
      // 不传 handler：注销该事件的全部组件监听
      if (set) {
        for (const h of set) socket?.off(event, h)
        set.clear()
      }
      return
    }
    set?.delete(handler)
    socket?.off(event, handler)
  }

  function getSocket() {
    return socket
  }

  const connected = () => socket?.connected ?? false

  /**
   * 确保 socket 已建连（修 A4：深链进入时 emit 前必须先建连，否则 join 事件被丢弃）。
   *
   * - 已连接 → 立即 resolve(true)
   * - 否则调用 connect() 并等待 connect 事件；connect_error / 超时 → resolve(false)
   *   （socket.io 自带自动重连，调用方据 false 给出可见提示即可，不必自己重试）
   */
  function connectAsync(timeoutMs = 8000): Promise<boolean> {
    if (socket?.connected) return Promise.resolve(true)
    connect()
    const sock = socket
    if (!sock) return Promise.resolve(false)
    if (sock.connected) return Promise.resolve(true)
    return new Promise<boolean>((resolve) => {
      let settled = false
      let timer: number | undefined
      const finish = (ok: boolean) => {
        if (settled) return
        settled = true
        if (timer !== undefined) window.clearTimeout(timer)
        sock.off('connect', onConnect)
        sock.off('connect_error', onConnectError)
        resolve(ok)
      }
      const onConnect = () => finish(true)
      const onConnectError = () => finish(false)
      timer = window.setTimeout(() => finish(false), timeoutMs)
      sock.on('connect', onConnect)
      sock.on('connect_error', onConnectError)
    })
  }

  return { connect, connectAsync, disconnect, emit, on, off, connected, getSocket }
}
