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

/**
 * 解析 Servux 返回的 NBT。
 *
 * Servux 服务端（Fabric/Forge）用 Minecraft 网络序列化（FriendlyByteBuf.writeNbt）
 * 发送 NBT：root tag 后【不含 root name】；而 prismarine-nbt 期望标准 NBT
 * （root tag + 2 字节 root name）。直接解析会报
 *   "Read error for undefined : Missing characters in string"
 * 修复：解析失败时在 root tag 后补 2 字节空名（0000）重试。
 */
async function parseNbt(buf) {
  try {
    return await nbt.parse(buf);
  } catch (firstErr) {
    if (buf && buf.length > 1) {
      // root tag(1B) + 0000(空 root name) + 剩余 payload
      const fixed = Buffer.concat([buf.subarray(0, 1), Buffer.from([0x00, 0x00]), buf.subarray(1)]);
      try {
        return await nbt.parse(fixed);
      } catch {
        throw firstErr; // 补名后仍失败 → 抛原始错误
      }
    }
    throw firstErr;
  }
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
 * 判断物品是否为潜影盒（潜影盒内可装物品，需要递归展开内容）。
 */
function isShulkerBoxItem(itemId) {
  const s = String(itemId || '').toLowerCase();
  return s.endsWith('shulker_box') || s === 'minecraft:shulker';
}

/**
 * 从物品 entry 中提取方块实体数据 compound（兼容旧格式 tag.BlockEntityTag 与
 * 1.21.x 组件化 components["minecraft:block_entity_data"]）。
 * @param {object} entry prismarine-nbt compound tag
 * @returns {object|null} compound tag（含 .type/.value），找不到返回 null
 */
function findBlockEntityData(entry) {
  if (!entry || typeof entry !== 'object') return null;
  try {
    // 旧格式：tag.BlockEntityTag（1.20 及以前）
    if (entry.tag && entry.tag.value && entry.tag.value.BlockEntityTag) {
      return entry.tag.value.BlockEntityTag;
    }
  } catch (e) { /* ignore */ }
  try {
    // 1.21.x 组件化：components["minecraft:block_entity_data"]
    if (entry.components && entry.components.value &&
        entry.components.value['minecraft:block_entity_data']) {
      return entry.components.value['minecraft:block_entity_data'];
    }
  } catch (e) { /* ignore */ }
  return null;
}

/**
 * 从 list tag 中取出元素数组（兼容 prismarine-nbt 2.x 与 3.x 结构差异）：
 *   2.x: { type: <元素类型>, value: [扁平元素] }
 *   3.x: { type: 'list', value: { type: <元素类型>, value: [扁平元素] } }
 * @returns {Array|null}
 */
function getListArray(listTag) {
  if (!listTag) return null;
  if (Array.isArray(listTag.value)) return listTag.value;
  if (listTag.value && Array.isArray(listTag.value.value)) return listTag.value.value;
  return null;
}

/**
 * 递归收集物品列表（含潜影盒内容展开）。
 * @param {object} listTag prismarine-nbt list tag（Items/Inventory/Container）
 * @param {number} depth 当前递归深度（0=容器层）
 * @param {number} maxDepth 潜影盒最大展开深度（超出不再展开）
 * @param {Array} out 结果数组
 */
function collectListItems(listTag, depth, maxDepth, out) {
  const arr = getListArray(listTag);
  if (!arr) return;
  for (const entry of arr) {
    if (!entry || typeof entry !== 'object') continue;
    const id = entry.id?.value || entry.Id?.value || '';
    if (!id) continue;
    const count = entry.count?.value ?? entry.Count?.value ?? 1;
    const slot = entry.Slot?.value ?? entry.slot?.value ?? -1;
    const itemId = String(id);
    out.push({
      item_id: itemId,
      display_name: friendlyName(itemId),
      count: Number(count) || 0,
      slot: Number(slot),
    });
    // 潜影盒内容递归展开（深度限制，防嵌套潜影盒无限递归）
    if (isShulkerBoxItem(itemId)) {
      // [debug] 打印潜影盒物品的原始 entry 结构，用于排查 NBT 格式
      console.log(`\x1b[33m[servux][dbg]\x1b[0m shulker entry keys=${Object.keys(entry).join(',')} id=${itemId}`);
      console.log(`\x1b[33m[servux][dbg]\x1b[0m entry JSON=${JSON.stringify(entry).slice(0, 1000)}`);
      const be = findBlockEntityData(entry);
      console.log(`\x1b[33m[servux][dbg]\x1b[0m blockEntityData=${be ? JSON.stringify(be).slice(0, 1000) : 'null'}`);
    }
    if (isShulkerBoxItem(itemId) && depth < maxDepth) {
      const be = findBlockEntityData(entry);
      if (be && be.value) {
        collectShulkerContents(be.value, depth + 1, maxDepth, out);
      }
    }
  }
}

/**
 * 从方块实体 compound 的 value 中展开潜影盒内部 Items。
 * @param {object} beValue 方块实体 compound 的 value（可能含 Items，或再包一层 BlockEntityTag）
 * @param {number} depth 当前递归深度
 * @param {number} maxDepth 潜影盒最大展开深度
 * @param {Array} out 结果数组
 */
function collectShulkerContents(beValue, depth, maxDepth, out) {
  let target = beValue;
  if (target.BlockEntityTag && target.BlockEntityTag.type === 'compound') {
    target = target.BlockEntityTag.value;
  }
  const listTag = target.Items || target.Inventory || target.Container;
  if (getListArray(listTag)) {
    collectListItems(listTag, depth, maxDepth, out);
  }
}

/**
 * 从方块实体 NBT 中提取物品列表（兼容 1.21.x 组件化格式与旧格式）。
 * 潜影盒物品会自动递归展开其内部内容（受 maxDepth 限制）。
 * @param {object} compoundValue prismarine-nbt compound value
 * @param {number} depth 当前递归深度（默认 0）
 * @param {number} maxDepth 潜影盒最大展开深度（默认 3，对应 config.shulker_recursion_depth）
 * @returns {Array<{item_id, display_name, count, slot}>}
 */
function extractItems(compoundValue, depth = 0, maxDepth = 3) {
  const items = [];
  if (!compoundValue || typeof compoundValue !== 'object') return items;

  // 1.21.x: Items / Inventory / Container 列表（组件化：id 为字符串 + components）
  // 旧版:   Items 列表（id 为字符串 + tag）
  const listTag = compoundValue.Items || compoundValue.Inventory || compoundValue.Container;
  if (getListArray(listTag)) {
    collectListItems(listTag, depth, maxDepth, items);
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
  // v1 协议（minihud LTS/1.21.11, PROTOCOL_VERSION=1）：block/entity request 需带自增 transactionId
  let nextTxnId = 0;

  // ── 发送原始 payload ──
  function sendPayload(payloadBuffer) {
    try {
      bot._client.write('custom_payload', {
        channel: CHANNEL,
        data: payloadBuffer,
      });
      return true;
    } catch (err) {
      console.error(`\x1b[31m[servux]\x1b[0m send payload failed:`, err.message);
      return false;
    }
  }

  // ── 握手 ──
  function ensureHandshake() {
    if (servuxReady) return Promise.resolve({ success: true, version: servuxVersion });
    if (handshakePromise) return handshakePromise;

    handshakePromise = new Promise((resolve) => {
      handshakeResolve = resolve;

      // 握手 NBT：模仿 MiniHUD（version 为字符串 MOD_STRING）。
      // 实测：服务器(servux-lophine)对 int version=1 的握手返回"简化NBT"(Items无组件)；
      // 对 MiniHUD 的 string version 握手可能返回"完整NBT"(Items含组件/潜影盒内容)。
      const verStr = 'minihud-fabric-1.21.11-26.2';
      const metaNbt = Buffer.concat([
        Buffer.from([0x0a, 0x08, 0x00, 0x07]),
        Buffer.from('version'),
        Buffer.from([0x00, 0x1b]),
        Buffer.from(verStr),
        Buffer.from([0x00]),
      ]);
      sendPayload(Buffer.concat([writeVarInt(TYPE_C2S_METADATA_REQUEST), metaNbt]));

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
        // 服务器可能运行旧版 Servux（协议 v1，如 servux-lophine-1.21.11-DEV），
        // 新版为 v2。v1/v2 的 metadata/block-entity 帧结构一致（差异仅在版本号），
        // 这里同时接受 1 和 2，实际能力按服务器上报的 servux 版本执行。
        if ((version === PROTOCOL_VERSION || version === 1) && typeof servux === 'string' && servux.startsWith('servux-')) {
          servuxReady = true;
          servuxVersion = servux;
          console.log(`\x1b[36m[servux]\x1b[0m handshake OK, connected to`, servux);
          // 唤醒等待中的握手调用方
          if (handshakeResolve) {
            const resolveHs = handshakeResolve;
            handshakeResolve = null;
            resolveHs({ success: true, version: servux });
          }
        } else {
          console.warn(`\x1b[33m[servux]\x1b[0m handshake mismatch: version=%s servux=%s`, version, servux);
          sendPayload(Buffer.concat([writeVarInt(TYPE_C2S_UNREGISTER_REPLY), encodeNbt({})]));
        }
      } else if (type === TYPE_S2C_BLOCK_NBT_RESPONSE_SIMPLE) {
        const posRes = longToPos(buf, offset);
        const key = `${posRes.x},${posRes.y},${posRes.z}`;
        offset = posRes.offset;
        // [debug] 打印原始 NBT 字节（前 500B），排查组件是否被旧版 prismarine-nbt 丢弃
        console.log(`\x1b[33m[servux][dbg]\x1b[0m rawNBT hex=${buf.subarray(offset).subarray(0, 500).toString('hex')}`);
        const parsed = await parseNbt(buf.subarray(offset));
        const compoundValue = getCompoundValue(parsed);
        // [debug] 打印容器 NBT 顶层结构，排查潜影盒内容 NBT 位置
        console.log(`\x1b[33m[servux][dbg]\x1b[0m container(${key}) top keys=${Object.keys(compoundValue).join(',')}`);
        console.log(`\x1b[33m[servux][dbg]\x1b[0m container NBT=${JSON.stringify(compoundValue).slice(0, 2500)}`);
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
      console.error(`\x1b[31m[servux]\x1b[0m handle payload error:`, err.message);
    }
  }

  // ── 注册 custom_payload 监听 ──
  function register() {
    if (!bot._client) return false;
    // 注意：不要发送 register_channels！
    // 实测 minecraft-data 1.21.11 的 register_channels 包 ID 与服务器实际协议不匹配，
    // 发送会导致服务器按 accept_teleportation 解码失败直接踢下线
    // （"Failed to decode packet 'serverbound/minecraft:accept_teleportation'"）。
    // Servux 服务端会在客户端进入游戏后【主动推送】S2C_METADATA，无需注册通道。
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

    // 编码（v1 协议，minihud LTS/1.21.11）：
    // C2S_BLOCK_ENTITY_REQUEST = varint(type=3) + varint(transactionId) + BlockPos(long)
    // 注意：v1 必须带 transactionId，否则服务端读取 BlockPos 时数据不足会解码失败踢人。
    const posBuf = Buffer.alloc(8);
    posBuf.writeBigInt64BE(posToLong(x, y, z), 0);
    const payload = Buffer.concat([
      writeVarInt(TYPE_C2S_BLOCK_ENTITY_REQUEST),
      writeVarInt(nextTxnId++),
      posBuf,
    ]);
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

module.exports = { createServuxHandlers, extractItems, isShulkerBoxItem, findBlockEntityData };
