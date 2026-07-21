# 服务器运维协作指南

## 协作流程

```
我出指令 → 你执行 → 粘贴结果 → 我分析/给下一步
```

每次需要操作服务器时，直接把结果贴回来，我会根据输出判断下一步。

---

## 1. 日常同步（部署最新代码）

代码先推到 Gitee，然后服务器拉取：

```bash
ssh root@106.12.180.1

# 进入项目目录
cd /opt/vmtools-next/vmtools-next

# 拉取最新代码
git fetch gitee master && git reset --hard gitee/master

# 前端纯静态文件，拉取即生效，无需重启
```

> **注意**：如果改了后端 Python 代码，拉取后需要重启服务：
> ```bash
> supervisorctl restart vmtools-next   # 或用实际的服务管理方式
> ```

---

## 2. 常见问题排查清单

执行命令后把输出贴给我。

### 2.1 页面打开是旧版本 / 没更新

```bash
# 检查当前 git commit 是否最新
cd /opt/vmtools-next/vmtools-next && git log --oneline -3
```

### 2.2 服务挂了 / 页面打不开

```bash
# 检查进程是否在跑
ps aux | grep python

# 检查端口是否在监听
ss -tlnp | grep 8080

# 看最近的服务日志
tail -100 /opt/vmtools-next/vmtools-next/logs/*.log
```

### 2.3 前端白屏 / 报错

```bash
# 检查前端文件是否完整
ls -la /opt/vmtools-next/vmtools-next/vmtools-next/backend/static/
ls /opt/vmtools-next/vmtools-next/vmtools-next/backend/static/index.html
```

浏览器打开 F12 Console，截图或复制报错信息贴给我。

### 2.4 MCC 实例启不来

```bash
# 查看后端日志中 MCC 相关的错误
grep -i "mcc\|error\|traceback" /opt/vmtools-next/vmtools-next/logs/*.log | tail -50

# 检查实例目录是否存在
ls /opt/vmtools/mcc-instances/

# 检查 MCC 程序是否存在
ls -la /opt/vmtools/mcc-runtime/MinecraftClient.exe
```

### 2.5 Bot 连接不上

```bash
# 检查 MCP 端口是否开放
ss -tlnp | grep 33333

# 看 Bot 相关的 API 日志
grep -i "bot\|connect\|mcp" /opt/vmtools-next/vmtools-next/logs/*.log | tail -30
```

### 2.6 数据库问题

```bash
# 数据库位置
ls -la /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db

# 检查权限
stat /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db

# 备份数据库（操作前必做）
cp /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db /opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db.bak.$(date +%Y%m%d_%H%M%S)
```

### 2.7 磁盘空间

```bash
df -h
du -sh /opt/vmtools-next/
du -sh /opt/vmtools/mcc-instances/
```

---

## 3. 常用路径速查

| 用途 | 路径 |
|------|------|
| 项目根目录 | `/opt/vmtools-next/vmtools-next/` |
| 后端代码 | `/opt/vmtools-next/vmtools-next/vmtools-next/` |
| 前端静态文件 | `/opt/vmtools-next/vmtools-next/vmtools-next/backend/static/` |
| SQLite 数据库 | `/opt/vmtools-next/vmtools-next/vmtools-next/vmtools-next.db` |
| 日志目录 | `/opt/vmtools-next/vmtools-next/logs/` |
| MCC 实例目录 | `/opt/vmtools/mcc-instances/` |
| MCC 运行时程序 | `/opt/vmtools/mcc-runtime/MinecraftClient.exe` |
| Gitee 仓库 | `https://gitee.com/de-spider/vmtools-next.git` |

---

## 4. 紧急恢复

### 分支分叉冲突

```bash
cd /opt/vmtools-next/vmtools-next
git fetch gitee master
git reset --hard gitee/master

# 如果 config.yaml 被覆盖了，恢复它：
git checkout origin/master -- vmtools-next/config/config.yaml
```

### 服务挂了快速重启

```bash
# 先看服务管理方式
systemctl status vmtools-next 2>/dev/null || supervisorctl status vmtools-next 2>/dev/null

# 重启（根据上面的结果选一个）
systemctl restart vmtools-next
# 或
supervisorctl restart vmtools-next
```
