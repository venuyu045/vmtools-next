import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface ResidenceInfo {
  name: string
  owner: string
  area: number
}

export interface RegionInfo {
  label: string
  tps: number | null
  mspt: number | null
  entities: number | null
  players_in_region: number | null
  chunks: number | null
  sections: number | null
}

export interface OnlinePlayer {
  name: string
  uuid: string
  world: string
  foreign: boolean
  position: { x: number; y: number; z: number } | null
  rotation: { pitch: number; yaw: number; roll: number } | null
  residence: ResidenceInfo | null
  region: RegionInfo | null
}

export interface PlayerEvent {
  name: string
  event: 'join' | 'leave'
  world: string
  position?: { x: number; y: number; z: number } | null
  residence?: ResidenceInfo | null
  region?: RegionInfo | null
}

export interface ResidenceEntry {
  id: string
  label: string
  owner: string
  area: number
  min_y: number
  max_y: number
  shape: { x: number; z: number }[]
  position: { x: number; y: number; z: number } | null
  type: string
}

export interface RegionEntry {
  id: string
  label: string
  shape: { x: number; z: number }[]
  shape_y: number
  tps: number | null
  mspt: number | null
  entities: number | null
  players_in_region: number | null
  chunks: number | null
  sections: number | null
  position: { x: number; y: number; z: number } | null
}

export interface MarkerEntry {
  id: string
  label: string
  position: { x: number; y: number; z: number } | null
  type: string
  detail: string
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

  // Cached marker data from slow poll
  const residences = ref<ResidenceEntry[]>([])
  const regions = ref<RegionEntry[]>([])
  const markers = ref<MarkerEntry[]>([])

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

  // Residence rankings by area
  const residenceRankings = computed(() => {
    return [...residences.value]
      .filter(r => r.area > 0)
      .sort((a, b) => b.area - a.area)
  })

  // Region rankings by MSPT (lower is better performance)
  const regionRankings = computed(() => {
    return [...regions.value]
      .filter(r => r.mspt != null && r.mspt > 0)
      .sort((a, b) => (a.mspt ?? 999) - (b.mspt ?? 999))
  })

  // ── Point-in-polygon helper (ray casting) ──
  function pointInPolygon(px: number, pz: number, polygon: { x: number; z: number }[]): boolean {
    if (!polygon || polygon.length < 3) return false
    let inside = false
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const xi = polygon[i].x, zi = polygon[i].z
      const xj = polygon[j].x, zj = polygon[j].z
      if ((zi > pz) !== (zj > pz) && px < ((xj - xi) * (pz - zi)) / (zj - zi) + xi) {
        inside = !inside
      }
    }
    return inside
  }

  // Map region id → residence labels whose position falls within the region polygon
  const regionResidences = computed(() => {
    const map: Record<string, string[]> = {}
    for (const region of regions.value) {
      const labels: string[] = []
      if (region.shape && region.shape.length >= 3) {
        for (const res of residences.value) {
          if (res.position) {
            if (pointInPolygon(res.position.x, res.position.z, region.shape)) {
              labels.push(res.label)
            }
          }
        }
      }
      map[region.id] = labels
    }
    return map
  })

  // Map region label → online player names currently in that region
  const regionOnlinePlayers = computed(() => {
    const map: Record<string, string[]> = {}
    for (const p of players.value) {
      if (p.region?.label) {
        const rl = p.region.label
        if (!map[rl]) map[rl] = []
        map[rl].push(p.name)
      }
    }
    return map
  })

  // Group residences by owner
  const ownerRankings = computed(() => {
    const map: Record<string, { owner: string; count: number; totalArea: number }> = {}
    for (const r of residences.value) {
      const owner = r.owner || '未知'
      if (!map[owner]) map[owner] = { owner, count: 0, totalArea: 0 }
      map[owner].count++
      map[owner].totalArea += r.area
    }
    return Object.values(map).sort((a, b) => b.totalArea - a.totalArea)
  })

  function setPlayers(list: OnlinePlayer[]) {
    players.value = list
    lastUpdate.value = Date.now()
  }

  function setResidences(list: ResidenceEntry[]) {
    residences.value = list
  }

  function setRegions(list: RegionEntry[]) {
    regions.value = list
  }

  function setMarkers(list: MarkerEntry[]) {
    markers.value = list
  }

  function addEvent(ev: PlayerEvent) {
    events.value.unshift({ ...ev, time: Date.now() })
    if (events.value.length > 100) {
      events.value = events.value.slice(0, 100)
    }
  }

  function getWorldLabel(worldId: string): string {
    return WORLD_LABELS[worldId] || worldId
  }

  return {
    players, events, lastUpdate, count, byWorld, worldLabels,
    residences, regions, markers,
    residenceRankings, ownerRankings, regionRankings,
    regionResidences, regionOnlinePlayers,
    setPlayers, setResidences, setRegions, setMarkers,
    addEvent, getWorldLabel,
  }
})
