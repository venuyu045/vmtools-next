"""CLI tool: list QQ groups the bot has joined (prints group_openid).

凭据从 config.yaml 的 ``qqbot`` 段读取（app_id / app_secret），不在代码中硬编码。
"""
import asyncio
from vmtools_next.adapters.qqbot.qq_bot_client import QqBotClient
from vmtools_next.config import get_config


async def main():
    cfg = get_config().qqbot
    if not cfg.enabled or not cfg.app_id or not cfg.app_secret:
        print("❌ qqbot 未启用或缺少 app_id / app_secret，请先在 config.yaml 的 qqbot 段配置后重试。")
        return
    client = QqBotClient(
        app_id=cfg.app_id,
        app_secret=cfg.app_secret,
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
