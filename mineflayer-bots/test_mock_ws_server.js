#!/usr/bin/env node
/**
 * test_mock_ws_server.js — 模拟 mineflayer bot 的 WebSocket 服务器
 *
 * 用于测试 Python MineflayerBridgeClient 的通信协议。
 * 用法: node test_mock_ws_server.js --port 44444
 */

const { WebSocketServer } = require('ws');
const { createSuccessResponse, createErrorResponse, createEvent } = require('./ws_protocol');

const args = {};
const raw = process.argv.slice(2);
for (let i = 0; i < raw.length; i++) {
  const key = raw[i].replace(/^--/, '');
  const val = raw[++i];
  if (val !== undefined) {
    const num = Number(val);
    args[key.replace(/-/g, '_')] = isNaN(num) ? val : num;
  }
}

const port = args.port || 44444;
const wss = new WebSocketServer({ port });

console.log(`[mock] WS server listening on ${port}`);

wss.on('connection', (ws) => {
  console.log('[mock] client connected');

  // 发送 bot_ready 事件
  ws.send(JSON.stringify(createEvent('bot_ready', {
    username: 'MockBot',
    ws_port: port,
  })));

  ws.on('message', (rawMsg) => {
    let msg;
    try {
      msg = JSON.parse(rawMsg.toString());
    } catch {
      return;
    }

    if (msg.type === 'request') {
      const { request_id, method, params = {} } = msg;
      console.log(`[mock] request: ${method}`, params);

      // 模拟 100ms 延迟
      setTimeout(() => {
        let result;

        switch (method) {
          case 'health_check':
            result = { status: 'ok', uptime_ms: 1234 };
            break;
          case 'get_player_state':
            result = {
              position: { x: 100, y: 64, z: 200 },
              yaw: 0,
              pitch: 0,
              health: 20,
              food: 20,
              gamemode: 'creative',
              dimension: 'minecraft:overworld',
              is_on_ground: true,
              velocity: { x: 0, y: 0, z: 0 },
            };
            break;
          case 'get_inventory_snapshot':
            result = {
              items: [
                { item_id: 'minecraft:dirt', count: 64, slot: 0 },
                { item_id: 'minecraft:stone', count: 32, slot: 1 },
              ],
              hotbar: [null, null, null, null, null, null, null, null, null],
            };
            break;
          case 'get_world_block_at':
            result = { block_id: 'minecraft:stone', properties: {} };
            break;
          case 'move_to':
            result = { success: true, path_length: 42 };
            break;
          case 'look_at':
            result = { success: true };
            break;
          case 'place_block':
            result = { success: true };
            break;
          case 'dig_block':
            result = { success: true };
            break;
          case 'select_hotbar_item':
            result = { success: true };
            break;
          case 'send_chat':
            result = { success: true };
            break;
          case 'run_command':
            result = { success: true };
            break;
          case 'get_server_info':
            result = {
              server: 'MockServer',
              version: '1.21.11',
              online_mode: false,
              player_count: 10,
              max_players: 20,
            };
            break;
          case 'cancel_pathing':
            result = { success: true };
            break;
          case 'is_player_nearby':
            result = { nearby: false, players: [] };
            break;
          case 'open_container_at':
            result = { container_id: 'mock-container-1', type: 'chest', slots: 27 };
            break;
          case 'close_container':
            result = { success: true };
            break;
          case 'get_container_snapshot':
            result = {
              container_id: 'mock-container-1',
              items: [
                { item_id: 'minecraft:dirt', count: 64, slot: 0 },
              ],
            };
            break;
          case 'withdraw_container_item':
            result = { success: true, withdrawn: params.count || 1 };
            break;
          case 'deposit_container_item':
            result = { success: true, deposited: params.count || 1 };
            break;
          case 'find_blocks':
            result = { blocks: [] };
            break;
          case 'scan_nearby_blocks':
            result = { blocks: [] };
            break;
          case 'set_quick_bar_slot':
            result = { success: true };
            break;
          default:
            ws.send(JSON.stringify(createErrorResponse(request_id, `Unknown method: ${method}`)));
            return;
        }

        ws.send(JSON.stringify(createSuccessResponse(request_id, result)));
      }, 100);
    }
  });

  ws.on('close', () => {
    console.log('[mock] client disconnected');
  });
});

// 每 3 ���推送状态事件
setInterval(() => {
  const status = {
    type: 'status',
    bot_status: {
      connected: true,
      position: { x: 100, y: 64, z: 200 },
      yaw: 0,
      pitch: 0,
      health: 20,
      food: 20,
      dimension: 'minecraft:overworld',
      game_mode: 'creative',
    },
  };
  for (const ws of wss.clients) {
    if (ws.readyState === 1) {
      ws.send(JSON.stringify(status));
    }
  }
}, 3000);

console.log('[mock] ready');

// 优雅退出
process.on('SIGTERM', () => {
  wss.close();
  process.exit(0);
});
process.on('SIGINT', () => {
  wss.close();
  process.exit(0);
});
