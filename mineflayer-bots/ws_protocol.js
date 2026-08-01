/**
 * ws_protocol.js — WebSocket 消息协议定义和工具
 *
 * 消息格式：
 *   请求 (Python → Node):  { type: "request",  request_id: "uuid", method: "xxx", params: {...} }
 *   响应 (Node → Python):  { type: "response", request_id: "uuid", success: bool, result: {...} }
 *   事件 (Node → Python):  { type: "event",    event: "xxx",       data: {...} }
 *   状态 (Node → Python):  { type: "status",   bot_status: {...} }
 */

// ── 请求-响应协议 ────────────────────────────────────────────

let requestIdCounter = 0;

/** 生成递增 request_id */
function nextRequestId() {
  return `req_${++requestIdCounter}_${Date.now()}`;
}

/** 创建一个请求消息 */
function createRequest(method, params = {}) {
  return {
    type: 'request',
    request_id: nextRequestId(),
    method,
    params,
  };
}

/** 创建一个成功响应 */
function createSuccessResponse(request_id, result = {}) {
  return { type: 'response', request_id, success: true, result };
}

/** 创建一个失败响应 */
function createErrorResponse(request_id, error) {
  return { type: 'response', request_id, success: false, error: String(error) };
}

// ── 事件推送 ────────────────────────────────────────────────────

/** 创建一个事件推送消息 */
function createEvent(eventName, data = {}) {
  return { type: 'event', event: eventName, data };
}

/** 创建 bot 状态更新 */
function createStatusUpdate(bot) {
  if (!bot || !bot.entity) {
    return { type: 'status', bot_status: { connected: false } };
  }
  return {
    type: 'status',
    bot_status: {
      connected: true,
      position: {
        x: bot.entity.position.x,
        y: bot.entity.position.y,
        z: bot.entity.position.z,
      },
      yaw: bot.entity.yaw,
      pitch: bot.entity.pitch,
      health: bot.health || 20,
      food: bot.food || 20,
      dimension: bot.game?.dimension || 'unknown',
      game_mode: bot.game?.gameMode || 'unknown',
      logged_in: true,  // 状态推送只会在 login 事件后启动，true = 已通过登录认证
      username: bot.username,
      ping: bot.player?.ping ?? -1,
    },
  };
}

module.exports = {
  nextRequestId,
  createRequest,
  createSuccessResponse,
  createErrorResponse,
  createEvent,
  createStatusUpdate,
};
