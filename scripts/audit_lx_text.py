"""只读审查：拉取理想乡官网全部文案数据并打印。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8080"


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


print("===== INFO =====")
info = get("/api/lixiangxiang/info")
print("slogan:", info["slogan"])
print("founded:", info["settings"].get("founded"))
print("--- intro ---")
print(info["intro"])
print("--- history ---")
print(info["history"])

print("\n===== BASES =====")
for b in get("/api/lixiangxiang/bases"):
    print(f'- {b["name"]} | coords: {b["coordinates"]} | {b["description"][:40]}')

print("\n===== MEMBERS =====")
for m in get("/api/lixiangxiang/members"):
    print(f'- {m["nickname"] or m["game_id"]:<8} | {m["game_id"]:<14} | 加入 {m["joined_at"]:<9} | {m["title"]}')

print("\n===== CATEGORIES =====")
for c in get("/api/lixiangxiang/categories"):
    print(f'- {c["name"]} ({c["image_count"]})')

print("\n===== IMAGES =====")
for g in get("/api/lixiangxiang/images"):
    print(f'- {g["title"]} | {(g.get("description") or "")[:36]}')