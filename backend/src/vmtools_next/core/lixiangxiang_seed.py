"""理想乡官网种子数据（启动时幂等写入）。

- organization_info：组织介绍占位文案（AI 起草，后台可编辑）
- members：22 位示例成员
- bases：地图基地展示占位
- gallery_categories + gallery_images：相册分类与占位图片

占位图片用纯 Python 标准库（zlib + struct）生成渐变 PNG，不依赖 Pillow：
- seed/avatar-*.png   成员头像（暖色系小尺寸）
- seed/photo-*.png    相册占位图（横向渐变）
- seed/base-*.png     基地占位图（横向渐变）
"""
from __future__ import annotations

import struct
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

from vmtools_next.data.models.lixiangxiang import (
    OrganizationInfoModel, MemberModel, LxBaseModel,
    GalleryCategoryModel, GalleryImageModel,
)
from vmtools_next.infra.logging import get_logger

logger = get_logger("lixiangxiang.seed")


# ──────────────────────────────────────────────
# 简易 PNG 生成（标准库，RGB 渐变）
# ──────────────────────────────────────────────

def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _lerp(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))  # type: ignore[return-value]


def write_gradient_png(
    path: Path,
    width: int,
    height: int,
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    diagonal: bool = False,
) -> None:
    """生成一张垂直（或对角）渐变 PNG。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            t = ((x + y) / (width + height)) if diagonal else (y / max(height - 1, 1))
            r, g, b = _lerp(c1, c2, min(max(t, 0.0), 1.0))
            raw += bytes((r, g, b))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


# ──────────────────────────────────────────────
# 占位内容
# ──────────────────────────────────────────────

INTRO_TEXT = (
    "「理想乡」诞生于 2023 年初春，是一群热爱《我的世界》的玩家共同筑造的生存服务器。"
    "我们不追求最快的进度，也不攀比最炫的装备——我们相信，方块之间藏着的，是人与人之间的温度。\n\n"
    "这里的每一座建筑都由成员亲手搭建，每一条道路都记录着共同走过的时光。"
    "我们坚持生存原味、共建共享，让每一位成员都能在这片大陆上留下自己的印记。\n\n"
    "**宗旨**：共建、共居、共享——让理想乡成为每一位成员在方块世界里的家。"
)

HISTORY_TEXT = (
    "2023 年 1 月 · 理想乡服务器正式开服，首批 6 位拓荒者选定主城选址，奠基「风起之地」。\n"
    "2023 年 5 月 · 主城一期完工，市政大厅落成，成员突破 10 人。\n"
    "2023 年 9 月 · 「望岳」环形山基地动工，成为服务器第一座大型标志性建筑群。\n"
    "2024 年 3 月 · 开通跨世界铁路，连接主城与四座卫星基地，物流体系成形。\n"
    "2024 年 11 月 · 「星野」海面基地竣工，灯光工程点亮整片海湾。\n"
    "2025 年 6 月 · 成员达到 22 人，举办第一届全服建筑大赛。\n"
    "2026 年 · 我们仍在继续书写理想乡的故事。"
)

SLOGAN = "方块之间，是家与远方"

SETTINGS = '{"founded": "2023-01", "qq_group": "", "world": "主世界", "server_address": ""}'

# (game_id, nickname, title, joined_at, specialty, bio)
MEMBERS_SEED: list[tuple[str, str, str, str, str, str]] = [
    ("VenusYu", "维纳斯", "领主 · 创始人", "2023-01", "总体规划 / 市政建设", "理想乡的缔造者，主持主城与四座基地的整体规划，相信好的秩序能让每个人玩得更自由。"),
    ("gxko", "GX", "管理员", "2023-03", "红石机械 / 自动化", "红石信徒，主城地铁与自动农场系统的设计者，最爱研究让生活更便利的机械。"),
    ("happyzhou2991", "周周", "管理员", "2023-03", "资源规划 / 后勤", "后勤总管，负责全服物资调度与仓库管理，永远在你缺东西的时候出现。"),
    ("KuangYuan", "旷远", "首席建筑师", "2023-05", "大型建筑 / 古典风格", "主城大教堂与「望岳」环形山的执笔人，擅长用方块书写宏大叙事。"),
    ("WildMango", "野生芒果", "建筑师", "2023-06", "景观园林 / 自然风格", "偏爱将建筑融入山水，河畔木屋与樱花林道的作者。"),
    ("HappyBoat", "快乐船", "建筑师", "2023-06", "港口 / 船舶建筑", "爱造船也爱造港口，星野海湾的灯塔与码头都出自他手。"),
    ("NyaNya", "喵酱", "建筑师", "2023-07", "内饰 / 温馨小屋", "专攻室内装修，能把一间 3×3 的小屋布置得温暖又精致。"),
    ("StoneGolem", "石像鬼", "工程师", "2023-08", "红石电路 / 机关", "沉迷各种红石机关与陷阱，也是全服最靠谱的电梯工程师。"),
    ("LunaMoth", "月蛾", "建筑师", "2023-09", "现代建筑 / 灯光", "星野海面基地的主创，擅长玻璃与灯光营造梦幻氛围。"),
    ("Bamboo", "青竹", "农夫", "2023-09", "农业 / 种植", "全服最全的农田与牧场经营者，南瓜田是他的骄傲。"),
    ("FrostByte", "霜字节", "工程师", "2023-10", "数据 / 插件", "服务器技术顾问，维护各类数据与插件，深藏功与名。"),
    ("Maple", "枫", "建筑师", "2023-11", "日式建筑", "「风起之地」东侧的日式小镇主创，秋日枫景是他的招牌。"),
    ("Coral", "珊瑚", "建筑师", "2023-12", "水下建筑", "海底观光隧道与珊瑚礁花园的作者，潜水爱好者的天堂。"),
    ("SilverFox", "银狐", "猎手", "2024-01", "战斗 / 探险", "开荒先锋，负责探索新地形与开辟远征航线，最爱下界探险。"),
    ("Panda", "熊猫", "后勤", "2024-02", "养殖 / 繁育", "全服动物繁育专家，稀有坐骑与宠物都能从他那里领养。"),
    ("Dawn", "晨曦", "建筑师", "2024-03", "欧式建筑", "主城西侧花园区与喷泉广场的设计师，擅长晨光下的建筑剪影。"),
    ("Raven", "渡鸦", "工程师", "2024-05", "铁路 / 交通", "跨世界铁路的总工程师，站台与信号系统全部出自他手。"),
    ("Jelly", "果冻", "建筑师", "2024-07", "甜品店 / 商业建筑", "主城商业街的甜品店老板，蛋糕塔是他的代表作。"),
    ("Mist", "雾", "探险家", "2024-09", "考古 / 遗迹", "沉迷寻找并复原世界遗迹，理想乡博物馆的常驻讲解员。"),
    ("Cloud", "云朵", "建筑师", "2025-02", "空中建筑", "建造了全服第一座浮空岛「云端花园」，是名副其实的造云师。"),
    ("Ember", "余烬", "匠人", "2025-06", "红石 / 自动化", "新一代红石新星，设计过全自动熔炉与分类机，潜力无限。"),
    ("Star", "星星", "后勤", "2025-08", "地图绘制 / 纪录", "负责全服地图测绘与年鉴记录，理想乡的活地图。"),
]

BASES_SEED: list[tuple[str, str, str, str]] = [
    ("主城 · 风起之地", "理想乡的发源地与政治文化中心。市政大厅、大教堂、商业街、喷泉广场依次排开，是每一位成员旅程的起点。", "seed/base-1.png", "-2673, 57, 9627"),
    ("望岳 · 环形山基地", "服务器第一座大型标志性建筑群，依环形山势而建，包含议事厅、藏书塔与环形观景廊，可俯瞰整片大陆。", "seed/base-2.png", "-120, 80, 640"),
    ("星野 · 海面基地", "用玻璃与灯光在海上筑起的梦幻之城。灯塔、码头与海面栈道构成浪漫夜景，是全服公认的拍照圣地。", "seed/base-3.png", "860, 64, -230"),
]

GALLERY_CATEGORIES_SEED: list[tuple[str, str]] = [
    ("建筑风景", "主城与各基地的标志性建筑、风景大片"),
    ("活动记录", "建筑大赛、开荒远征等活动的现场记录"),
    ("日常点滴", "成员们的生存日常、趣事与合影"),
]

# (category_name, title, description, filename, 配色)
GALLERY_IMAGES_SEED: list[tuple[str, str, str, str, tuple, tuple]] = [
    ("建筑风景", "主城大教堂 · 黄昏", "黄昏时分的市政大教堂，暖光透过彩窗洒在广场上。", "photo-1.png", (217, 119, 87), (120, 84, 74)),
    ("建筑风景", "望岳 · 环形山观景廊", "从观景廊远眺大陆，层峦叠嶂尽收眼底。", "photo-2.png", (138, 154, 91), (74, 92, 66)),
    ("建筑风景", "星野 · 海湾夜景", "夜幕降临后的星野海面基地，灯光如星河倒映。", "photo-3.png", (64, 84, 112), (24, 34, 58)),
    ("活动记录", "第一届全服建筑大赛", "2025 年夏，22 位成员同台竞技的盛况。", "photo-4.png", (176, 141, 87), (110, 84, 52)),
    ("活动记录", "下界远征队", "远征开荒小队的合影，身后是下界堡垒遗迹。", "photo-5.png", (122, 92, 74), (58, 40, 34)),
    ("日常点滴", "樱花林道漫步", "河畔樱花盛开的季节，成员们在林道散步。", "photo-6.png", (203, 148, 156), (130, 96, 116)),
]

AVATAR_COLORS: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [
    ((217, 119, 87), (150, 78, 56)),
    ((138, 154, 91), (92, 110, 62)),
    ((176, 141, 87), (118, 90, 56)),
    ((122, 140, 176), (78, 92, 126)),
    ((166, 124, 82), (110, 82, 56)),
    ((184, 86, 74), (122, 54, 46)),
    ((126, 116, 82), (86, 78, 54)),
    ((110, 138, 122), (72, 96, 84)),
    ((190, 168, 122), (128, 110, 78)),
    ((160, 110, 140), (106, 70, 92)),
    ((96, 122, 150), (60, 80, 104)),
    ((182, 130, 100), (122, 84, 62)),
]


def _write_seed_assets(lx_dir: Path) -> None:
    """生成成员头像 + 相册 + 基地占位图。"""
    seed_dir = lx_dir / "seed"
    for i, (c1, c2) in enumerate(AVATAR_COLORS, start=1):
        write_gradient_png(seed_dir / f"avatar-{i}.png", 128, 128, c1, c2, diagonal=True)
    for _, _, _, filename, c1, c2 in GALLERY_IMAGES_SEED:
        write_gradient_png(seed_dir / filename, 960, 540, c1, c2)
    for i, (_, _, filename, _) in enumerate(BASES_SEED, start=1):
        write_gradient_png(seed_dir / filename, 1200, 600, (217, 119, 87), (90, 74, 66))
    logger.info("Lixiangxiang seed assets written ({} avatars, {} photos, {} bases)",
                len(AVATAR_COLORS), len(GALLERY_IMAGES_SEED), len(BASES_SEED))


def seed_lixiangxiang(Session, static_dir: Path) -> None:
    """幂等写入理想乡种子数据（仅当表为空时）。"""
    try:
        db = Session()
        try:
            # ── 组织介绍 ──
            existing = db.query(OrganizationInfoModel).count()
            if existing == 0:
                now = datetime.now(timezone.utc)
                db.add_all([
                    OrganizationInfoModel(key="intro", value=INTRO_TEXT, updated_at=now),
                    OrganizationInfoModel(key="history", value=HISTORY_TEXT, updated_at=now),
                    OrganizationInfoModel(key="slogan", value=SLOGAN, updated_at=now),
                    OrganizationInfoModel(key="settings", value=SETTINGS, updated_at=now),
                ])
                logger.info("Lixiangxiang: seeded organization_info")

            # ── 成员 ──
            if db.query(MemberModel).count() == 0:
                now = datetime.now(timezone.utc)
                for i, (game_id, nickname, title, joined_at, specialty, bio) in enumerate(MEMBERS_SEED):
                    avatar = f"seed/avatar-{(i % len(AVATAR_COLORS)) + 1}.png"
                    db.add(MemberModel(
                        id=uuid.uuid4().hex,
                        game_id=game_id,
                        nickname=nickname,
                        title=title,
                        joined_at=joined_at,
                        specialty=specialty,
                        bio=bio,
                        avatar_path=f"/static/lixiangxiang/{avatar}",
                        sort_order=i,
                        created_at=now,
                        updated_at=now,
                    ))
                logger.info("Lixiangxiang: seeded {} members", len(MEMBERS_SEED))

            # ── 基地 ──
            if db.query(LxBaseModel).count() == 0:
                now = datetime.now(timezone.utc)
                for i, (name, desc, img, coords) in enumerate(BASES_SEED):
                    db.add(LxBaseModel(
                        id=uuid.uuid4().hex,
                        name=name,
                        description=desc,
                        image_path=f"/static/lixiangxiang/{img}",
                        coordinates=coords,
                        sort_order=i,
                        created_at=now,
                        updated_at=now,
                    ))
                logger.info("Lixiangxiang: seeded {} bases", len(BASES_SEED))

            # ── 相册分类 + 图片 ──
            if db.query(GalleryCategoryModel).count() == 0:
                now = datetime.now(timezone.utc)
                cat_ids: dict[str, str] = {}
                for i, (name, _desc) in enumerate(GALLERY_CATEGORIES_SEED):
                    cid = uuid.uuid4().hex
                    cat_ids[name] = cid
                    db.add(GalleryCategoryModel(id=cid, name=name, sort_order=i, created_at=now))
                if db.query(GalleryImageModel).count() == 0:
                    for i, (cat_name, title, desc, filename, _c1, _c2) in enumerate(GALLERY_IMAGES_SEED):
                        db.add(GalleryImageModel(
                            id=uuid.uuid4().hex,
                            category_id=cat_ids.get(cat_name),
                            image_path=f"/static/lixiangxiang/seed/{filename}",
                            title=title,
                            description=desc,
                            uploaded_at=now,
                        ))
                    logger.info("Lixiangxiang: seeded {} gallery images", len(GALLERY_IMAGES_SEED))

            db.commit()

            # ── 占位图文件（无论是否 seed 数据都确保存在，避免删除后缺图）──
            _write_seed_assets(static_dir / "lixiangxiang")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        logger.warning("Lixiangxiang seed skipped: {}", e)