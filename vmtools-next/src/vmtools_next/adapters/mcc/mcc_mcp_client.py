"""MCC MCP HTTP Client — wraps all 65 tool methods from IMccMcpCapabilities.

Uses httpx.AsyncClient for async HTTP requests to MCC's MCP server
at http://{host}:{port}/mcp. Each method maps 1:1 to a C# MCP tool.

MCP Protocol: JSON-RPC 2.0 over HTTP POST.
  Request:  {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ToolName","arguments":{...}}}
  Response: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"..."}]}}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("vmtools.mcc_mcp")


class MccMcpError(Exception):
    """Error returned by MCC MCP server."""
    def __init__(self, message: str, code: int = -1, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MccMcpClient:
    """Async HTTP client for MCC's MCP server.

    One instance per bot. Managed by MccSessionPool.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 33333,
                 auth_token: Optional[str] = None,
                 timeout_connect: float = 5.0,
                 timeout_read: float = 30.0):
        self._host = host
        self._port = port
        self._base_url = f"http://{host}:{port}/mcp"
        self._auth_token = auth_token
        self._timeout = httpx.Timeout(connect=timeout_connect, read=timeout_read, write=10.0, pool=5.0)
        self._client: Optional[httpx.AsyncClient] = None
        self._request_id = 0
        self._connected = False
        self._session_id: Optional[str] = None

    async def connect(self) -> bool:
        """Initialize the HTTP client, perform MCP handshake, and verify connectivity."""
        if self._client is not None:
            return True
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
        )
        try:
            # MCP initialize handshake (required for newer MCC MCP SDK)
            await self._initialize()
            result = await self.get_session_status()
            self._connected = True
            logger.info("MCC MCP connected: %s:%d", self._host, self._port)
            return True
        except Exception as e:
            logger.warning("MCC MCP connection failed: %s", e)
            self._connected = False
            return False

    async def _initialize(self) -> None:
        """Send MCP initialize request and capture session ID."""
        resp = await self._client.post("", json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vmtools-next", "version": "0.1.0"},
            },
        })
        data = resp.json()
        if "error" in data:
            logger.warning("MCP initialize failed: %s", data["error"].get("message", ""))
            # Some servers don't require initialize — try stateless
            return
        # Extract session ID from response headers
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
            self._client.headers["mcp-session-id"] = sid
            logger.info("MCP session established: %s", sid)
        # Send initialized notification
        await self._client.post("", json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
            return False

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    # ── Low-level RPC ────────────────────────────────────────────────────

    async def _call_tool(self, tool_name: str, arguments: Optional[dict] = None,
                         timeout_override: Optional[float] = None) -> dict:
        """Call a single MCP tool and return the parsed result.

        Retries up to 3 times on network errors with exponential backoff.
        """
        if self._client is None:
            raise MccMcpError("Client not connected", code=-1)

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }

        last_error = None
        for attempt in range(3):
            try:
                kwargs = {}
                if timeout_override is not None:
                    kwargs["timeout"] = timeout_override

                resp = await self._client.post("", json=payload, **kwargs)

                if resp.status_code >= 500:
                    last_error = MccMcpError(f"Server error {resp.status_code}", code=resp.status_code)
                    await asyncio.sleep(1.0 * (2 ** attempt))
                    continue
                if resp.status_code >= 400:
                    raise MccMcpError(f"Client error {resp.status_code}: {resp.text}", code=resp.status_code)

                data = resp.json()
                if "error" in data:
                    err = data["error"]
                    raise MccMcpError(
                        err.get("message", "Unknown error"),
                        code=err.get("code", -1),
                        data=err.get("data"),
                    )

                # Extract result from MCP response
                result = data.get("result", {})
                content = result.get("content", [])
                if content and len(content) > 0:
                    text = content[0].get("text", "{}")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"raw": text}
                return result

            except httpx.TimeoutException as e:
                last_error = MccMcpError(f"Timeout: {e}", code=-2)
                await asyncio.sleep(1.0 * (2 ** attempt))
            except httpx.ConnectError as e:
                last_error = MccMcpError(f"Connection error: {e}", code=-3)
                self._connected = False
                await asyncio.sleep(1.0 * (2 ** attempt))
            except MccMcpError:
                raise
            except Exception as e:
                last_error = MccMcpError(f"Unexpected error: {e}", code=-4)
                await asyncio.sleep(1.0 * (2 ** attempt))

        raise last_error or MccMcpError("Max retries exceeded")

    # ── Session/World Query (10 methods) ─────────────────────────────────

    async def get_session_status(self) -> dict:
        return await self._call_tool("GetSessionStatus")

    async def get_server_info(self) -> dict:
        return await self._call_tool("GetServerInfo")

    async def get_player_state(self) -> dict:
        return await self._call_tool("GetPlayerState")

    async def get_world_state(self) -> dict:
        return await self._call_tool("GetWorldState")

    async def get_chunk_status(self, x: Optional[float] = None,
                                y: Optional[float] = None,
                                z: Optional[float] = None) -> dict:
        args = {}
        if x is not None: args["x"] = x
        if y is not None: args["y"] = y
        if z is not None: args["z"] = z
        return await self._call_tool("GetChunkStatus", args)

    async def get_loaded_bots(self) -> dict:
        return await self._call_tool("GetLoadedBots")

    async def get_recent_events(self, after_id: int = 0, max_count: int = 50,
                                 type_filter: Optional[str] = None) -> dict:
        args = {"afterId": after_id, "maxCount": max_count}
        if type_filter:
            args["typeFilter"] = type_filter
        return await self._call_tool("GetRecentEvents", args)

    async def get_chat_history(self, max_count: int = 50,
                                include_json: bool = False) -> dict:
        return await self._call_tool("GetChatHistory", {
            "maxCount": max_count, "includeJson": include_json,
        })

    async def get_status_effects(self) -> dict:
        return await self._call_tool("GetStatusEffects")

    async def get_player_stats(self) -> dict:
        return await self._call_tool("GetPlayerStats")

    # ── Movement/Pathfinding (6 methods) — replaces BaritoneAdapter ──────

    async def move_to(self, x: float, y: float, z: float,
                       allow_unsafe: bool = False,
                       allow_direct_teleport: bool = False,
                       max_offset: int = 1, min_offset: int = 0,
                       timeout_ms: int = 10000) -> dict:
        return await self._call_tool("MoveTo", {
            "x": x, "y": y, "z": z,
            "allowUnsafe": allow_unsafe,
            "allowDirectTeleport": allow_direct_teleport,
            "maxOffset": max_offset, "minOffset": min_offset,
            "timeoutMs": timeout_ms,
        }, timeout_override=timeout_ms / 1000.0 + 5.0)

    async def move_to_player(self, player_name: str,
                              allow_unsafe: bool = False,
                              allow_direct_teleport: bool = False,
                              max_offset: int = 1, min_offset: int = 0,
                              timeout_ms: int = 10000) -> dict:
        return await self._call_tool("MoveToPlayer", {
            "playerName": player_name,
            "allowUnsafe": allow_unsafe,
            "allowDirectTeleport": allow_direct_teleport,
            "maxOffset": max_offset, "minOffset": min_offset,
            "timeoutMs": timeout_ms,
        }, timeout_override=timeout_ms / 1000.0 + 5.0)

    async def can_reach_position(self, x: float, y: float, z: float,
                                  allow_unsafe: bool = False,
                                  max_offset: int = 1, min_offset: int = 0,
                                  timeout_ms: int = 10000) -> dict:
        return await self._call_tool("CanReachPosition", {
            "x": x, "y": y, "z": z,
            "allowUnsafe": allow_unsafe,
            "maxOffset": max_offset, "minOffset": min_offset,
            "timeoutMs": timeout_ms,
        })

    async def preview_path(self, x: float, y: float, z: float,
                            allow_unsafe: bool = False,
                            max_offset: int = 1, min_offset: int = 0,
                            timeout_ms: int = 10000,
                            max_waypoints: int = 50) -> dict:
        return await self._call_tool("PreviewPath", {
            "x": x, "y": y, "z": z,
            "allowUnsafe": allow_unsafe,
            "maxOffset": max_offset, "minOffset": min_offset,
            "timeoutMs": timeout_ms, "maxWaypoints": max_waypoints,
        })

    async def look_at(self, x: float, y: float, z: float) -> dict:
        return await self._call_tool("LookAt", {"x": x, "y": y, "z": z})

    async def look_direction(self, direction: str) -> dict:
        """direction: 'north'|'south'|'east'|'west'|'up'|'down'"""
        return await self._call_tool("LookDirection", {"direction": direction})

    async def look_angles(self, yaw: float, pitch: float) -> dict:
        return await self._call_tool("LookAngles", {"yaw": yaw, "pitch": pitch})

    # ── Block Operations (6 methods) — replaces PrinterAdapter ───────────

    async def place_block(self, x: int, y: int, z: int,
                           face: str = "UP", hand: str = "MAIN_HAND",
                           look_at_block: bool = True) -> dict:
        return await self._call_tool("PlaceBlock", {
            "x": x, "y": y, "z": z,
            "face": face, "hand": hand, "lookAtBlock": look_at_block,
        })

    async def dig_block(self, x: int, y: int, z: int,
                         duration_seconds: float = 0) -> dict:
        return await self._call_tool("DigBlock", {
            "x": x, "y": y, "z": z, "durationSeconds": duration_seconds,
        })

    async def use_item_on_block(self, x: int, y: int, z: int) -> dict:
        return await self._call_tool("UseItemOnBlock", {"x": x, "y": y, "z": z})

    async def use_item_on_hand(self) -> dict:
        return await self._call_tool("UseItemOnHand")

    async def get_world_block_at(self, x: int, y: int, z: int) -> dict:
        return await self._call_tool("GetWorldBlockAt", {"x": x, "y": y, "z": z})

    async def scan_nearby_blocks(self, radius: int = 16, max_count: int = 100,
                                  material_filter: Optional[str] = None) -> dict:
        args = {"radius": radius, "maxCount": max_count}
        if material_filter:
            args["materialFilter"] = material_filter
        return await self._call_tool("ScanNearbyBlocks", args)

    # ── Container/Inventory (8 methods) — replaces MiniHudAdapter ────────

    async def list_inventories(self) -> dict:
        return await self._call_tool("ListInventories")

    async def get_inventory_snapshot(self, inventory_id: int = 0) -> dict:
        return await self._call_tool("GetInventorySnapshot", {"inventoryId": inventory_id})

    async def search_inventories(self, query: str, max_count: int = 50,
                                  exact_match: bool = False,
                                  include_containers: bool = True) -> dict:
        return await self._call_tool("SearchInventories", {
            "query": query, "maxCount": max_count,
            "exactMatch": exact_match, "includeContainers": include_containers,
        })

    async def open_container_at(self, x: int, y: int, z: int,
                                 timeout_ms: int = 5000,
                                 close_current: bool = True) -> dict:
        return await self._call_tool("OpenContainerAt", {
            "x": x, "y": y, "z": z,
            "timeoutMs": timeout_ms, "closeCurrent": close_current,
        }, timeout_override=timeout_ms / 1000.0 + 5.0)

    async def close_container(self, inventory_id: int,
                               timeout_ms: int = 5000) -> dict:
        return await self._call_tool("CloseContainer", {
            "inventoryId": inventory_id, "timeoutMs": timeout_ms,
        })

    async def inventory_window_action(self, inventory_id: int, slot_id: int,
                                       action_type: str = "ShiftClick") -> dict:
        """action_type: 'LeftClick'|'RightClick'|'ShiftClick'|'DropItemStack'|'DropSingleItem'"""
        return await self._call_tool("InventoryWindowAction", {
            "inventoryId": inventory_id, "slotId": slot_id, "actionType": action_type,
        })

    async def withdraw_container_item(self, item_type: str, count: int = 64,
                                       inventory_id: int = 0,
                                       prefer_largest_stack: bool = True) -> dict:
        return await self._call_tool("WithdrawContainerItem", {
            "itemType": item_type, "count": count,
            "inventoryId": inventory_id, "preferLargestStack": prefer_largest_stack,
        })

    async def deposit_container_item(self, item_type: str, count: int = 64,
                                      inventory_id: int = 0,
                                      prefer_largest_stack: bool = True) -> dict:
        return await self._call_tool("DepositContainerItem", {
            "itemType": item_type, "count": count,
            "inventoryId": inventory_id, "preferLargestStack": prefer_largest_stack,
        })

    # ── Player Actions (5 methods) ───────────────────────────────────────

    async def change_hotbar_slot(self, slot: int) -> dict:
        return await self._call_tool("ChangeHotbarSlot", {"slot": slot})

    async def select_hotbar_item(self, item_type: str,
                                  prefer_lowest_slot: bool = True) -> dict:
        return await self._call_tool("SelectHotbarItem", {
            "itemType": item_type, "preferLowestSlot": prefer_lowest_slot,
        })

    async def toggle_sneak(self, enabled: bool) -> dict:
        return await self._call_tool("ToggleSneak", {"enabled": enabled})

    async def toggle_sprint(self, enabled: bool) -> dict:
        return await self._call_tool("ToggleSprint", {"enabled": enabled})

    async def play_animation(self, hand: str = "MAIN_HAND") -> dict:
        return await self._call_tool("PlayAnimation", {"hand": hand})

    # ── Chat/Command (4 methods) ─────────────────────────────────────────

    async def send_chat(self, text: str) -> dict:
        return await self._call_tool("SendChat", {"text": text})

    async def run_internal_command(self, command: str) -> dict:
        return await self._call_tool("RunInternalCommand", {"command": command})

    async def respawn(self) -> dict:
        return await self._call_tool("Respawn")

    async def disconnect_client(self) -> dict:
        return await self._call_tool("DisconnectClient")

    # ── Entity (5 methods) ───────────────────────────────────────────────

    async def list_entities(self, max_count: int = 100,
                             type_filter: Optional[str] = None,
                             radius: float = 32.0) -> dict:
        args = {"maxCount": max_count, "radius": radius}
        if type_filter:
            args["typeFilter"] = type_filter
        return await self._call_tool("ListEntities", args)

    async def get_entity_info(self, entity_id: int,
                               include_metadata: bool = True,
                               include_equipment: bool = True,
                               include_effects: bool = False) -> dict:
        return await self._call_tool("GetEntityInfo", {
            "entityId": entity_id,
            "includeMetadata": include_metadata,
            "includeEquipment": include_equipment,
            "includeEffects": include_effects,
        })

    async def attack_entity(self, entity_id: int) -> dict:
        return await self._call_tool("AttackEntity", {"entityId": entity_id})

    async def interact_entity(self, entity_id: int, interaction: str = "interact",
                               hand: str = "MAIN_HAND") -> dict:
        return await self._call_tool("InteractEntity", {
            "entityId": entity_id, "interaction": interaction, "hand": hand,
        })

    async def pickup_items(self, item_type: str, radius: float = 16.0,
                            max_items: int = 64, allow_unsafe: bool = False,
                            timeout_ms: int = 10000) -> dict:
        return await self._call_tool("PickupItems", {
            "itemType": item_type, "radius": radius, "maxItems": max_items,
            "allowUnsafe": allow_unsafe, "timeoutMs": timeout_ms,
        })

    # ── Query Helpers (multiple methods) ─────────────────────────────────

    async def find_blocks(self, query: Optional[str] = None, radius: int = 32,
                           max_count: int = 100, exact_match: bool = False) -> dict:
        args = {"radius": radius, "maxCount": max_count, "exactMatch": exact_match}
        if query:
            args["query"] = query
        return await self._call_tool("FindBlocks", args)

    async def find_nearest_entity(self, type_filter: Optional[str] = None,
                                   name_filter: Optional[str] = None,
                                   radius: float = 32.0,
                                   include_players: bool = False) -> dict:
        args = {"radius": radius, "includePlayers": include_players}
        if type_filter: args["typeFilter"] = type_filter
        if name_filter: args["nameFilter"] = name_filter
        return await self._call_tool("FindNearestEntity", args)

    async def is_player_nearby(self, player_name: Optional[str] = None,
                                radius: float = 32.0,
                                include_self: bool = False) -> dict:
        args = {"radius": radius, "includeSelf": include_self}
        if player_name: args["playerName"] = player_name
        return await self._call_tool("IsPlayerNearby", args)

    async def locate_player(self, player_name: str,
                             include_self: bool = False) -> dict:
        return await self._call_tool("LocatePlayer", {
            "playerName": player_name, "includeSelf": include_self,
        })

    async def find_signs(self, text: str, exact_match: bool = False,
                          radius: int = 32, max_count: int = 20,
                          include_back_text: bool = False) -> dict:
        return await self._call_tool("FindSigns", {
            "text": text, "exactMatch": exact_match, "radius": radius,
            "maxCount": max_count, "includeBackText": include_back_text,
        })

    async def list_item_entities(self, item_type: Optional[str] = None,
                                  radius: float = 32.0,
                                  max_count: int = 100) -> dict:
        args = {"radius": radius, "maxCount": max_count}
        if item_type: args["itemType"] = item_type
        return await self._call_tool("ListItemEntities", args)

    async def get_materials_list(self, filter: Optional[str] = None,
                                  max_count: int = 100) -> dict:
        args = {"maxCount": max_count}
        if filter: args["filter"] = filter
        return await self._call_tool("GetMaterialsList", args)

    async def get_block_types_list(self, filter: Optional[str] = None,
                                    max_count: int = 100) -> dict:
        args = {"maxCount": max_count}
        if filter: args["filter"] = filter
        return await self._call_tool("GetBlockTypesList", args)

    async def get_entity_types_list(self, filter: Optional[str] = None,
                                     max_count: int = 100) -> dict:
        args = {"maxCount": max_count}
        if filter: args["filter"] = filter
        return await self._call_tool("GetEntityTypesList", args)

    async def get_players_list(self) -> dict:
        return await self._call_tool("GetPlayersList")

    async def get_players_detailed(self, include_self: bool = False,
                                    include_coordinates: bool = True) -> dict:
        return await self._call_tool("GetPlayersDetailed", {
            "includeSelf": include_self, "includeCoordinates": include_coordinates,
        })

    async def raycast_block(self, max_distance: float = 6.0,
                             include_neighbors: bool = False) -> dict:
        return await self._call_tool("RaycastBlock", {
            "maxDistance": max_distance, "includeNeighbors": include_neighbors,
        })

    async def get_internal_commands(self) -> dict:
        return await self._call_tool("GetInternalCommands")

    async def quit_client(self) -> dict:
        return await self._call_tool("QuitClient")

    async def drop_inventory_item(self, item_type: str, count: int = 64,
                                   inventory_id: int = 0,
                                   prefer_stack: bool = True) -> dict:
        return await self._call_tool("DropInventoryItem", {
            "itemType": item_type, "count": count,
            "inventoryId": inventory_id, "preferStack": prefer_stack,
        })

    async def query_entities(self, max_count: int = 100) -> dict:
        return await self._call_tool("QueryEntities", {"maxCount": max_count})
