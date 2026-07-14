"""WebSocket sniffer — connect to QQ Bot gateway and print group_openid.

Run this, then @bot in the group. group_openid will appear in logs.
"""
import asyncio
import json
import httpx


APP_ID = "1905191614"
APP_SECRET = "REDACTED_QQ_APP_SECRET"


async def get_token() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": APP_ID, "clientSecret": APP_SECRET},
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
    print("获取 token...")
    token = await get_token()
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
                "intents": 0xFFFF,
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

            # Log group-related events
            if t in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE", "MESSAGE_CREATE"):
                gid = d.get("group_openid", d.get("group_id", "??"))
                gname = d.get("group_name", "??")
                content = d.get("content", "") or str(d.get("event_id", ""))
                print(f"🟢 群消息! group_openid={gid} content={content[:50]}")
            
            if "group_openid" in str(d).lower() and d.get("group_openid"):
                print(f"🔍 group_openid: {d['group_openid']}")
                
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
