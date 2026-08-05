/**
 * servux.js — Servux 容器预览协议客户端 handler
 *
 * 实现 MiniHUD 的 Servux Entity Data Sync 协议（通道 servux:entity_data, v2）：
 *   不打开容器，直接按 BlockPos 向服务器请求方块实体 NBT（含 Items），
 *   用于仓库扫描等"只读容器内容"的场景。
 *
 * 协议（详见 docs/servux-container-data-sync-analysis.md）：
 *   C2S_METADATA_REQUEST(2)            = varint(2) + NBT{version:2}
 *   S2C_METADATA(1)                    = varint(1) + NBT{version, servux}
 *   C2S_BLOCK_ENTITY_REQUEST(3)        = varint(3) + BlockPos(long)
 *   S2C_BLOCK_NBT_RESPONSE_SIMPLE(5)   = varint(5) + BlockPos(long) + NBT
 *
 * 方法：
 *   servux_handshake()       → 与服务器 Servux 插件握手，返回 {success, version?}
 *   preview_container_at(x,y,z,timeout_ms) → 预览容器内容（不打开容器）
 *
 * 依赖：prismarine-nbt（mineflayer 传递依赖）
 */

const nbt = require('prismarine-nbt');

// ── 协议常量 ──
const CHANNEL = 'servux:entity_data';
const PROTOCOL_VERSION = 2;

const TYPE_S2C_METADATA = 1;
const TYPE_C2S_METADATA_REQUEST = 2;
const TYPE_C2S_BLOCK_ENTITY_REQUEST = 3;
const TYPE_C2S_ENTITY_REQUEST = 4;
const TYPE_S2C_BLOCK_NBT_RESPONSE_SIMPLE = 5;
const TYPE_S2C_ENTITY_NBT_RESPONSE_SIMPLE = 6;
const TYPE_C2S_UNREGISTER_REPLY = 7;

const DEFAULT_TIMEOUT_MS = 5000;
const HANDSHAKE_TIMEOUT_MS = 3000;

// ── Varint 编解码 ──
function writeVarInt(value) {
  const out = [];
  let v = value >>> 0;
  while (v >= 0x80) {
    out.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
  out.push(v);
  return Buffer.from(out);
}

function readVarInt(buf, offset) {
  let result = 0;
  let shift = 0;
  let pos = offset || 0;
  while (true) {
    if (pos >= buf.length) throw new Error('VarInt out of buffer');
    const b = buf[pos++];
    result |= (b & 0x7f) << shift;
    if ((b & 0x80) === 0) break;
    shift += 7;
    if (shift >= 35) throw new Error('VarInt too long');
  }
  return { value: result >>> 0, offset: pos };
}

// ── BlockPos long（MC 1.14+）：((x & 0x3FFFFFF) << 38) | ((z & 0x3FFFFFF) << 12) | (y & 0xFFF) ──
function posToLong(x, y, z) {
  let val = (
    ((BigInt(x) & 0x3ffffffn) << 38n) |
    ((BigInt(z) & 0x3ffffffn) << 12n) |
    (BigInt(y) & 0xfffn)
  );
  // 转为有符号 64 位（Java long 补码）：负坐标时结果最高位为 1，需减 2^64
  if (val >= (1n << 63n)) {
    val -= (1n << 64n);
  }
  return val;
}

function longToPos(buf, offset) {
  const val = buf.readBigInt64BE(offset);
  const x = Number((val >> 38n) & 0x3ffffffn);
  const z = Number((val >> 12n) & 0x3ffffffn);
  const y = Number(val & 0xfffn);
  // 符号修正（负数坐标）
  const sx = x >= 0x2000000 ? x - 0x4000000 : x;
  const sz = z >= 0x2000000 ? z - 0x4000000 : z;
  const sy = y >= 0x800 ? y - 0x1000 : y;
  return { x: sx, y: sy, z: sz, offset: offset + 8 };
}

// ── NBT 辅助 ──
function encodeNbt(compoundValue) {
  const tag = { type: 'compound', name: '', value: compoundValue };
  return nbt.writeUncompressed(tag);
}

function parseNbt(buf) {
  return nbt.parse(buf);
}

/**
 * 兼容 prismarine-nbt 新旧版本返回结构：
 *   新（3.x）: { parsed: {type,name,value}, type, metadata }
 *   旧（2.x）: { type, name, value, metadata }
 * @returns {object} compound value
 */
function getCompoundValue(parsed) {
  if (parsed?.parsed && parsed.parsed.value) return parsed.parsed.value;
  if (parsed?.value && typeof parsed.value === 'object') return parsed.value;
  if (parsed?.data && parsed.data.value) return parsed.data.value;
  return {};
}

/**
 * 从方块实体 NBT 中提取物品列表（兼容 1.21.x 组件化格式与旧格式）。
 * @param {object} compoundValue prismarine-nbt compound value
 * @returns {Array<{item_id, display_name, count, slot}>}
 */
function extractItems(compoundValue) {
  const items = [];
  if (!compoundValue || typeof compoundValue !== 'object') return items;

  // 1.21.x: Items / Inventory / Container 列表（组件化：id 为字符串 + components）
  // 旧版:   Items 列表（id 为字符串 + tag）
  const listTag = compoundValue.Items || compoundValue.Inventory || compoundValue.Container;
  if (listTag && listTag.type === 'list') {
    const arr = listTag.value && listTag.value.value;
    if (Array.isArray(arr)) {
      for (const entry of arr) {
        if (!entry || typeof entry !== 'object') continue;
        const id = entry.id?.value || entry.Id?.value || '';
        if (!id) continue;
        const count = entry.count?.value ?? entry.Count?.value ?? 1;
        const slot = entry.Slot?.value ?? entry.slot?.value ?? -1;
        items.push({
          item_id: String(id),
          display_name: friendlyName(String(id)),
          count: Number(count) || 0,
          slot: Number(slot),
        });
      }
    }
  }
  return items;
}

function friendlyName(itemId) {
  const parts = String(itemId).split(':');
  return parts[parts.length - 1] || itemId;
}

/**
 * @param {import('mineflayer').Bot} bot
 */
function createServuxHandlers(bot) {
  const pending = new Map(); // key `${x},${y},${z}` → {resolve, timer}
  let servuxReady = false;
  let servuxVersion = null;
  let handshakePromise = null;
  let handshakeResolve = null;

  // ── 发送原始 payload ──
  function sendPayload(payloadBuffer) {
    try {
      bot._client.write('custom_payload', {
        channel: CHANNEL,
        data: payloadBuffer,
      });
      return true;
    } catch (err) {
      console.error('[servux] send payload failed:', err.message);
      return false;
    }
  }

  // ── 握手 ──
  function ensureHandshake() {
    if (servuxReady) return Promise.resolve({ success: true, version: servuxVersion });
    if (handshakePromise) return handshakePromise;

    handshakePromise = new Promise((resolve) => {
      handshakeResolve = resolve;
      const meta = encodeNbt({ version: { type: 'int', value: PROTOCOL_VERSION } });
      const payload = Buffer.concat([writeVarInt(TYPE_C2S_METADATA_REQUEST), meta]);
      sendPayload(payload);
      // 握手结果由 custom_payload 接收侧在收到 S2C_METADATA 时回填（resolve）；
      // 这里用超时兜底，避免等待时挂死。
      setTimeout(() => {
        if (!servuxReady) {
          handshakePromise = null;
          handshakeResolve = null;
          resolve({ success: false, error: 'Servux handshake timeout' });
        }
      }, HANDSHAKE_TIMEOUT_MS);
    });
    return handshakePromise;
  }

  // ── 收到 Servux 响应 ──
  async function handlePayload(packet) {
    // 关键过滤：minecraft-protocol 会把服务器发来的【所有】custom_payload 都抛到这个事件
    // （品牌 minecraft:brand、注册表 minecraft:register、聊天建议、其它插件通道等）。
    // 若不按通道过滤，其它通道的二进制数据会被误当成 Servux NBT 解析，
    // 产生大量 "Read error ... Missing characters in string" 噪音，甚至可能误触发解析逻辑。
    if (packet && packet.channel !== undefined && String(packet.channel) !== CHANNEL) {
      return;
    }

    let buf = packet && (packet.data || packet);
    if (typeof buf === 'object' && Buffer.isBuffer(buf) === false && buf.data) {
      buf = buf.data; // 兼容 packet 对象形态
    }
    if (!Buffer.isBuffer(buf) || buf.length < 1) return;

    let res;
    try {
      res = readVarInt(buf, 0);
    } catch (e) {
      return;
    }
    const type = res.value;
    let offset = res.offset;

    try {
      if (type === TYPE_S2C_METADATA) {
        // NBT 元数据 → 校验版本与前缀
        const parsed = await parseNbt(buf.subarray(offset));
        const value = getCompoundValue(parsed);
        const version = value.version?.value;
        const servux = value.servux?.value;
        if (version === PROTOCOL_VERSION && typeof servux === 'string' && servux.startsWith('servux-')) {
          servuxReady = true;
          servuxVersion = servux;
          console.log('[servux] handshake OK, connected to', servux);
          // 唤醒等待中的握手调用方
          if (handshakeResolve) {
            const resolveHs = handshakeResolve;
            handshakeResolve = null;
            resolveHs({ success: true, version: servux });
          }
        } else {
          console.warn('[servux] handshake mismatch: version=%s servux=%s', version, servux);
          sendPayload(Buffer.concat([writeVarInt(TYPE_C2S_UNREGISTER_REPLY), encodeNbt({})]));
        }
      } else if (type === TYPE_S2C_BLOCK_NBT_RESPONSE_SIMPLE) {
        const posRes = longToPos(buf, offset);
        const key = `${posRes.x},${posRes.y},${posRes.z}`;
        offset = posRes.offset;
        const parsed = await parseNbt(buf.subarray(offset));
        const compoundValue = getCompoundValue(parsed);
        const items = extractItems(compoundValue);
        const entry = pending.get(key);
        if (entry) {
          clearTimeout(entry.timer);
          pending.delete(key);
          entry.resolve({ success: true, items, source: 'servux' });
        }
      } else if (type === TYPE_S2C_ENTITY_NBT_RESPONSE_SIMPLE) {
        // 实体响应：暂不处理（仓库扫描只用方块实体）
      }
    } catch (err) {
      console.error('[servux] handle payload error:', err.message);
    }
  }

  // ── 注册 custom_payload 监听 ──
  function register() {
    if (!bot._client) return false;
    bot._client.on('custom_payload', handlePayload);
    return true;
  }

  // ── 对外方法 ──

  async function servux_handshake({ timeout_ms = HANDSHAKE_TIMEOUT_MS } = {}) {
    const result = await ensureHandshake();
    return {
      success: servuxReady,
      version: servuxVersion || (result && result.version) || null,
      error: result && result.error ? result.error : undefined,
    };
  }

  async function preview_container_at({ x, y, z, timeout_ms = DEFAULT_TIMEOUT_MS } = {}) {
    if (x === undefined || y === undefined || z === undefined) {
      return { success: false, error: 'x, y, z are required' };
    }
    if (!bot._client) {
      return { success: false, error: 'Bot not connected' };
    }

    // 确保已握手（未就绪则尝试一次握手）
    if (!servuxReady) {
      const hs = await ensureHandshake();
      if (!servuxReady) {
        return {
          success: false,
          error: 'Servux not available: ' + ((hs && hs.error) || 'handshake failed'),
        };
      }
    }

    const key = `${x},${y},${z}`;
    if (pending.has(key)) {
      return { success: false, error: `Duplicate request for container at ${key}` };
    }

    // 编码：type(3) + pos long
    const posBuf = Buffer.alloc(8);
    posBuf.writeBigInt64BE(posToLong(x, y, z), 0);
    const payload = Buffer.concat([writeVarInt(TYPE_C2S_BLOCK_ENTITY_REQUEST), posBuf]);
    if (!sendPayload(payload)) {
      return { success: false, error: 'Failed to send Servux request' };
    }

    return await new Promise((resolve) => {
      const timer = setTimeout(() => {
        pending.delete(key);
        resolve({ success: false, error: `Servux read timeout at (${x},${y},${z})` });
      }, timeout_ms);
      pending.set(key, { resolve, timer });
    });
  }

  return {
    servux_handshake,
    preview_container_at,
    // 内部：注册监听（由 bot_main 在 login 后调用）
    _register: register,
  };
}

module.exports = { createServuxHandlers };
