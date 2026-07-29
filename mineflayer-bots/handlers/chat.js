/**
 * chat.js — 聊天/命令 handler
 *
 * 方法：
 *   send_chat(message)       → 发送聊天消息
 *   run_command(command)     → 运行 /command
 */

/** @param {import('mineflayer').Bot} bot */
function createChatHandlers(bot) {

  function send_chat({ message } = {}) {
    try {
      bot.chat(message);
      return { success: true };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  function run_command({ command } = {}) {
    try {
      bot.chat('/' + command.replace(/^\//, ''));
      return { success: true, command };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }

  return { send_chat, run_command };
}

module.exports = { createChatHandlers };
