#!/usr/bin/env python
"""
test_mineflayer_protocol.py — Mineflayer WebSocket 协议集成测试

验证:
1. Python MineflayerBridgeClient 连接到模拟 Node.js WS 服务
2. 发送请求并接收响应
3. 超时和错误处理

用法:
  python test_mineflayer_protocol.py [--ws-port 44444]
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from vmtools_next.adapters.mineflayer.mineflayer_client import MineflayerBridgeClient


async def run_tests():
    ws_port = int(sys.argv[1]) if len(sys.argv) > 1 else 44444

    print(f"\n{'='*60}")
    print(f"Mineflayer WS Protocol Test Suite")
    print(f"{'='*60}")
    print(f"Target: ws://127.0.0.1:{ws_port}")
    print()

    client = MineflayerBridgeClient(host="127.0.0.1", port=ws_port)

    passed = 0
    failed = 0

    async def test(name, fn):
        nonlocal passed, failed
        try:
            await fn()
            print(f"  ��� {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            failed += 1

    try:
        # 1. 连接
        print("\n[连接测试]")
        await test("connect", lambda: client.connect(timeout=5.0))

        # 2. 基本操��
        print("\n[移动操作]")
        await test("move_to", lambda: client.move_to(x=300, y=64, z=400))
        await test("look_at", lambda: client.look_at(x=300, y=65, z=400))
        await test("get_player_state", lambda: client.get_player_state())
        await test("cancel_pathing", lambda: client.cancel_pathing())
        await test("is_player_nearby", lambda: client.is_player_nearby(radius=10))

        # 3. 方��操作
        print("\n[方块操作]")
        await test("place_block", lambda: client.place_block(x=100, y=64, z=201, face="UP"))
        await test("dig_block", lambda: client.dig_block(x=100, y=64, z=200))
        await test("get_world_block_at", lambda: client.get_world_block_at(x=100, y=64, z=200))

        # 4. 背包操作
        print("\n[背包操作]")
        await test("get_inventory_snapshot", lambda: client.get_inventory_snapshot())
        await test("select_hotbar_item", lambda: client.select_hotbar_item(item_type="minecraft:dirt"))

        # 5. 容器操作
        print("\n[容器操作]")
        await test("open_container_at", lambda: client.open_container_at(x=100, y=64, z=200, timeout_ms=3000))
        await test("close_container", lambda: client.close_container(container_id="test"))
        await test("get_container_snapshot", lambda: client.get_container_snapshot(container_id="test"))
        await test("withdraw_container_item", lambda: client.withdraw_container_item(item_type="minecraft:dirt", count=32))
        await test("deposit_container_item", lambda: client.deposit_container_item(item_type="minecraft:stone", count=16))

        # 6. 聊天
        print("\n[聊天命令]")
        await test("send_chat", lambda: client.send_chat(message="Hello from VMTools test"))
        await test("run_command", lambda: client.run_command(command="/list"))

        # 7. 世界查��
        print("\n[世界查询]")
        await test("get_server_info", lambda: client.get_server_info())

        # 8. 超时测试
        print("\n[错误处理]")
        # 尝试不存在的method
        try:
            await client._send_request("nonexistent_method", {}, timeout=5.0)
            print("  ❌ unknown_method: 应该抛出异常但是没有")
            failed += 1
        except Exception:
            print("  ✅ unknown_method 正确报错")
            passed += 1

    finally:
        print("\n[清理]")
        await client.disconnect()
        print("  已断开连接")

    # 汇总
    print(f"\n{'='*60}")
    if failed:
        print(f"  结果: {passed}/{passed + failed} 通过, {failed} 失败 ❌")
    else:
        print(f"  结果: {passed}/{passed + failed} 全部���过 ✅ ALL PASSED")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
