# 服务器运维协作指南

## 协作流程

```
我出指令 → 你执行 → 粘贴结果 → 我分析/给下一步
```

---

## ⚠️ 0. 最重要：数据库 = 你的 Bot 数据，目录不对就丢！

**SQLite 数据库路径是相对路径 `vmtools-next.db`，取决于你在哪个目录启动 uvicorn！**

| 启动目录 | 数据库会跑到 | 结果 |
|----------|-------------|------|
| `/opt/vmtools-next/vmtools-next/vmtools-next/` ✅ | `/opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db` | **正确！89MB 你的数据** |
| `/opt/vmtools-next/vmtools-next/backend/` ❌ | `/opt/vmtools-next/vmtools-next/backend/vmtools-next.db` | **空库！数据全丢** |

**所有启动/重启命令必须从这个目录执行：**

```bash
cd /opt/vmtools-next/vmtools-next/vmtools-next
```

---

## 1. 日常同步 + 重启（改前端 + 改后端都用这个）

```bash
cd /opt/vmtools-next/vmtools-next
git fetch origin master && git reset --hard origin/master

# 如果改了后端 Python 代码，杀进程重启：
pkill -f "python.*main:app"
cd /opt/vmtools-next/vmtools-next/vmtools-next
nohup ../backend/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080 > /tmp/vmtools.log 2>&1 &

# 前端纯静态文件，拉取后刷新即生效，不需要重启
```

---

## 2. 常见问题排查

### 2.1 数据全没了 / Bot 实例全空了

```bash
# 检查是不是有人在 wrong directory 启动过
ls -la /opt/vmtools-next/vmtools-next/backend/vmtools-next.db
# 如果这个文件存在且很小（几百KB），说明有人从 backend/ 启动了
# 把当前进程杀掉，从正确目录重启即可恢复

ls -la /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db
# 89MB 的是你的真实数据库
```

### 2.2 重启后数据没回来

```bash
# 杀掉所有相关进程
pkill -f "python.*main:app"
pkill -f "python main.py"

# 确认都死了
ps aux | grep -E "python.*main|uvicorn" | grep -v grep

# 从正确目录重启
cd /opt/vmtools-next/vmtools-next/vmtools-next
nohup ../backend/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080 > /tmp/vmtools.log 2>&1 &
```

### 2.3 服务挂了 / 页面打不开

```bash
ps aux | grep -E "python.*main|uvicorn" | grep -v grep
ss -tlnp | grep 8080
tail -50 /tmp/vmtools.log
```

### 2.4 MCC 实例启不来

```bash
grep -i "mcc\|error\|traceback" /opt/vmtools-next/vmtools-next/logs/*.log | tail -50
ls /opt/vmtools/mcc-instances/
ls -la /opt/vmtools/mcc-runtime/MinecraftClient.exe
```

### 2.5 Bot 连接不上

```bash
ss -tlnp | grep 33333
grep -i "bot\|connect\|mcp" /opt/vmtools-next/vmtools-next/logs/*.log | tail -30
```

### 2.6 数据库备份

```bash
cp /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db.bak.$(date +%Y%m%d_%H%M%S)
```

---

## 3. 路径速查

| 用途 | 路径 |
|------|------|
| 项目根目录 | `/opt/vmtools-next/vmtools-next/` |
| 启动 uvicorn 的正确目录 | `/opt/vmtools-next/vmtools-next/vmtools-next/` |
| SQLite 数据库 | `/opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db` |
| 前端静态文件 | `/opt/vmtools-next/vmtools-next/vmtools-next/backend/static/` |
| Gitee 仓库 | `https://gitee.com/de-spider/vmtools-next.git` |

---

## 4. 紧急恢复

### 分支分叉

```bash
cd /opt/vmtools-next/vmtools-next
git fetch origin master && git reset --hard origin/master
```

### 数据"丢了"（其实没丢）

```bash
pkill -f "python.*main:app"
cd /opt/vmtools-next/vmtools-next/vmtools-next
nohup ../backend/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080 > /tmp/vmtools.log 2>&1 &
```
