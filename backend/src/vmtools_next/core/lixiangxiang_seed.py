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
# MC 像素风格头像生成（8×8 方块脸 → 128×128 最近邻放大，RGBA）
# ──────────────────────────────────────────────

# 8×8 经典 MC 头部模板：H=头发 S=肤色 E=眼睛 .=透明
_MC_HEAD = [
    "..HHHH..",
    ".HHHHHH.",
    ".HHHHHH.",
    ".HSSSSH.",
    ".HSSSSH.",
    ".HSESESH",
    ".HSSSSH.",
    "..HHHH..",
]

# 22 组配色（肤色 / 发色 / 眼色）——每成员唯一组合
AVATAR_MC_PALETTES: list[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = [
    ((217, 168, 140), (43, 38, 32), (58, 46, 36)),   # 浅肤 · 墨黑
    ((176, 122, 90), (94, 59, 42), (58, 46, 36)),    # 棕肤 · 深棕
    ((217, 168, 140), (122, 74, 46), (58, 46, 36)),  # 浅肤 · 栗棕
    ((176, 122, 90), (176, 141, 62), (58, 46, 36)),  # 棕肤 · 金棕
    ((217, 168, 140), (140, 59, 46), (58, 46, 36)),  # 浅肤 · 红棕
    ((176, 122, 90), (106, 122, 140), (58, 46, 36)), # 棕肤 · 蓝灰
    ((217, 168, 140), (164, 155, 140), (58, 46, 36)),# 浅肤 · 银灰
    ((176, 122, 90), (43, 38, 32), (58, 46, 36)),    # 棕肤 · 墨黑
    ((217, 168, 140), (150, 104, 58), (58, 46, 36)), # 浅肤 · 榛棕
    ((176, 122, 90), (90, 122, 100), (58, 46, 36)),  # 棕肤 · 苔绿
    ((217, 168, 140), (122, 58, 86), (58, 46, 36)),  # 浅肤 · 酒红
    ((176, 122, 90), (72, 90, 120), (58, 46, 36)),   # 棕肤 · 海蓝
    ((217, 168, 140), (43, 38, 32), (58, 46, 36)),   # 循环变体（隔 12 人不同发色）
    ((176, 122, 90), (94, 59, 42), (58, 46, 36)),
    ((217, 168, 140), (122, 74, 46), (58, 46, 36)),
    ((176, 122, 90), (176, 141, 62), (58, 46, 36)),
    ((217, 168, 140), (140, 59, 46), (58, 46, 36)),
    ((176, 122, 90), (106, 122, 140), (58, 46, 36)),
    ((217, 168, 140), (164, 155, 140), (58, 46, 36)),
    ((176, 122, 90), (43, 38, 32), (58, 46, 36)),
    ((217, 168, 140), (150, 104, 58), (58, 46, 36)),
    ((176, 122, 90), (90, 122, 100), (58, 46, 36)),
]


def write_mc_avatar_png(path: Path, hair: tuple, skin: tuple, eye: tuple, scale: int = 16) -> None:
    """生成一张 MC 像素风格头像（8×8 → 128×128 最近邻放大，RGBA）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 8 * scale
    px: dict[str, tuple] = {"H": hair, "S": skin, "E": eye}
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        for x in range(size):
            ch = _MC_HEAD[y // scale][x // scale]
            if ch == ".":
                raw += bytes((0, 0, 0, 0))  # 透明
            else:
                r, g, b = px[ch]
                raw += bytes((r, g, b, 255))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
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
    "「理想乡」创建于 2024 年 12 月 2 日。我们的理念很简单：建立较为完善的基础生产体系，"
    "收容大部分游戏内生物，让组织内每一位组员都拥有自己心仪的家园。\n\n"
    "领地被划分为建筑区（包括各位的居住区）与工业区，建筑风格定向为**中世纪幻想风格**"
    "（国风建筑选址仍在规划中）。若有建筑需求，可在群内公示，材料由组织报销——"
    "在此感谢组织内各位后勤人员。\n\n"
    "理想乡拥有较为完善的基础生电设施，能够量产基础建筑方块与资源；**全物品主体已完成**，"
    "目前正在持续完善中。同时我们收容了大部分游戏内生物，为每一位成员的家园添上生机。\n\n"
    "我们急需中世纪风格与国风建筑师、会使用 masa 全家桶或精通 Java 生电基础的生电玩家，"
    "也欢迎想要在服务器内寻求安逸住所的休闲玩家与热爱冒险探索的玩家加入。"
    "理想乡没有苛捐杂税，大家因为热爱而相聚。\n\n"
    "**宗旨**：共建、共居、共享——愿思念伴随你进入理想乡。"
)

HISTORY_TEXT = (
    "2024 年 12 月 2 日 · 理想乡组织成立，「愿思念伴随你进入理想乡」自此成为我们的欢迎语。\n"
    "2024 年 · 选定领地选址，划分建筑区与工业区，确立中世纪幻想建筑风格。\n"
    "2025 年 · 基础生电设施成型，全物品主体完成并持续完善；大部分游戏内生物收容入园。\n"
    "2025 年 6 月 · 成员达到 22 人。\n"
    "2026 年 · 我们仍在继续书写理想乡的故事。"
)

SLOGAN = "愿思念伴随你进入理想乡"

SETTINGS = '{"founded": "2024-12", "qq_group": "", "world": "主世界", "server_address": ""}'

# (game_id, nickname, title, joined_at, specialty, bio)
MEMBERS_SEED: list[tuple[str, str, str, str, str, str]] = [
    ("VenusYu", "维纳斯", "领主 · 创始人", "2024-12", "总体规划 / 市政建设", "理想乡的缔造者，主持领地与四座基地的整体规划，相信好的秩序能让每个人玩得更自由。"),
    ("gxko", "GX", "管理员", "2024-12", "红石机械 / 自动化", "红石信徒，领地运输系统与自动农场系统的设计者，最爱研究让生活更便利的机械。"),
    ("happyzhou2991", "周周", "管理员", "2024-12", "资源规划 / 后勤", "后勤总管，负责组织物资调度与仓库管理，永远在你缺东西的时候出现。"),
    ("KuangYuan", "旷远", "首席建筑师", "2024-12", "大型建筑 / 古典风格", "领地标志性建筑与「领地」环形山的执笔人，擅长用方块书写宏大叙事。"),
    ("WildMango", "野生芒果", "建筑师", "2024-12", "景观园林 / 自然风格", "偏爱将建筑融入山水，河畔木屋与林间小径的作者。"),
    ("HappyBoat", "快乐船", "建筑师", "2024-12", "港口 / 船舶建筑", "爱造船也爱造港口，领地海湾的灯塔与码头都出自他手。"),
    ("NyaNya", "喵酱", "建筑师", "2024-12", "内饰 / 温馨小屋", "专攻室内装修，能把一间 3×3 的小屋布置得温暖又精致。"),
    ("StoneGolem", "石像鬼", "工程师", "2024-12", "红石电路 / 机关", "沉迷各种红石机关与陷阱，也是组织最靠谱的电梯工程师。"),
    ("LunaMoth", "月蛾", "建筑师", "2024-12", "现代建筑 / 灯光", "领地水景建筑的主创，擅长玻璃与灯光营造梦幻氛围。"),
    ("Bamboo", "青竹", "农夫", "2024-12", "农业 / 种植", "组织最全的农田与牧场经营者，南瓜田是他的骄傲。"),
    ("FrostByte", "霜字节", "工程师", "2024-12", "数据 / 插件", "组织技术顾问，维护各类数据与插件，深藏功与名。"),
    ("Maple", "枫", "建筑师", "2024-12", "街区规划 / 景观", "领地东侧街区主创，秋日景观是他的招牌。"),
    ("Coral", "珊瑚", "建筑师", "2024-12", "水下建筑", "海底观光隧道与珊瑚礁花园的作者，潜水爱好者的天堂。"),
    ("SilverFox", "银狐", "猎手", "2025-01", "战斗 / 探险", "开荒先锋，负责探索新地形与开辟远征航线，最爱下界探险。"),
    ("Panda", "熊猫", "后勤", "2025-01", "养殖 / 繁育", "组织动物繁育专家，稀有坐骑与宠物都能从他那里领养。"),
    ("Dawn", "晨曦", "建筑师", "2025-01", "欧式建筑", "领地西侧花园区与喷泉广场的设计师，擅长晨光下的建筑剪影。"),
    ("Raven", "渡鸦", "工程师", "2025-01", "铁路 / 交通", "跨世界铁路的总工程师，站台与信号系统全部出自他手。"),
    ("Jelly", "果冻", "建筑师", "2025-01", "甜品店 / 商业建筑", "领地商业街的甜品店老板，蛋糕塔是他的代表作。"),
    ("Mist", "雾", "探险家", "2025-01", "考古 / 遗迹", "沉迷寻找并复原世界遗迹，理想乡博物馆的常驻讲解员。"),
    ("Cloud", "云朵", "建筑师", "2025-02", "空中建筑", "建造了组织第一座浮空岛「云端花园」，是名副其实的造云师。"),
    ("Ember", "余烬", "匠人", "2025-06", "红石 / 自动化", "新一代红石新星，设计过全自动熔炉与分类机，潜力无限。"),
    ("Star", "星星", "后勤", "2025-08", "地图绘制 / 纪录", "负责组织地图测绘与年鉴记录，理想乡的活地图。"),
]

BASES_SEED: list[tuple[str, str, str, str]] = [
    ("建筑区 · 成员居住地", "领地内的建筑区承载着每一位成员的居住空间，建筑风格定向为中世纪幻想风格；国风建筑选址仍在规划中。若有建筑需求，可在群内公示，材料由组织报销。", "seed/base-1.png", ""),
    ("工业区 · 生电设施", "理想乡拥有较为完善的基础生电设施，能够量产基础建筑方块与资源；全物品主体已完成，目前正在持续完善中。", "seed/base-2.png", ""),
    ("生物收容园", "理想乡收容了大部分游戏内生物，为每一位成员的家园添上生机。", "seed/base-3.png", ""),
]

GALLERY_CATEGORIES_SEED: list[tuple[str, str]] = [
    ("建筑风景", "领地与各基地的标志性建筑、风景大片"),
    ("活动记录", "建筑大赛、开荒远征等活动的现场记录"),
    ("日常点滴", "成员们的生存日常、趣事与合影"),
]

# (category_name, title, description, filename, 配色) —— 占位标题，待替换为真实实拍
GALLERY_IMAGES_SEED: list[tuple[str, str, str, str, tuple, tuple]] = [
    ("建筑风景", "领地建筑群 · 中世纪幻想风格", "领地内的建筑区与成员居住地，实拍截图待补充。", "photo-1.png", (217, 119, 87), (120, 84, 74)),
    ("建筑风景", "工业区 · 生电设施", "量产基础建筑方块与资源的生电设施，实拍截图待补充。", "photo-2.png", (138, 154, 91), (74, 92, 66)),
    ("日常点滴", "生物收容园", "收容了大部分游戏内生物的家园一角，实拍截图待补充。", "photo-3.png", (64, 84, 112), (24, 34, 58)),
    ("活动记录", "组织活动 · 记录待补充", "理想乡成员共同活动的现场记录，实拍截图待补充。", "photo-4.png", (176, 141, 87), (110, 84, 52)),
    ("活动记录", "成员远征 · 记录待补充", "成员们共同探索与远征的记录，实拍截图待补充。", "photo-5.png", (122, 92, 74), (58, 40, 34)),
    ("日常点滴", "成员日常 · 记录待补充", "理想乡的日常点滴，实拍截图待补充。", "photo-6.png", (203, 148, 156), (130, 96, 116)),
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
    """生成 MC 头像 + 相册 + 基地占位图（文件已存在则跳过，避免每次启动重写）。"""
    seed_dir = lx_dir / "seed"
    for i, (skin, hair, eye) in enumerate(AVATAR_MC_PALETTES, start=1):
        p = seed_dir / f"avatar-mc-{i}.png"
        if not p.is_file():
            write_mc_avatar_png(p, hair, skin, eye)
    for _, _, _, filename, c1, c2 in GALLERY_IMAGES_SEED:
        p = seed_dir / filename
        if not p.is_file():
            write_gradient_png(p, 960, 540, c1, c2)
    for i, (_, _, filename, _) in enumerate(BASES_SEED, start=1):
        p = seed_dir / filename
        if not p.is_file():
            write_gradient_png(p, 1200, 600, (217, 119, 87), (90, 74, 66))
    logger.info("Lixiangxiang seed assets ensured ({} MC avatars, {} photos, {} bases)",
                len(AVATAR_MC_PALETTES), len(GALLERY_IMAGES_SEED), len(BASES_SEED))


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
                    avatar = f"seed/avatar-mc-{(i % len(AVATAR_MC_PALETTES)) + 1}.png"
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
            else:
                # 幂等迁移：旧渐变头像（seed/avatar-N.png）→ MC 像素头像
                migrated = 0
                for m in db.query(MemberModel).all():
                    if m.avatar_path and m.avatar_path.startswith("/static/lixiangxiang/seed/avatar-") and "-mc-" not in m.avatar_path:
                        idx = (m.sort_order or 0) % len(AVATAR_MC_PALETTES)
                        m.avatar_path = f"/static/lixiangxiang/seed/avatar-mc-{idx + 1}.png"
                        migrated += 1
                if migrated:
                    db.commit()
                    logger.info("Lixiangxiang: migrated {} member avatars to MC style", migrated)

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