import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface OnlinePlayer {
  name: string
  uuid: string
  world: string
  foreign: boolean
  position: { x: number; y: number; z: number } | null
  rotation: { pitch: number; yaw: number; roll: number } | null
}

export interface PlayerEvent {
  name: string
  event: 'join' | 'leave'
  world: string
  position?: { x: number; y: number; z: number } | null
}

const WORLD_LABELS: Record<string, string> = {
  world: '主世界',
  world_nether: '地狱',
  world_the_end: '末地',
}

export const useOnlinePlayersStore = defineStore('onlinePlayers', () => {
  const players = ref<OnlinePlayer[]>([])
  const events = ref<(PlayerEvent & { time: number })[]>([])
  const lastUpdate = ref(0)

  const count = computed(() => players.value.length)
  const byWorld = computed(() => {
    const map: Record<string, OnlinePlayer[]> = {}
    for (const p of players.value) {
      if (!p.foreign) {
        const key = p.world
        if (!map[key]) map[key] = []
        map[key].push(p)
      }
    }
    return map
  })

  const worldLabels = computed(() => WORLD_LABELS)

  function setPlayers(list: OnlinePlayer[]) {
    players.value = list
    lastUpdate.value = Date.now()
  }

  function addEvent(ev: PlayerEvent) {
    events.value.unshift({ ...ev, time: Date.now() })
    // Keep only last 100 events
    if (events.value.length > 100) {
      events.value = events.value.slice(0, 100)
    }
  }

  function getWorldLabel(worldId: string): string {
    return WORLD_LABELS[worldId] || worldId
  }

  return {
    players,
    events,
    lastUpdate,
    count,
    byWorld,
    worldLabels,
    setPlayers,
    addEvent,
    getWorldLabel,
  }
})
