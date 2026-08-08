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
  world?: string
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
  afk?: boolean
  bot_owner?: string | null
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
  world: string
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
  world: string
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
  world: string
  label: string
  position: { x: number; y: number; z: number } | null
  type: string
  detail: string
}

export interface LandmarkEntry {
  id: string
  world: string
  label: string
  position: { x: number; y: number; z: number } | null
  type: string
  detail: string
}

export interface MetroLineEntry {
  id: string
  world: string
  label: string
  line: { x: number; y: number; z: number }[]
  line_color?: string
  detail: string
  position: { x: number; y: number; z: number } | null
}

export interface MetroStationEntry {
  id: string
  world: string
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

// Bot owner groups (mirrors QQ /list): ordered display, owner → label
const BOT_OWNER_ORDER = ['venus', 'gxko', '快乐船', '其他']
const BOT_OWNER_LABELS: Record<string, string> = {
  venus: 'venus 的 bot',
  gxko: 'gxko 的 bot',
  '快乐船': '快乐船的 bot',
  '其他': '其他 bot',
}

export const useOnlinePlayersStore = defineStore('onlinePlayers', () => {
  const players = ref<OnlinePlayer[]>([])
  const events = ref<(PlayerEvent & { time: number })[]>([])
  const lastUpdate = ref(0)

  // Cached marker data from slow poll
  const residences = ref<ResidenceEntry[]>([])
  const regions = ref<RegionEntry[]>([])
  const markers = ref<MarkerEntry[]>([])
  const landmarks = ref<LandmarkEntry[]>([])
  const metroLines = ref<MetroLineEntry[]>([])
  const metroStations = ref<MetroStationEntry[]>([])

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

  // ── Bot classification (mirrors QQ /list) ──
  // Human players split by movement (AFK tracked server-side from position deltas)
  const humanPlayers = computed(() => players.value.filter(p => !p.bot_owner))
  const humanActive = computed(() => humanPlayers.value.filter(p => !p.afk))
  const humanAfk = computed(() => humanPlayers.value.filter(p => p.afk))
  // Bots grouped by owner (venus / gxko / 快乐船 / 其他)
  const botPlayers = computed(() => players.value.filter(p => p.bot_owner))
  const botGroups = computed(() => {
    const groups: { owner: string; label: string; players: OnlinePlayer[] }[] = []
    for (const owner of BOT_OWNER_ORDER) {
      const list = botPlayers.value.filter(p => p.bot_owner === owner)
      if (list.length) {
        groups.push({ owner, label: BOT_OWNER_LABELS[owner] || `${owner} 的 bot`, players: list })
      }
    }
    return groups
  })
  const botTotal = computed(() => botPlayers.value.length)

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

  // Residences grouped by world — speeds up region↔residence point-in-polygon
  // matching (only same-world pairs need testing).
  const residencesByWorld = computed(() => {
    const map: Record<string, ResidenceEntry[]> = {}
    for (const r of residences.value) {
      const w = r.world || 'world'
      if (!map[w]) map[w] = []
      map[w].push(r)
    }
    return map
  })

  // Map region id → residence labels whose position falls within the region polygon
  // (same-world only — nether/end shapes must not swallow overworld residences)
  const regionResidences = computed(() => {
    const map: Record<string, string[]> = {}
    for (const region of regions.value) {
      const labels: string[] = []
      const wRes = residencesByWorld.value[region.world || 'world'] || []
      if (region.shape && region.shape.length >= 3) {
        for (const res of wRes) {
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

  // Map region → online player names currently in that region.
  // Key uses world + label so same-named regions in different worlds don't merge.
  const regionOnlinePlayers = computed(() => {
    const map: Record<string, string[]> = {}
    for (const p of players.value) {
      if (p.region?.label) {
        const key = `${p.region.world || p.world || 'world'}|${p.region.label}`
        if (!map[key]) map[key] = []
        map[key].push(p.name)
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

  // Landmark groupings — by type (e.g. 地铁轻轨 / 商店金融 / 停车场 ...)
  const landmarkTypes = computed(() => {
    const map: Record<string, number> = {}
    for (const lm of landmarks.value) {
      const t = lm.type || '未分类'
      map[t] = (map[t] || 0) + 1
    }
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => ({ type, count }))
  })

  const landmarksByType = computed(() => {
    const map: Record<string, LandmarkEntry[]> = {}
    for (const lm of landmarks.value) {
      const t = lm.type || '未分类'
      if (!map[t]) map[t] = []
      map[t].push(lm)
    }
    return map
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

  function setLandmarks(list: LandmarkEntry[]) {
    landmarks.value = list
  }

  function setMetroLines(list: MetroLineEntry[]) {
    metroLines.value = list
  }

  function setMetroStations(list: MetroStationEntry[]) {
    metroStations.value = list
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
    humanPlayers, humanActive, humanAfk, botGroups, botTotal,
    residences, regions, markers, landmarks, metroLines, metroStations,
    residenceRankings, ownerRankings, regionRankings,
    landmarkTypes, landmarksByType,
    regionResidences, regionOnlinePlayers,
    setPlayers, setResidences, setRegions, setMarkers,
    setLandmarks, setMetroLines, setMetroStations,
    addEvent, getWorldLabel,
  }
})
