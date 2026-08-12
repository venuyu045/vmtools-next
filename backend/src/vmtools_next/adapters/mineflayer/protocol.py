"""WebSocket protocol constants and message types for mineflayer bridge.

Message flow:
  Request  (Python → Node):  {"type":"request", "request_id":"...", "method":"xxx", "params":{...}}
  Response (Node → Python):  {"type":"response", "request_id":"...", "success":bool, "result":{...}}
  Event    (Node → Python):  {"type":"event",    "event":"xxx",           "data":{...}}
  Status   (Node → Python):  {"type":"status",   "bot_status":{...}}
"""

# ── Method names exposed by the mineflayer bot process ──

# Movement / pathfinding
METHOD_MOVE_TO = "move_to"
METHOD_LOOK_AT = "look_at"
METHOD_GET_PLAYER_STATE = "get_player_state"
METHOD_CANCEL_PATHING = "cancel_pathing"
METHOD_IS_PLAYER_NEARBY = "is_player_nearby"
# 玩家操控（2026-08-09 背包页移动控制台）
METHOD_SET_CONTROL_STATE = "set_control_state"
METHOD_LOOK = "look"
METHOD_JUMP = "jump"
METHOD_SNEAK = "sneak"

# Block operations
METHOD_PLACE_BLOCK = "place_block"
METHOD_DIG_BLOCK = "dig_block"
METHOD_GET_WORLD_BLOCK_AT = "get_world_block_at"
METHOD_SCAN_NEARBY_BLOCKS = "scan_nearby_blocks"
METHOD_SCAN_LOADED_CONTAINERS = "scan_loaded_containers"

# Inventory / containers
METHOD_SELECT_HOTBAR_ITEM = "select_hotbar_item"
METHOD_SET_QUICK_BAR_SLOT = "set_quick_bar_slot"
METHOD_GET_INVENTORY_SNAPSHOT = "get_inventory_snapshot"
METHOD_OPEN_CONTAINER_AT = "open_container_at"
METHOD_CLOSE_CONTAINER = "close_container"
METHOD_GET_CONTAINER_SNAPSHOT = "get_container_snapshot"
METHOD_WITHDRAW_CONTAINER_ITEM = "withdraw_container_item"
METHOD_DEPOSIT_CONTAINER_ITEM = "deposit_container_item"
METHOD_DROP_ITEM = "drop_item"
METHOD_MOVE_ITEM = "move_item"
METHOD_USE_ITEM = "use_item"
# 窗口内点击/右键使用（2026-08-12，快捷潜影盒等）
METHOD_CLICK_WINDOW = "click_window"
METHOD_ACTIVATE_ITEM = "activate_item"
METHOD_ACTIVATE_BLOCK = "activate_block"

# Servux 容器预览（不打开容器，直接请求方块实体 NBT）
METHOD_SERVUX_HANDSHAKE = "servux_handshake"
METHOD_PREVIEW_CONTAINER_AT = "preview_container_at"

# Chat
METHOD_SEND_CHAT = "send_chat"
METHOD_RUN_COMMAND = "run_command"

# World queries
METHOD_GET_SERVER_INFO = "get_server_info"
METHOD_FIND_BLOCKS = "find_blocks"

# Combat（自动攻击/手动攻击/守护模式，2026-08-10）
METHOD_GET_NEARBY_ENTITIES = "get_nearby_entities"
METHOD_ATTACK = "attack"
METHOD_SET_AUTO_ATTACK = "set_auto_attack"
METHOD_SET_GUARD = "set_guard"
METHOD_GET_COMBAT_STATUS = "get_combat_status"
METHOD_STOP_COMBAT = "stop_combat"

# ── Event names pushed by the bot process ──
EVENT_BOT_READY = "bot_ready"
EVENT_BOT_SPAWNED = "bot_spawned"
EVENT_BOT_DEATH = "bot_death"
EVENT_BOT_KICKED = "bot_kicked"
EVENT_BOT_ERROR = "bot_error"
EVENT_BOT_DISCONNECTED = "bot_disconnected"
EVENT_BOT_CHAT = "bot_chat"
EVENT_PLAYER_JOINED = "player_joined"
EVENT_PLAYER_LEFT = "player_left"
EVENT_COMBAT_DURABILITY_LOW = "combat_durability_low"
# 容器窗口自动打开/关闭（2026-08-12：快捷潜影盒等服务器 GUI）
EVENT_CONTAINER_OPENED = "container_opened"
EVENT_CONTAINER_CLOSED = "container_closed"

# ── Default timeout ──

DEFAULT_CMD_TIMEOUT = 30.0  # seconds
MOVE_TIMEOUT = 15.0
CONTAINER_TIMEOUT = 10.0
