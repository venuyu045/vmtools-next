"""CLI tool: list QQ groups the bot has joined (prints group_openid)."""
import asyncio
import json
from vmtools_next.adapters.qqbot.qq_bot_client import QqBotClient


async def main():
    client = QqBotClient(
        app_id="1905191614",
        app_secret="REDACTED_QQ_APP_SECRET",
    )
    await client.start()
    groups = await client.list_groups()
    await client.stop()

    if not groups:
        print("❌ 机器人尚未加入任何 QQ 群")
        print("   请先把机器人拉进群，然后重新运行此脚本")
        return

    print(f"找到 {len(groups)} 个群:\n")
    for g in groups:
        print(f"  openid: {g.get('group_openid', '??')}")
        print(f"  名称:   {g.get('group_name', '未知')}")
        print(f"  人数:   {g.get('member_count', '?')}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
