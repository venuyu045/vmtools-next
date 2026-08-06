"""Minecraft 物品中文名映射（zh_cn）。

提供 item_id → 中文名 的查询；未知物品回退为可读英文名。
覆盖常见物品与常用仓库材料；可按需扩充。
"""

# minecraft:xxx 前缀可省略；键为 item_id（不含命名空间）
_ZH: dict[str, str] = {
    # ── 建筑/材料（含用户仓库实测物品） ──
    "nether_brick": "下界砖", "soul_sand": "灵魂沙", "crying_obsidian": "哭泣黑曜石",
    "obsidian": "黑曜石", "blackstone": "黑石", "oak_log": "橡木原木",
    "gold_block": "金块", "leather": "皮革", "iron_nugget": "铁粒",
    "shulker_box": "潜影盒", "shulker_shell": "潜影壳", "shears": "剪刀",
    "cooked_porkchop": "熟猪排", "cooked_beef": "熟牛排", "cooked_chicken": "熟鸡肉",
    "cooked_mutton": "熟羊肉", "cooked_rabbit": "熟兔肉", "cooked_cod": "熟鳕鱼",
    "cooked_salmon": "熟鲑鱼", "bread": "面包", "apple": "苹果",
    "golden_apple": "金苹果", "enchanted_golden_apple": "附魔金苹果",
    "diamond": "钻石", "emerald": "绿宝石", "iron_ingot": "铁锭",
    "gold_ingot": "金锭", "copper_ingot": "铜锭", "netherite_ingot": "下界合金锭",
    "netherite_scrap": "下界合金碎片", "coal": "煤炭", "charcoal": "木炭",
    "redstone": "红石粉", "lapis_lazuli": "青金石", "quartz": "下界石英",
    "amethyst_shard": "紫水晶碎片", "flint": "燧石",
    "iron_block": "铁块", "diamond_block": "钻石块", "emerald_block": "绿宝石块",
    "coal_block": "煤炭块", "redstone_block": "红石块", "lapis_block": "青金石块",
    "netherite_block": "下界合金块", "copper_block": "铜块", "quartz_block": "石英块",
    "iron_ore": "铁矿石", "gold_ore": "金矿石", "diamond_ore": "钻石矿石",
    "emerald_ore": "绿宝石矿石", "coal_ore": "煤矿石", "redstone_ore": "红石矿石",
    "lapis_ore": "青金石矿石", "copper_ore": "铜矿石", "deepslate_iron_ore": "深层铁矿石",
    "deepslate_gold_ore": "深层金矿石", "deepslate_diamond_ore": "深层钻石矿石",
    "deepslate_emerald_ore": "深层绿宝石矿石", "deepslate_coal_ore": "深层煤矿石",
    "deepslate_redstone_ore": "深层红石矿石", "deepslate_lapis_ore": "深层青金石矿石",
    "deepslate_copper_ore": "深层铜矿石",
    "cobblestone": "圆石", "stone": "石头", "andesite": "安山岩",
    "diorite": "闪长岩", "granite": "花岗岩", "deepslate": "深板岩",
    "tuff": "凝灰岩", "dripstone_block": "滴水石", "calcite": "方解石",
    "sand": "沙子", "red_sand": "红沙", "gravel": "沙砾", "clay": "黏土",
    "dirt": "泥土", "grass_block": "草方块", "podzol": "灰化土",
    "moss_block": "苔藓块", "snow_block": "雪块", "ice": "冰",
    "packed_ice": "浮冰", "blue_ice": "蓝冰",
    "oak_planks": "橡木木板", "spruce_log": "云杉原木", "spruce_planks": "云杉木板",
    "birch_log": "白桦原木", "birch_planks": "白桦木板", "jungle_log": "丛林木原木",
    "jungle_planks": "丛林木板", "acacia_log": "金合欢原木", "acacia_planks": "金合欢木板",
    "dark_oak_log": "深色橡木原木", "dark_oak_planks": "深色橡木木板",
    "mangrove_log": "红树木原木", "mangrove_planks": "红树木板",
    "cherry_log": "樱花木原木", "cherry_planks": "樱花木木板",
    "crimson_stem": "绯红菌柄", "crimson_planks": "绯红木板",
    "warped_stem": "诡异菌柄", "warped_planks": "诡异木板",
    "glass": "玻璃", "glass_pane": "玻璃板", "terracotta": "陶瓦",
    "white_terracotta": "白色陶瓦", "brick": "红砖", "bricks": "砖块",
    "stone_bricks": "石砖", "mossy_stone_bricks": "苔石砖", "cracked_stone_bricks": "裂纹石砖",
    "nether_bricks": "下界砖块", "red_nether_bricks": "红色下界砖块",
    "end_stone": "末地石", "end_stone_bricks": "末地石砖",
    "purpur_block": "紫珀块", "purpur_pillar": "紫珀柱",
    "prismarine": "海晶石", "prismarine_bricks": "海晶石砖", "dark_prismarine": "暗海晶石",
    "sea_lantern": "海晶灯", "glowstone": "萤石", "magma_block": "岩浆块",
    "slime_block": "黏液块", "honey_block": "蜜脾块", "hay_block": "干草块",
    "dried_kelp_block": "干海带块", "bone_block": "骨块", "wither_skeleton_skull": "凋灵骷髅头颅",
    "sculk": "幽匿块", "sculk_sensor": "幽匿感测体",
    "wheat": "小麦", "wheat_seeds": "小麦种子", "carrot": "胡萝卜",
    "potato": "马铃薯", "baked_potato": "烤马铃薯", "beetroot": "甜菜根",
    "beetroot_seeds": "甜菜种子", "pumpkin": "南瓜", "melon_slice": "西瓜片",
    "sugar_cane": "甘蔗", "sugar": "糖", "egg": "鸡蛋", "milk_bucket": "牛奶桶",
    "cocoa_beans": "可可豆", "honey_bottle": "蜂蜜瓶", "honeycomb": "蜜脾",
    "sweet_berries": "甜浆果", "glow_berries": "发光浆果", "bamboo": "竹子",
    "paper": "纸", "book": "书", "writable_book": "书与笔", "written_book": "成书",
    "enchanted_book": "附魔书", "name_tag": "命名牌",
    "stick": "木棍", "string": "线", "feather": "羽毛", "bone": "骨头",
    "bone_meal": "骨粉", "gunpowder": "火药", "blaze_powder": "烈焰粉",
    "blaze_rod": "烈焰棒", "ender_pearl": "末影珍珠", "ender_eye": "末影之眼",
    "end_crystal": "末影水晶", "ghast_tear": "恶魂之泪", "magma_cream": "岩浆膏",
    "slime_ball": "黏液球", "phantom_membrane": "幻翼膜", "nautilus_shell": "鹦鹉螺壳",
    "heart_of_the_sea": "海洋之心", "prismarine_shard": "海晶碎片", "prismarine_crystals": "海晶砂粒",
    "echo_shard": "回响碎片", "disc_fragment_5": "唱片残片",
    "dragon_breath": "龙息", "dragon_egg": "龙蛋", "elytra": "鞘翅",
    "totem_of_undying": "不死图腾", "trident": "三叉戟",
    "nether_star": "下界之星", "beacon": "信标", "conduit": "潮涌核心",
    "experience_bottle": "附魔之瓶",
    "shield": "盾牌", "bow": "弓", "arrow": "箭", "spectral_arrow": "光灵箭",
    "tipped_arrow": "药箭", "crossbow": "弩", "fishing_rod": "钓鱼竿",
    "wooden_sword": "木剑", "stone_sword": "石剑", "iron_sword": "铁剑",
    "golden_sword": "金剑", "diamond_sword": "钻石剑", "netherite_sword": "下界合金剑",
    "wooden_pickaxe": "木镐", "stone_pickaxe": "石镐", "iron_pickaxe": "铁镐",
    "golden_pickaxe": "金镐", "diamond_pickaxe": "钻石镐", "netherite_pickaxe": "下界合金镐",
    "wooden_axe": "木斧", "stone_axe": "石斧", "iron_axe": "铁斧",
    "golden_axe": "金斧", "diamond_axe": "钻石斧", "netherite_axe": "下界合金斧",
    "wooden_shovel": "木锹", "stone_shovel": "石锹", "iron_shovel": "铁锹",
    "golden_shovel": "金锹", "diamond_shovel": "钻石锹", "netherite_shovel": "下界合金锹",
    "wooden_hoe": "木锄", "stone_hoe": "石锄", "iron_hoe": "铁锄",
    "golden_hoe": "金锄", "diamond_hoe": "钻石锄", "netherite_hoe": "下界合金锄",
    "iron_helmet": "铁头盔", "iron_chestplate": "铁胸甲", "iron_leggings": "铁护腿",
    "iron_boots": "铁靴子", "diamond_helmet": "钻石头盔", "diamond_chestplate": "钻石胸甲",
    "diamond_leggings": "钻石护腿", "diamond_boots": "钻石靴子",
    "netherite_helmet": "下界合金头盔", "netherite_chestplate": "下界合金胸甲",
    "netherite_leggings": "下界合金护腿", "netherite_boots": "下界合金靴子",
    "leather_helmet": "皮革帽子", "leather_chestplate": "皮革外套",
    "leather_leggings": "皮革裤子", "leather_boots": "皮革靴子",
    "chainmail_helmet": "锁链头盔", "chainmail_chestplate": "锁链胸甲",
    "chainmail_leggings": "锁链护腿", "chainmail_boots": "锁链靴子",
    "golden_helmet": "金头盔", "golden_chestplate": "金胸甲",
    "golden_leggings": "金护腿", "golden_boots": "金靴子",
    "bucket": "桶", "water_bucket": "水桶", "lava_bucket": "熔岩桶",
    "flint_and_steel": "打火石", "compass": "指南针", "recovery_compass": "追溯指针",
    "clock": "时钟", "spyglass": "望远镜", "map": "地图", "filled_map": "地图",
    "lead": "拴绳", "saddle": "鞍", "carrot_on_a_stick": "胡萝卜钓竿",
    "warped_fungus_on_a_stick": "诡异菌钓竿",
    "redstone_torch": "红石火把", "redstone_lamp": "红石灯", "repeater": "红石中继器",
    "comparator": "红石比较器", "lever": "拉杆", "button": "按钮",
    "stone_button": "石头按钮", "oak_button": "橡木按钮",
    "pressure_plate": "压力板", "stone_pressure_plate": "石头压力板",
    "oak_pressure_plate": "橡木压力板", "tripwire_hook": "绊线钩",
    "piston": "活塞", "sticky_piston": "黏性活塞", "observer": "侦测器",
    "dispenser": "发射器", "dropper": "投掷器", "hopper": "漏斗",
    "chest": "箱子", "trapped_chest": "陷阱箱", "ender_chest": "末影箱",
    "barrel": "木桶", "furnace": "熔炉", "blast_furnace": "高炉",
    "smoker": "烟熏炉", "brewing_stand": "酿造台", "cauldron": "炼药锅",
    "crafting_table": "工作台", "anvil": "铁砧", "enchanting_table": "附魔台",
    "grindstone": "砂轮", "stonecutter": "切石机", "loom": "织布机",
    "cartography_table": "制图台", "smithing_table": "锻造台", "fletching_table": "制箭台",
    "lectern": "讲台", "jukebox": "唱片机", "note_block": "音符盒",
    "beacon_block": "信标", "campfire": "营火", "soul_campfire": "灵魂营火",
    "lantern": "灯笼", "soul_lantern": "灵魂灯笼", "torch": "火把",
    "soul_torch": "灵魂火把", "ladder": "梯子", "rail": "铁轨",
    "powered_rail": "动力铁轨", "detector_rail": "探测铁轨", "activator_rail": "激活铁轨",
    "minecart": "矿车", "chest_minecart": "箱子矿车", "furnace_minecart": "熔炉矿车",
    "tnt_minecart": "TNT矿车", "hopper_minecart": "漏斗矿车",
    "boat": "船", "oak_boat": "橡木船", "spruce_boat": "云杉木船",
    "birch_boat": "白桦木船", "jungle_boat": "丛林船", "acacia_boat": "金合欢船",
    "dark_oak_boat": "深色橡木船", "mangrove_boat": "红树船",
    "tnt": "TNT", "target": "标靶", "trial_spawner": "试炼刷怪笼",
    "vault": "宝库", "sculk_shrieker": "幽匿尖啸体", "sculk_catalyst": "幽匿催发体",
    "spawner": "刷怪笼", "skeleton_spawn_egg": "骷髅刷怪蛋",
    "zombie_spawn_egg": "僵尸刷怪蛋", "creeper_spawn_egg": "苦力怕刷怪蛋",
    "ender_dragon_spawn_egg": "末影龙刷怪蛋", "wither_spawn_egg": "凋灵刷怪蛋",
    "snowball": "雪球", "snow": "雪",
    "potion": "药水", "glass_bottle": "玻璃瓶", "splash_potion": "喷溅药水",
    "lingering_potion": "滞留药水", "ominous_bottle": "不祥之瓶",
    # 潜影盒变体
    "white_shulker_box": "白色潜影盒", "orange_shulker_box": "橙色潜影盒",
    "magenta_shulker_box": "品红色潜影盒", "light_blue_shulker_box": "淡蓝色潜影盒",
    "yellow_shulker_box": "黄色潜影盒", "lime_shulker_box": "黄绿色潜影盒",
    "pink_shulker_box": "粉红色潜影盒", "gray_shulker_box": "灰色潜影盒",
    "light_gray_shulker_box": "淡灰色潜影盒", "cyan_shulker_box": "青色潜影盒",
    "purple_shulker_box": "紫色潜影盒", "blue_shulker_box": "蓝色潜影盒",
    "brown_shulker_box": "棕色潜影盒", "green_shulker_box": "绿色潜影盒",
    "red_shulker_box": "红色潜影盒", "black_shulker_box": "黑色潜影盒",
    # 羊毛/混凝土/陶瓦
    "white_wool": "白色羊毛", "black_wool": "黑色羊毛", "red_wool": "红色羊毛",
    "blue_wool": "蓝色羊毛", "green_wool": "绿色羊毛",
    "white_concrete": "白色混凝土", "black_concrete": "黑色混凝土",
    "red_concrete": "红色混凝土", "blue_concrete": "蓝色混凝土", "green_concrete": "绿色混凝土",
    "white_concrete_powder": "白色混凝土粉末", "black_concrete_powder": "黑色混凝土粉末",
    # 花卉/植物
    "dandelion": "蒲公英", "poppy": "虞美人", "blue_orchid": "兰花",
    "allium": "绒球葱", "azure_bluet": "蓝花美耳草", "red_tulip": "红色郁金香",
    "orange_tulip": "橙色郁金香", "white_tulip": "白色郁金香", "pink_tulip": "粉红色郁金香",
    "oxeye_daisy": "滨菊", "cornflower": "矢车菊", "lily_of_the_valley": "铃兰",
    "wither_rose": "凋灵玫瑰", "sunflower": "向日葵", "lilac": "丁香",
    "rose_bush": "玫瑰丛", "peony": "牡丹", "vine": "藤蔓",
    "lily_pad": "睡莲", "kelp": "海带", "seagrass": "海草", "cactus": "仙人掌",
    "mushroom": "蘑菇", "brown_mushroom": "棕色蘑菇", "red_mushroom": "红色蘑菇",
    "crimson_fungus": "绯红菌", "warped_fungus": "诡异菌", "crimson_roots": "绯红菌索",
    "warped_roots": "诡异菌索", "nether_wart": "下界疣", "chorus_fruit": "紫颂果",
    "popped_chorus_fruit": "爆裂紫颂果", "chorus_flower": "紫颂花",
    "melon": "西瓜", "pumpkin_seeds": "南瓜种子", "melon_seeds": "西瓜种子",
    "torchflower_seeds": "火把花种子", "pitcher_pod": "瓶子草荚",
    "oak_sapling": "橡树树苗", "spruce_sapling": "云杉树苗", "birch_sapling": "白桦树苗",
    "jungle_sapling": "丛林树苗", "acacia_sapling": "金合欢树苗",
    "dark_oak_sapling": "深色橡树树苗", "cherry_sapling": "樱花树苗",
    # 附魔/经验
    "air": "空气", "debug_stick": "调试棒", "knowledge_book": "知识之书",
}

# 常见中文搜索关键词 → item_id 片段（便于中文名搜索兜底）
_ZH_INDEX: dict[str, str] = {}
for _item, _name in _ZH.items():
    _ZH_INDEX.setdefault(_item, _item)


def get_item_zh(item_id: str, fallback: str | None = None) -> str:
    """返回物品中文名；未知物品回退可读英文名（minecraft:xxx → Xxx Xxx）。"""
    if not item_id:
        return fallback or ""
    key = item_id.split(":")[-1] if ":" in item_id else item_id
    zh = _ZH.get(key)
    if zh:
        return zh
    if fallback:
        return fallback
    # 可读英文：下划线/中划线 → 空格，首字母大写
    words = key.replace("_", " ").replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) if words else key


def search_zh_keywords(q: str) -> list[str]:
    """中文关键词 → 匹配的 item_id 列表（用于搜索 API 的中文名匹配）。"""
    q = (q or "").strip().lower()
    if not q:
        return []
    hits = []
    for _key, _name in _ZH.items():
        if q in _name.lower():
            hits.append(_key)
    return hits
