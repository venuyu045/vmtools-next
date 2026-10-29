# 时装资产目录（`data/fashion-assets/`）

VMFashion mod 的资产文件根目录，由 `VMT_FASHION__ASSET_DIR` 配置（相对仓库根解析）。

## 目录结构

```
data/fashion-assets/
├── <pack_id>/
│   └── <version>/
│       └── <sha256前16位>-<filename>      # 管理端上传的资产（按内容去重）
└── <任意相对路径>                          # 手工放置的静态资产（assetKey 直接当路径）
```

- 上传接口：`POST /api/fashion/admin/assets`（site-admin，`multipart/form-data`）
- 文件名会被清洗（只保留字母/数字/`.`/`_`/`-`），扩展名白名单见
  `core/fashion_service.ALLOWED_ASSET_EXTS`
- 同一 `sha256` + 文件名只落盘一次
- 下载接口：`GET /api/fashion/assets/{assetKey}`，`Cache-Control: public, max-age=31536000, immutable`

## 两种放置方式

1. **上传流**（推荐）：上传资产 → 得到 `sha256` → 在目录条目里填 `assetKey` + `sha256`，
   下载时按 `sha256 → fashion_asset.storage_path` 解析。
2. **静态文件流**：直接把文件放到本目录（例如 `cape/dragon.png`），目录条目的
   `assetKey` 填同样的相对路径，`sha256` 留空 —— 下载时回退成「按 assetKey 找文件」。

> ⚠️ 目录穿越防护：`..`、绝对路径、盘符、空字节一律 404；不要在本目录下建符号链接指向外部。
>
> ⚠️ 生产部署请把本目录挂到持久卷，否则容器重建后资产丢失（目录条目还在，下载 404）。
