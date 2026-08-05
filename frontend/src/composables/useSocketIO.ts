import { io, Socket } from 'socket.io-client'
import { useBotStore } from '@/stores/bot'
import { useWarehouseStore } from '@/stores/warehouse'
import { useBuildStore } from '@/stores/build'
import { useLogisticsStore } from '@/stores/logistics'
import { useMonitorStore } from '@/stores/monitor'
import { useMccInstanceStore } from '@/stores/mccInstance'
import { useOnlinePlayersStore } from '@/stores/onlinePlayers'
import { useAuthStore } from '@/stores/auth'
import { ElNotification } from 'element-plus'

let socket: Socket | null = null

export function useSocketIO() {
  function connect() {
    if (socket?.connected) return

    const authStore = useAuthStore()
    socket = io(window.location.origin, {
      transports: ['websocket', 'polling'],
      auth: { token: authStore.token || '' },
    })

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

    // Build progress
    socket.on('build_progress', (payload) => {
      const buildStore = useBuildStore()
      buildStore.updateTaskFromSocket(payload)
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

    // Alerts
    socket.on('alert', (payload) => {
      const monitorStore = useMonitorStore()
      monitorStore.pushAlert(payload)
      ElNotification({
        title: '系统告警',
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
    socket?.emit(event, data)
  }

  function on(event: string, handler: (...args: any[]) => void) {
    socket?.on(event, handler)
  }

  function off(event: string, handler?: (...args: any[]) => void) {
    socket?.off(event, handler)
  }

  function getSocket() {
    return socket
  }

  const connected = () => socket?.connected ?? false

  return { connect, disconnect, emit, on, off, connected, getSocket }
}