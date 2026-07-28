/** BuildMapScene — Three.js 3D scene for map art construction visualization.
 *
 * Key optimizations (per implementation-plan.md Section 6):
 *   - InstancedMesh groups same-colored blocks → 20 meshes vs 16384
 *   - Incremental updates: only changed instances per frame
 *   - Frustum culling: automatic via Three.js
 */

import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

// ---- Minecraft wool → hex color mapping ----
const WOOL_COLORS: Record<string, number> = {
  'minecraft:white_wool': 0xffffff,
  'minecraft:orange_wool': 0xf9801d,
  'minecraft:magenta_wool': 0xc74ebd,
  'minecraft:light_blue_wool': 0x3ab3da,
  'minecraft:yellow_wool': 0xfed83d,
  'minecraft:lime_wool': 0x80c71f,
  'minecraft:pink_wool': 0xf38baa,
  'minecraft:gray_wool': 0x474f52,
  'minecraft:light_gray_wool': 0x9d9d97,
  'minecraft:cyan_wool': 0x169c9d,
  'minecraft:purple_wool': 0x8932b8,
  'minecraft:blue_wool': 0x3c44aa,
  'minecraft:brown_wool': 0x835432,
  'minecraft:green_wool': 0x5e7c16,
  'minecraft:red_wool': 0xb02e26,
  'minecraft:black_wool': 0x1d1d21,
}

const CONCRETE_COLORS: Record<string, number> = {
  'minecraft:white_concrete': 0xcfd5d6,
  'minecraft:orange_concrete': 0xe06300,
  'minecraft:magenta_concrete': 0xa9309f,
  'minecraft:light_blue_concrete': 0x2489c7,
  'minecraft:yellow_concrete': 0xf0b017,
  'minecraft:lime_concrete': 0x5ea818,
  'minecraft:pink_concrete': 0xd5658e,
  'minecraft:gray_concrete': 0x35383d,
  'minecraft:light_gray_concrete': 0x7e7975,
  'minecraft:cyan_concrete': 0x14778a,
  'minecraft:purple_concrete': 0x632e9c,
  'minecraft:blue_concrete': 0x2c2e8c,
  'minecraft:brown_concrete': 0x5e4022,
  'minecraft:green_concrete': 0x47571c,
  'minecraft:red_concrete': 0x8a2125,
  'minecraft:black_concrete': 0x0a0a11,
}

const ALL_COLORS: Record<string, number> = { ...WOOL_COLORS, ...CONCRETE_COLORS }

// ---- Types ----
export interface BlockState {
  x: number; y: number; z: number
  expected: string
  actual: string
  placed: boolean
  verified: boolean
}

export interface BotMarker {
  bot_id: string
  name: string
  x: number; y: number; z: number
  color: string
  state: string
  region: { x_start: number; x_end: number; z_start: number; z_end: number }
}

export interface MapInitData {
  task_id: string
  blocks: BlockState[]
  bots: BotMarker[]
  origin: { x: number; y: number; z: number }
  size: { x: number; z: number }
}

// ---- Scene Manager ----
export class BuildMapScene {
  private scene: THREE.Scene
  private camera: THREE.PerspectiveCamera
  private renderer: THREE.WebGLRenderer
  private controls: OrbitControls

  // InstancedMesh per block type (key = block_id or "unplaced")
  private blockMeshes = new Map<string, { mesh: THREE.InstancedMesh; count: number }>()
  private unplacedMesh: THREE.InstancedMesh | null = null
  private botMarkers = new Map<string, THREE.Mesh>()
  private regionOutlines: THREE.Line[] = []

  // Mapping for updates
  private blockIndexMap = new Map<string, { meshKey: string; instanceId: number }>() // "x,z" → ...

  private originX = 0
  private originY = 64
  private originZ = 0

  constructor(canvas: HTMLCanvasElement) {
    const w = canvas.clientWidth
    const h = canvas.clientHeight

    // Scene
    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(0x1a1a2e)

    // Camera — isometric-ish overview
    this.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000)
    this.camera.position.set(64, 120, -60)
    this.camera.lookAt(64, 64, 64)

    // Renderer
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    this.renderer.setSize(w, h)
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

    // Controls
    this.controls = new OrbitControls(this.camera, canvas)
    this.controls.target.set(64, 64, 64)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.1
    this.controls.maxPolarAngle = Math.PI / 2 + 0.3

    // Lighting
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.6))
    const dir = new THREE.DirectionalLight(0xffffff, 0.8)
    dir.position.set(64, 150, 64)
    this.scene.add(dir)
  }

  // ---- Initialization ----

  initialize(data: MapInitData): void {
    this.originX = data.origin.x
    this.originY = data.origin.y
    this.originZ = data.origin.z

    this.clearAll()
    this.addGrid(data.size.x, data.size.z)
    this.createBlocks(data.blocks)
    this.createBots(data.bots)
    this.createRegionOutlines(data.bots)

    // Focus camera
    const cx = data.origin.x + data.size.x / 2
    const cz = data.origin.z + data.size.z / 2
    this.controls.target.set(cx, data.origin.y, cz)
    this.camera.position.set(cx, data.origin.y + 80, cz - 40)
    this.camera.lookAt(cx, data.origin.y, cz)
  }

  // ---- Blocks ----

  private createBlocks(blocks: BlockState[]): void {
    // Group by expected block type (or "unplaced")
    const groups = new Map<string, BlockState[]>()
    for (const b of blocks) {
      const key = b.placed ? b.expected : 'unplaced'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(b)
    }

    const boxGeo = new THREE.BoxGeometry(0.9, 0.15, 0.9)
    const wireGeo = new THREE.EdgesGeometry(boxGeo)
    const dummy = new THREE.Object3D()

    for (const [key, group] of groups) {
      let mesh: THREE.InstancedMesh
      if (key === 'unplaced') {
        const mat = new THREE.MeshBasicMaterial({ color: 0x444444, transparent: true, opacity: 0.3, wireframe: true })
        mesh = new THREE.InstancedMesh(boxGeo, mat, group.length)
        this.unplacedMesh = mesh
      } else {
        const hex = ALL_COLORS[key] ?? this.blockIdToHex(key)
        const mat = new THREE.MeshPhongMaterial({ color: hex, specular: 0x111111, shininess: 10 })
        mesh = new THREE.InstancedMesh(boxGeo, mat, group.length)
      }

      group.forEach((b, i) => {
        dummy.position.set(b.x, b.y, b.z)
        dummy.updateMatrix()
        mesh.setMatrixAt(i, dummy.matrix)
        this.blockIndexMap.set(`${b.x},${b.z}`, { meshKey: key, instanceId: i })
      })

      mesh.instanceMatrix.needsUpdate = true
      this.scene.add(mesh)
      this.blockMeshes.set(key, { mesh, count: group.length })
    }
  }

  updateBlockPlaced(x: number, y: number, z: number, blockId: string): void {
    const key = `${x},${z}`
    const entry = this.blockIndexMap.get(key)
    if (!entry) return

    // Hide from unplaced mesh and add to placed mesh
    // Simplified: just change opacity via color
    if (entry.meshKey === 'unplaced' && this.unplacedMesh) {
      // Re-color the instance
      const hex = ALL_COLORS[blockId] ?? this.blockIdToHex(blockId)
      const color = new THREE.Color(hex)
      this.unplacedMesh.setColorAt(entry.instanceId, color)
      if (this.unplacedMesh.instanceColor) {
        this.unplacedMesh.instanceColor.needsUpdate = true
      }
    }
  }

  // ---- Bot markers ----

  private createBots(bots: BotMarker[]): void {
    for (const bot of bots) {
      this.addBotMarker(bot)
    }
  }

  private addBotMarker(bot: BotMarker): void {
    const geo = new THREE.SphereGeometry(0.6, 16, 16)
    const hex = parseInt(bot.color.replace('#', ''), 16)
    const mat = new THREE.MeshBasicMaterial({ color: hex })
    const marker = new THREE.Mesh(geo, mat)
    const cx = bot.region ? (bot.region.x_start + bot.region.x_end) / 2 : 0
    const cz = bot.region ? bot.region.z_start : 0
    marker.position.set(cx, this.originY + 2, cz)
    this.scene.add(marker)
    this.botMarkers.set(bot.bot_id, marker)
  }

  updateBotPosition(botId: string, x: number, y: number, z: number): void {
    const marker = this.botMarkers.get(botId)
    if (!marker) return
    marker.position.lerp(new THREE.Vector3(x, y + 1.5, z), 0.5)
  }

  // ---- Region outlines ----

  private createRegionOutlines(bots: BotMarker[]): void {
    for (const bot of bots) {
      if (!bot.region) continue
      const { x_start, x_end, z_start, z_end } = bot.region
      const y = this.originY - 0.2
      const hex = parseInt(bot.color.replace('#', ''), 16)
      const points = [
        new THREE.Vector3(x_start, y, z_start),
        new THREE.Vector3(x_end, y, z_start),
        new THREE.Vector3(x_end, y, z_end),
        new THREE.Vector3(x_start, y, z_end),
        new THREE.Vector3(x_start, y, z_start),
      ]
      const geo = new THREE.BufferGeometry().setFromPoints(points)
      const mat = new THREE.LineBasicMaterial({ color: hex, linewidth: 1 })
      this.scene.add(new THREE.Line(geo, mat))
    }
  }

  // ---- Grid ----

  private addGrid(w: number, d: number): void {
    const grid = new THREE.GridHelper(Math.max(w, d), 16, 0x444466, 0x222244)
    grid.position.set(w / 2, this.originY - 0.1, d / 2)
    this.scene.add(grid)
  }

  // ---- Helpers ----

  private blockIdToHex(blockId: string): number {
    const hash = blockId.split('').reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 0)
    return hash & 0xffffff
  }

  private clearAll(): void {
    this.blockMeshes.forEach(({ mesh }) => { mesh.geometry.dispose(); (mesh.material as THREE.Material).dispose(); this.scene.remove(mesh) })
    this.blockMeshes.clear()
    this.blockIndexMap.clear()
    this.botMarkers.forEach(m => { m.geometry.dispose(); (m.material as THREE.Material).dispose(); this.scene.remove(m) })
    this.botMarkers.clear()
    this.regionOutlines.forEach(l => { l.geometry.dispose(); (l.material as THREE.Material).dispose(); this.scene.remove(l) })
    this.regionOutlines = []
    this.unplacedMesh = null
  }

  // ---- Animation loop ----

  animate(): void {
    requestAnimationFrame(() => this.animate())
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  // ---- Resize ----

  onResize(w: number, h: number): void {
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
  }

  dispose(): void {
    this.clearAll()
    this.renderer.dispose()
  }
}
