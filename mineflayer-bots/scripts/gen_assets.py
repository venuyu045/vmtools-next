#!/usr/bin/env python3
"""
gen_assets.py — 从 Mojang 官方 client.jar 重建 minecraft-assets/data/26.1 资产

用途：prismarine-viewer 渲染 26.x 版本需要真实方块模型/纹理资产。官方 jar 中
26.x 的模型纹理引用是 {"sprite": "minecraft:block/xxx"} 对象格式，旧版
prismarine-viewer 只认字符串，因此此处统一归一化为 "block/xxx" 字符串。

重建流程（完整见交接文档 3.13）：
  ① python3 scripts/gen_assets.py          # 本脚本：生成 data/26.1 资产
  ② node_modules 的 minecraft-assets/index.js 注册 '26.1' 条目（由 patches/ 自动应用）
  ③ node viewer/prerender.js -f            # 生成 blocksStates/26.1.json 与纹理图集
  ④ webpack --config webpack.config.js     # 重新打包 worker.js/index.js（勿全量，防 OOM）
  ⑤ mineflayer 的 time.js 补丁（由 patches/ 自动应用，26.1 时间包协议）

依赖：
  - 26.2 官方 client.jar（默认 /tmp/mcjar262/client.jar，可用环境变量 MC_JAR 覆盖）
  - 输出目录默认 minecraft-assets/minecraft-assets/data/26.1（可用环境变量 ASSETS_DATA 覆盖）
"""
import zipfile, json, os

JAR = os.environ.get('MC_JAR', '/tmp/mcjar262/client.jar')
DATA = os.environ.get(
    'ASSETS_DATA',
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', 'node_modules', 'minecraft-assets', 'minecraft-assets', 'data', '26.1'))

z = zipfile.ZipFile(JAR)
os.makedirs(DATA, exist_ok=True)


def norm_texture(v):
    """26.x 纹理引用新格式 {"sprite": "minecraft:block/xxx", ...} → "minecraft:block/xxx"（字符串）。
    注意：保留 sprite 的值原样（含 minecraft: 前缀）——jar 中原本就是字符串的引用（如
    "block/bamboo_stalk"）保持不动；旧版 prismarine-viewer 的 atlas/modelsBuilder 只认字符串引用。"""
    if isinstance(v, dict) and 'sprite' in v:
        s = v['sprite']
        if isinstance(s, str):
            return s
    return v


def norm_model_textures(m):
    """对单个模型对象归一化 textures 字段（递归处理 textures dict 值）。"""
    if isinstance(m, dict):
        if isinstance(m.get('textures'), dict):
            m['textures'] = {k: norm_texture(v) for k, v in m['textures'].items()}
    return m


# 1) blocks_states.json（聚合 blockstates/*.json，保留 variants/multipart；格式与 jar 一致无需转换）
bs = {}
for n in z.namelist():
    if n.startswith('assets/minecraft/blockstates/') and n.endswith('.json'):
        name = n.split('/')[-1][:-5]
        bs[name] = json.loads(z.read(n))
json.dump(bs, open(f'{DATA}/blocks_states.json', 'w'), ensure_ascii=False)
print('blocks_states:', len(bs))

# 2) blocks_models.json（聚合 models/block/*.json，key=相对路径；归一化 sprite 纹理引用）
bm = {}
for n in z.namelist():
    if n.startswith('assets/minecraft/models/block/') and n.endswith('.json'):
        rel = n[len('assets/minecraft/models/block/'):-5]
        bm[rel] = norm_model_textures(json.loads(z.read(n)))
json.dump(bm, open(f'{DATA}/blocks_models.json', 'w'), ensure_ascii=False)
print('blocks_models:', len(bm))

# 3) blocks/ 纹理 png（textures/block/*.png）
bd = f'{DATA}/blocks'
os.makedirs(bd, exist_ok=True)
count = 0
for n in z.namelist():
    if n.startswith('assets/minecraft/textures/block/') and n.endswith('.png'):
        with open(f'{bd}/{n.split("/")[-1]}', 'wb') as f:
            f.write(z.read(n))
        count += 1
print('block textures:', count)

# 4) 占位 json（prerender 不直接使用，但 index.js require 需要文件存在）
json.dump([], open(f'{DATA}/blocks_textures.json', 'w'))
json.dump([], open(f'{DATA}/items_textures.json', 'w'))
json.dump([], open(f'{DATA}/texture_content.json', 'w'))

# 5) 复制 colormap/effect 等（渲染着色需要）
for sub in ['colormap', 'effect', 'environment', 'misc', 'particle', 'mob_effect', 'painting']:
    src = f'assets/minecraft/textures/{sub}/'
    dst = f'{DATA}/{sub}'
    for n in z.namelist():
        if n.startswith(src) and n.endswith('.png'):
            os.makedirs(dst, exist_ok=True)
            with open(f'{dst}/{n.split("/")[-1]}', 'wb') as f:
                f.write(z.read(n))
print('extra textures copied')
print('DONE')
