<div align="center">
  <img src="icon.png" width="128" alt="Telegram 文件转存 Bot">
</div>

# Telegram 文件转存 Bot

[English](README_EN.md) | 中文

把 Telegram 里收到的文件自动下载并上传到网盘。基于 Telethon（MTProto）。

## 特性

- **大文件**：走 MTProto，单文件最大 2GB；大于 10MB 的文件用多连接并行下载。
- **多网盘**：通过 rclone 支持 70+ 种后端（OneDrive、Google Drive、Dropbox、S3、WebDAV 等）。
- **多来源**：私聊发送文件、转发文件、群组里引用消息 @ bot、监听频道自动下载新发布文件。
- **OAuth 一键授权**：OneDrive、Google Drive 等 20 种 OAuth 网盘用 rclone 自带的应用授权，不用自己注册应用、不用填 client_id / secret。
- **断点续传**：rclone 上传自带断点续传和自动重试，失败了点重试按钮就能再传。
- **时区**：每个用户用 `/timezone` 设自己的时区。
- **白名单**：只有白名单中指定的用户能用 bot。

## 要求

- Python 3.10+
- rclone（已验证 1.76）
- Telegram API 凭证（api_id、api_hash）
- 一个 Telegram bot（@BotFather 创建）

## 快速开始

```bash
git clone https://github.com/longli928/telegram_bot_to_rclone.git
cd telegram_bot_to_rclone
pip install -r requirements.txt
cp .env.example .env
# 填好 .env
rclone config providers > providers.json
python app.py
```

后台运行：

```bash
nohup python3 -u app.py > bot.log 2>&1 &
```

看到 `Bot 已上线` 就是跑起来了。

## 配置

`.env` 里填：

| 变量 | 说明 |
| --- | --- |
| `API_ID` | Telegram 应用的 api_id |
| `API_HASH` | Telegram 应用的 api_hash |
| `BOT_TOKEN` | bot 的 token |
| `ALLOWED_USER_IDS` | 能用这个 bot 的 Telegram 用户 ID，多个用逗号隔开；必填，为空谁都不能用 |
| `PARALLEL_CONNECTIONS` | 大于 10MB 的文件并行下载连接数，默认 6 |
| `MAX_CONCURRENT_FILES` | 同时处理的文件数上限，默认 5；设 0 为不限制 |
| `TIMEZONE` | 没设过时区的用户的默认时区，默认 Asia/Shanghai |
| `DOWNLOAD_DIR` | 下载临时目录，默认 ./downloads |

## 使用

### 私聊

直接发文件或转发文件给 bot，bot 下载完自动上传到默认存储（或你选的存储）。

### 群组

把 bot 拉进群，引用一条带文件的消息并 @ bot，bot 就下载它。只有白名单用户能触发，bot 在群里只响应 @。

### 频道

1. 把 bot 加进频道当管理员。
2. 在 bot 私聊里用 `/channels`，转发一条频道消息（或发频道 @用户名 / ID）加进白名单。
3. 之后这个频道新帖里的文件会自动下载上传，进度发到你的私聊。

### 命令

| 命令 | 说明 |
| --- | --- |
| `/start` | 开始使用 |
| `/help` | 使用帮助 |
| `/storage` | 存储管理（添加 / 选择默认 / 修改保存位置 / 删除） |
| `/channels` | 频道管理（白名单） |
| `/timezone` | 查看或设置时区 |

### 存储管理

`/storage` 里可以：

- **添加存储**：从 rclone 支持的全部后端里选。OAuth 的网盘（OneDrive、Google Drive 等）不用填 client_id / secret，bot 会发登录链接给你，登录后把跳回来的 localhost 链接发回 bot 就行。非 OAuth 的按提示填参数。
- **导入**：把 rclone 配置里已有的 remote 注册进来。
- **选择默认存储**：设了默认，收到文件就直接往它发；没设默认又有多个存储时，下载完会问存到哪个。
- **修改保存位置**：改某个存储的文件夹，不用重新添加。
- **删除存储**：删掉注册表和 rclone 配置里的对应 remote，云端文件不受影响。

## 文件结构

```
.
├── app.py               # bot 主程序
├── requirements.txt     # 依赖
├── providers.json       # rclone 后端列表（rclone config providers 生成，不会自动创建）
├── .env.example         # 配置模板
├── icon.png             # 图标
├── README.md            # 中文说明
├── README_EN.md         # 英文说明
├── storages.json        # 网盘注册表和默认存储（运行中自动创建）
├── channels.json        # 频道白名单（运行中自动创建）
├── timezones.json       # 每个用户的时区设置（运行中自动创建）
├── bot_session.session  # Telethon 会话
└── downloads/           # 下载临时目录，传完就清
```

## 安全

- 只有 `ALLOWED_USER_IDS` 白名单里的用户能用 bot；为空时谁都不能用。
- 网盘凭据只存在 rclone 自己的配置文件里（`~/.config/rclone/rclone.conf`），bot 不另存一份；`storages.json`、`channels.json`、`timezones.json` 都是 chmod 600。
- 添加存储时在聊天里发的密钥，bot 读完就删，不记日志；token 不会出现在日志里。
- `.env` 不要提交到公开仓库。

## 常见问题

**`providers.json` 是什么？**

rclone 后端列表，供 `/storage` 的添加菜单用。用 `rclone config providers > providers.json` 生成；rclone 升级后重新生成一次。如果没有这个文件，bot 只提供 5 个内置后端（OneDrive、Google Drive、Dropbox、S3、WebDAV）。

**OAuth 登录时贴回来的链接报错？**

链接有问题（没 code、没 state、state 对不上、回放拿不到 code）时，bot 会直接告诉你哪不对，并结束这次添加。注意要贴最新那条消息里的链接，旧链接的 state 对不上。

**频道里的文件没自动下载？**

先确认 bot 已加进频道当管理员，并且频道已在 `/channels` 白名单里。
