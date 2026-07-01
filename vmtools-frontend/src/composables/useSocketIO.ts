import { io, Socket } from 'socket.io-client'
import { useBotStore } from '@/stores/bot'
import { useWarehouseStore } from '@/stores/warehouse'
import { useBuildStore } from '@/stores/build'
import { useLogisticsStore } from '@/stores/logistics'
import { useMonitorStore } from '@/stores/monitor'
import { ElNotification } from 'element-plus'

let socket: Socket | null = null

export function useSocketIO() {
  function connect() {
    if (socket?.connected) return

    socket = io(window.location.origin, {
      transports: ['websocket', 'polling'],
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

  return { connect, disconnect, emit }
}
