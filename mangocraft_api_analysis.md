# MangoCraft 服务器地图 API 分析报告

> 分析日期：2026-08-04 | 地图软件：BlueMap 5.16

## 服务器信息
- 地图地址：http://map.mangocraft.cn:2087
- 软件：BlueMap 5.16（Minecraft 3D 地图渲染）
- 世界（3个）：world（主世界）/ world_nether（地狱）/ world_the_end（末地）

## 已确认 API 端点

### 1. 在线玩家
GET /maps/{world}/live/players.json
返回：players[{uuid, name, foreign, position{x,y,z}, rotation{pitch,yaw,roll}}]
foreign=true 为跨服/外来玩家，三个世界均可查询，实时

### 2. 标记数据（地点/区域/领地）
GET /maps/{world}/live/markers.json

主世界 world 标记集：
- folia-metro-stations 地铁站点：0
- folia-metro-lines 地铁线路：1（Line 1 测试线路，全长21537格）
- mangopassport-landmarks 服务器地标：246（POI含类型）
- folia-regions 已加载区域范围：27（含 TPS/MSPT/实体数/玩家数=卡顿数据）
- markers 行政规划区：3（三城区/互通区/花都区）
- Residences 玩家领地：1459（extrude领地，含owner）

地狱 world_nether：地标0、区域10、领地290
末地 world_the_end：地标1（末地主城）、区域1、领地120

### 3. 世界设置
GET /maps/{world}/settings.json → 名称、瓦片配置、天空色、光照

### 4. 全局设置
GET /settings.json → 版本5.16、默认视角、缩放范围

### 5. 纹理数据
GET /maps/world/textures.json → 方块纹理映射（base64 PNG，~2.3MB）

### 6. 地图瓦片（图片）
GET /maps/{world}/tiles/{lod}/{x}/{z}（hires: lod=0；lowres: lod=1~3）

## 玩家数据（2026-08-04，37人在线）
AmpereOne(f), _Ju_Cat, gxko, OG_Cat_002, _FAKE_LUO_2, Venus_Yu, _FAKE_LUO_3, SixJoker, _Wyeoming, OG_Cat_003, a6355555, __gxko, Venus_Yu114(f), OG_Cat_004, _luoxiaolei7567, _baka____9(f), _happyzhou7878, Venus_Yu001, _34434hgfdtj, _User258888, .miaoxiaobao555, Uper1145, Qiuyue_bai(f), OG_Cat, _happyzhou1314, _happyzhou5200, Xia_Tian_Tian, Elysia_13, happyzhou2991, a63555555, _happyzhou9191(f), littlelittle1(f), Venus_Yu045, MC_lsny2, OG_Cat_001(f), Yuyuko_SaMa
(f)=foreign 跨服玩家

## 地标类型分布（主世界246个）
地铁轻轨31、商店金融22、建筑群22、行政组织17、道路交通11、工业11、景区9、学校8、机场8、港口8、纪念建筑7、饭店7、公园6、铁路高铁站5、宗教5、体育4、停车场3、服务器核心3、PVP3、医院2、传送点1、图书馆1、酒店1、监狱1

## 区域性能数据（folia-regions 核心字段）
Sections / Chunks / Entities / Players / TPS / MSPT
TPS 均约20.00，MSPT 最高28.27（Region@overworld[404,450]，实体2421个）
服务器当前负载良好，部分高实体区域 MSPT 偏高

## 备注
- /maps 返回500，实际用 /maps/{world}/... 直接访问
- 玩家头像 /maps/{world}/assets/playerheads/{uuid}.png 404（未启用）
- WebSocket 未启用（/live/websocket 404），HTTP 轮询获取
- 前端默认：players 1秒刷新、markers 10秒刷新