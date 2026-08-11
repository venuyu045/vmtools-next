"""一次性更新理想乡 bases/images 为真实信息（领地方区描述 + 中性占位标题）。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8080"


def api(method, path, body=None, token=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    return json.loads(urllib.request.urlopen(req).read())


token = api("POST", "/api/auth/login", {"game_id": "VenusYu", "password": "jxy080405"})["token"]

# ── bases：虚构基地名/坐标 → 真实分区描述 ──
new_bases = [
    ("建筑区 · 成员居住地",
     "领地内的建筑区承载着每一位成员的居住空间，建筑风格定向为中世纪幻想风格；国风建筑选址仍在规划中。若有建筑需求，可在群内公示，材料由组织报销。", ""),
    ("工业区 · 生电设施",
     "理想乡拥有较为完善的基础生电设施，能够量产基础建筑方块与资源；全物品主体已完成，目前正在持续完善中。", ""),
    ("生物收容园",
     "理想乡收容了大部分游戏内生物，为每一位成员的家园添上生机。", ""),
]
bases = sorted(api("GET", "/api/lixiangxiang/bases"), key=lambda x: x["sort_order"])
for b, (n, d, c) in zip(bases, new_bases):
    api("PUT", f"/api/lixiangxiang/bases/{b['id']}", {"name": n, "description": d, "coordinates": c}, token)
    print("base updated:", n)

# ── images：虚构标题 → 中性占位（与中世纪幻想风格一致） ──
new_images = [
    ("领地建筑群 · 中世纪幻想风格", "领地内的建筑区与成员居住地，实拍截图待补充。"),
    ("工业区 · 生电设施", "量产基础建筑方块与资源的生电设施，实拍截图待补充。"),
    ("生物收容园", "收容了大部分游戏内生物的家园一角，实拍截图待补充。"),
    ("组织活动 · 记录待补充", "理想乡成员共同活动的现场记录，实拍截图待补充。"),
    ("成员远征 · 记录待补充", "成员们共同探索与远征的记录，实拍截图待补充。"),
    ("成员日常 · 记录待补充", "理想乡的日常点滴，实拍截图待补充。"),
]
images = api("GET", "/api/lixiangxiang/images")
for g, (t, d) in zip(images, new_images):
    api("PUT", f"/api/lixiangxiang/images/{g['id']}", {"title": t, "description": d}, token)
    print("image updated:", t)

print("ALL DONE")