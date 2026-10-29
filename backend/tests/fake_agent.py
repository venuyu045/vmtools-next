"""FakeAgent —— 离线驱动地图画引擎的假 MCP 客户端。

为什么需要它：真 ``MineflayerClient`` 要连 Node 子进程（WebSocket + 真实服务器），
本机无法运行。``FakeAgent`` 实现 ``BotRuntime`` / ``place_cell`` / 两个引擎实际调用的
那部分方法，返回**与 ``adapters/mineflayer/mineflayer_client.py`` 一致的 dict 形态**
（``{"success": bool, "reason": str, ...}`` / ``{"data": {...}}``），并记录所有副作用，
供断言使用。

典型用法::

    from _stub_env import install
    install()
    from fake_agent import FakeAgent

    world = {}                                    # 多个 bot 共享一个服务器世界
    a, b = FakeAgent("mf-001", world=world), FakeAgent("mf-002", world=world)

    assert a.placed_cells() == {(101, 200)}       # 记录了哪些格被放过
    assert a.chats == ["/esethomes dth"]          # 聊天指令也记录了

模拟故障（可选，默认全成功）：
  - ``fail_place_cells``：``{(x, y, z): 剩余失败次数}`` —— 放置返回 success=False
  - ``weak_confirm_cells``：``{(x, y, z)}`` —— 放置返回成功但世界不更新（读到 air），
    走 ``_pending_confirm`` 弱确认分支
  - ``wrong_block_cells``：``{(x, y, z): "other_block"}`` —— 放置后世界读到别的方块
"""

from __future__ import annotations

AIR = "air"


class FakeAgent:
    """最小可用的 mineflayer 客户端替身（异步方法，返回 dict）。"""

    def __init__(
        self,
        bot_id: str = "fake-bot",
        held: str = "white_wool",
        world: dict | None = None,
        *,
        position: tuple[float, float, float] = (0.0, 64.0, 0.0),
        offhand_food: str | None = "cooked_porkchop",
    ):
        # 服务器世界：{(x, y, z): 方块名（无 minecraft: 前缀）}
        self.world: dict[tuple[int, int, int], str] = world if world is not None else {}
        self.bot_id = bot_id
        self.held = held
        self.position = list(position)
        # 副手食物：真 bot 上线后副手通常已有猪排；置 None 可模拟「副手空 → 走补货流程」
        self.offhand_food = offhand_food

        # ── 副作用记录 ──
        self.placed: list[tuple[int, int, int, str]] = []
        self.digs: list[tuple[int, int, int]] = []
        self.chats: list[str] = []
        self.moves: list[tuple[int, int, int]] = []
        self.controls: list[tuple[str, bool]] = []
        self.equips: list[str] = []
        self.events: list = []          # on_event 注册的回调

        # ── 故障注入 ──
        self.fail_place_cells: dict[tuple[int, int, int], int] = {}
        self.weak_confirm_cells: set[tuple[int, int, int]] = set()
        self.wrong_block_cells: dict[tuple[int, int, int], str] = {}

        # 真客户端的 place_block 默认 face 是 "UP"；引擎会显式传 "AUTO"
        self.last_status = {
            "position": {"x": self.position[0], "y": self.position[1], "z": self.position[2]},
            "health": 20,
            "food": 20,
        }

    # ──────────────────────────────────────────
    # 断言辅助
    # ──────────────────────────────────────────

    def placed_cells(self) -> set[tuple[int, int]]:
        """放过方块的水平坐标集合（去重）。"""
        return {(x, z) for x, _y, z, _b in self.placed}

    def placed_count(self) -> int:
        return len(self.placed)

    def world_at(self, x: int, y: int, z: int) -> str:
        return self.world.get((int(x), int(y), int(z)), AIR)

    # ──────────────────────────────────────────
    # 事件 / 状态
    # ──────────────────────────────────────────

    def on_event(self, cb) -> None:
        self.events.append(cb)

    async def get_player_state(self) -> dict:
        return {
            "data": {
                "location": {"x": self.position[0], "y": self.position[1],
                             "z": self.position[2]},
                "is_on_ground": True,
                "health": 20,
                "food": 20,
                "held_item": self.held,
            }
        }

    async def get_world_block_at(self, x: int, y: int, z: int) -> dict:
        key = (int(x), int(y), int(z))
        if key in self.wrong_block_cells:
            return {"name": self.wrong_block_cells[key]}
        if key in self.weak_confirm_cells:
            # Via 不推送块更新 → 客户端数据旧，读到 air
            return {"name": AIR}
        return {"name": self.world.get(key, AIR)}

    async def scan_region_blocks(self, x_start: int, x_end: int, z_start: int,
                                 z_end: int, y: int, max_count: int = 200000) -> dict:
        blocks = []
        for x in range(int(x_start), int(x_end) + 1):
            for z in range(int(z_start), int(z_end) + 1):
                blocks.append({"x": x, "z": z,
                               "block": self.world.get((x, int(y), z))})
        return {"data": {"blocks": blocks}, "count": len(blocks)}

    # ──────────────────────────────────────────
    # 方块操作
    # ──────────────────────────────────────────

    async def place_block(self, x: int, y: int, z: int, face: str = "UP",
                          hand: str = "MAIN_HAND", look_at_block: bool = True,
                          trust_down: bool = False) -> dict:
        key = (int(x), int(y), int(z))
        remaining = self.fail_place_cells.get(key, 0)
        if remaining > 0:
            self.fail_place_cells[key] = remaining - 1
            return {"success": False, "reason": "fake injected failure"}

        self.placed.append((int(x), int(y), int(z), self.held))
        if key not in self.weak_confirm_cells:
            self.world[key] = self.held
        return {"success": True, "placed_with": self.held}

    async def dig_block(self, x: int, y: int, z: int) -> dict:
        key = (int(x), int(y), int(z))
        self.digs.append(key)
        self.world.pop(key, None)
        return {"success": True}

    # ──────────────────────────────────────────
    # 移动
    # ──────────────────────────────────────────

    async def baritone_move(self, x: int, y: int, z: int,
                            max_offset: int = 1, timeout_ms: int = 60000) -> dict:
        self.moves.append((int(x), int(y), int(z)))
        self.position = [float(x), float(y), float(z)]
        self.last_status["position"] = {"x": x, "y": y, "z": z}
        return {"success": True, "position": {"x": x, "y": y, "z": z}}

    async def move_to(self, x: int, y: int, z: int, max_offset: int = 3,
                      timeout_ms: int = 15000, ignore_y: bool = False) -> dict:
        self.moves.append((int(x), int(y), int(z)))
        self.position = [float(x), float(y), float(z)]
        self.last_status["position"] = {"x": x, "y": y, "z": z}
        return {"success": True, "position": {"x": x, "y": y, "z": z}}

    async def walk_toward(self, x: int, z: int, timeout_ms: int = 8000) -> dict:
        self.position = [float(x), self.position[1], float(z)]
        self.last_status["position"] = {"x": x, "y": self.position[1], "z": z}
        return {"success": True}

    async def ensure_standable(self, x: int, y: int, z: int) -> dict:
        return {"success": True}

    async def scaffold_to(self, x: int, y: int, z: int, timeout_ms: int = 30000) -> dict:
        return {"success": True}

    async def look_at(self, x: int, y: int, z: int) -> dict:
        return {"success": True}

    async def cancel_pathing(self) -> dict:
        return {"success": True}

    async def set_control_state(self, ctrl: str, state: bool) -> dict:
        self.controls.append((ctrl, state))
        return {"success": True}

    # ──────────────────────────────────────────
    # 背包 / 手持
    # ──────────────────────────────────────────

    async def get_inventory_snapshot(self, inventory_id: int = 0) -> dict:
        items = [{"type": self.held, "count": 64, "slot": 0}]
        if self.offhand_food:
            # slot 40 = 前端归一化后的副手槽；启动序列据此跳过「装备/补货猪排」长流程
            items.append({"type": self.offhand_food, "count": 64, "slot": 40})
        return {"data": {"items": items}}

    async def select_hotbar_item(self, item_type: str, hand: str = "MAIN_HAND") -> dict:
        # 真客户端返回的 type 带 minecraft: 前缀；引擎内部统一去前缀
        self.held = str(item_type).split(":")[-1]
        return {"success": True}

    async def set_quick_bar_slot(self, slot: int) -> dict:
        return {"success": True}

    async def equip_offhand(self, item_id: str) -> dict:
        self.equips.append(item_id)
        return {"success": True}

    async def consume_offhand(self) -> dict:
        return {"success": True}

    # ──────────────────────────────────────────
    # 容器 / 睡觉 / 聊天
    # ──────────────────────────────────────────

    async def open_container_at(self, x: int, y: int, z: int) -> dict:
        return {"success": True, "container_id": "fake-container", "slot_count": 27}

    async def get_container_snapshot(self, container_id: str) -> dict:
        return {"data": {"items": [{"type": self.held, "count": 64, "slot": 0}]}}

    async def withdraw_container_item(self, item_id: str, count: int = 64) -> dict:
        return {"success": True}

    async def close_container(self, container_id: str = "") -> dict:
        return {"success": True}

    async def sleep_at(self, x: int, y: int, z: int) -> dict:
        return {"success": True}

    async def wake_up(self) -> dict:
        return {"success": True}

    async def send_chat(self, message: str) -> dict:
        self.chats.append(message)
        return {"success": True}

    async def get_time_status(self) -> dict:
        return {"success": True, "time_of_day": 6000, "dimension": "overworld",
                "is_raining": False, "thunder_state": 0, "is_sleeping": False}
