"""WebSocket sniffer — connect to QQ Bot gateway and print group_openid.

Run this, then @bot in the group. group_openid will appear in logs.

凭据从 config.yaml 的 ``qqbot`` 段读取（app_id / app_secret），不在代码中硬编码。
"""
import asyncio
import json
import sys
import httpx

from vmtools_next.config import get_config


async def get_token(app_id: str, app_secret: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": app_id, "clientSecret": app_secret},
        )
        data = resp.json()
        return data["access_token"]


async def get_gateway_url(token: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.sgroup.qq.com/gateway/bot",
            headers={"Authorization": f"QQBot {token}"},
        )
        return resp.json()["url"]


async def main():
    cfg = get_config().qqbot
    if not cfg.enabled or not cfg.app_id or not cfg.app_secret:
        print("❌ qqbot 未启用或缺少 app_id / app_secret，请先在 config.yaml 的 qqbot 段配置后重试。")
        sys.exit(1)
    print(f"获取 token (app_id={cfg.app_id})...")
    token = await get_token(cfg.app_id, cfg.app_secret)
    print("获取网关地址...")
    ws_url = await get_gateway_url(token)
    print(f"连接 WebSocket: {ws_url}")

    import websockets
    async with websockets.connect(ws_url) as ws:
        # Send identify
        identify = {
            "op": 2,
            "d": {
                "token": f"QQBot {token}",
                "intents": 1 | (1 << 25),  # GUILDS + GROUP_AT_MESSAGE
                "shard": [0, 1],
                "properties": {
                    "$os": "linux",
                    "$browser": "vmtools",
                    "$device": "server",
                },
            },
        }
        await ws.send(json.dumps(identify))

        print("\n✅ 已连接！现在去群里 @机器人 发任意消息，group_openid 会出现在这里:\n")

        async for raw in ws:
            event = json.loads(raw)
            op = event.get("op")
            d = event.get("d", {})
            t = event.get("t")

            # Log group-related events - extract sender openid, NOT bot openid
            if t in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE", "MESSAGE_CREATE"):
                author = d.get("author", {})
                sender_id = author.get("id") or author.get("member_openid") or author.get("user_openid", "??")
                sender_name = author.get("username", "") or author.get("nick", "") or "??"
                content = d.get("content", "")
                print(f"🟢 发送者 openid={sender_id} 名称={sender_name} 消息={content[:60]}")
                print(f"   (内容中 <@xxx> 是机器人的 openid，忽略它)")
            
            if d.get("author", {}).get("id"):
                print(f"🔍 发送者 openid: {d['author']['id']}")
                
            # Log ready event
            if t == "READY":
                user = d.get("user", {})
                print(f"👤 Bot Ready: {user.get('username', '?')} ({user.get('id', '?')})")

            # Heartbeat
            if op == 10:
                interval = d["heartbeat_interval"]
                print(f"📡 Heartbeat interval: {interval}ms")
                asyncio.create_task(_heartbeat(ws, interval))


async def _heartbeat(ws, interval_ms):
    while True:
        await asyncio.sleep(interval_ms / 1000)
        try:
            await ws.send(json.dumps({"op": 1, "d": {}}))
        except Exception:
            break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye")
