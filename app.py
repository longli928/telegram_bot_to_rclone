#!/usr/bin/env python3
"""
Telegram Bot -> 多网盘（rclone）
部署：把 app.py 放在服务器上，用 nohup 跑

- 用 Telethon (MTProto, api_id/api_hash + bot_token)，绕过 Bot API 20MB 限制，
  大文件也能下载（Telegram 单文件上限按账号，普通账号 2GB）
- 下载：大于 10MB 用多连接并行分片下载，连接数由 PARALLEL_CONNECTIONS 配置
- 上传：只用 rclone copyto 到用户选的存储，Graph 直传方案已删掉；
  rclone 失败就抛错，bot 给用户弹重试按钮
- 存储管理（/storage）：在 bot 菜单里添加 rclone 支持的全部网盘（providers.json 里 71 种，
  由 `rclone config providers` 生成，跟着装的 rclone 版本走），凭据写进 rclone 自己的
  配置文件（/root/.config/rclone/rclone.conf，跟现在 [od] 的放法一样）；
  注册表和默认存储存在 storages.json 里（chmod 600）。设了默认存储，收到文件就直接往它发；
  没设默认又有多个存储时，下载完会问用户存到哪个。
  全新部署时 storages.json 是空的（没有预置的存储、没有默认文件夹），
  文件夹在添加存储时用选文件夹器定，不用提前在 .env 里想好。
  OAuth 的网盘（OneDrive / Google Drive / Dropbox 等 20 种）不用填 client_id/secret：
  bot 跑 `rclone authorize`（用 rclone 自带的应用），把登录链接发给用户，用户登录后把
  跳回来的 localhost 链接发回 bot，bot 回放给本机上的 authorize 服务换 token。
  贴回来的链接先对 state：对不上就是贴了上一次的旧链接；链接有问题（没 code、没 state、
  state 对不上、回放拿不到 code）就直接提示哪不对，然后结束这次添加、同时杀掉 authorize
  进程，不一直等着。重新开始一个添加流程会先把上一次没走完的 authorize 进程杀掉，免得
  旧进程占着端口、新链接对不上。
  注意：OAuth 后端的 remote 不能走 `rclone config create`（它会重新跑一遍 OAuth、在那
  等 code 卡住，实测 onedrive 即使给了 token 和 drive_id 也超时），所以直接写 rclone.conf；
  OneDrive 还要先拿 drive_id/drive_type（问 Graph 的 /me/drive），不然 lsd 会报缺这两项。
  非 OAuth 的按提示填配置，还能再补 key=value 参数。
  所有 rclone 子进程都用 stdin=DEVNULL，免得哪个命令等交互输入卡住；报错记日志前先抹掉 token。
  选文件夹时直接调 rclone 列目录（lsjson），按钮进目录/选定/新建文件夹，也能手动输入；
  OAuth/手动的在选文件夹期间用临时配置（/tmp/rclone-picker-<uid>.conf，流程结束就删），
  不污染真实配置。存储列表优先显示用户起的名字（没有再显示网盘名），添加界面的后端按字母 A-Z 排。
  存储管理里还有“修改保存位置”：选一个存储，同样用文件夹选择器改它在 storages.json 里的
  folder（从现在的文件夹开始列），改完直接保存，不用重新添加。
  /help 是使用帮助（发文件、/storage、/timezone 的用法），/start 里也有入口。
  提示文案只留必要的，不拿用户自己的配置做例子（比如不拿真实文件夹名举例）。
  群组：把 bot 拉进群，引用一条带文件的消息并艾特 bot 就下载它；群里只理艾特 bot 的
  消息（不然每条群消息都回太吵），白名单外的在群里直接忽略、不回；任务 id 用全局自增
  计数（不拿消息 id，免得不同聊天的消息 id 撞号）。加存储、改时区只在私聊里做。
  频道（/channels）：频道白名单存在 channels.json（chmod 600），按频道 ID（-100 开头）
  认——频道消息没有发送者，没法按用户认。bot 得被加进频道当管理员才会收到帖子；
  白名单里的频道一发带文件的帖子，bot 就自动下载，进度发到加这个频道的人的私聊里，
  不在频道里刷屏（多网盘没设默认时选存储的按钮也在私聊里点）。加频道可以转发一条
  那个频道的消息、也可以发 @用户名 或 ID。命令菜单在启动时同步（SetBotCommands）。
  代码里：取文件名+大小收进 _file_name_and_size（私聊/群组/频道三处共用），
  回调按钮的白名单检查收进 _cb_uid（重试按钮的拒绝日志还在）。
- 同时在 SERVER_PORT 上起一个极简 HTTP 服务做保活

环境变量（在 .env 里填，千万别写进公开仓库）：
  API_ID, API_HASH, BOT_TOKEN
  ALLOWED_USER_IDS         # 必填，逗号分隔的 Telegram user id；为空就是谁都不能用
  PARALLEL_CONNECTIONS     # 并行下载连接数，默认 6
  MAX_CONCURRENT_FILES     # 同时处理的文件数上限，默认 5；10 个以下是比较稳妥的数量，
                           # 设 0 为不限制。每个文件下载本身最多用 6 条连接，文件数太多会抢带宽、拖慢单个速度。
  TIMEZONE                 # 没设过时区的用户的默认时区，默认 Asia/Shanghai
  DOWNLOAD_DIR             # 默认 ./downloads
每个用户的时区用 /timezone 命令设（Telegram 不提供用户时区，只能自己设），
存在 timezones.json 里：点 /timezone 后直接发 UTC 序号就行（比如 -8、+8，范围 -12 到 +12），
也可以直接发 /timezone -8；想自动跟夏令时再发 IANA 名。
rclone 配置在 /root/.config/rclone/rclone.conf（[od]，OneDrive），
token 由 rclone 自己刷新，不走代码里的 Graph 授权。
新加的 remote 也写进同一个文件；bot 的存储注册表在 storages.json。
"""
import configparser
import glob
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# 上传时间按这个时区显示（默认 Asia/Shanghai，跟你的设备/聊天时间一致）；
# 想改成美国当地时间就改 .env 里的 TIMEZONE，比如 America/Los_Angeles。
# 注意：TIMEZONE 只是没设过时区的用户的默认值；每个用户可以用 /timezone 命令
# 设自己的时区（见下面的 timezones.json），互不干扰。
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Shanghai")
try:
    _DEFAULT_TZ = ZoneInfo(TIMEZONE)
except Exception:
    _DEFAULT_TZ = timezone.utc  # TIMEZONE 写错了就回落到 UTC，不报错

# 每个用户的时区：{user_id: "America/Los_Angeles"}，存在 timezones.json 里，
# Telegram 不提供用户的时区，只能让用户自己用 /timezone 命令设。
_TZ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timezones.json")
_user_timezones = {}


def _load_user_timezones():
    global _user_timezones
    try:
        with open(_TZ_FILE, encoding="utf-8") as f:
            _user_timezones = json.load(f) or {}
    except Exception:
        _user_timezones = {}


def _save_user_timezones():
    try:
        with open(_TZ_FILE, "w", encoding="utf-8") as f:
            json.dump(_user_timezones, f, ensure_ascii=False, indent=2)
        os.chmod(_TZ_FILE, 0o600)
    except Exception as e:
        log(f"保存用户时区失败：{e}")


def _parse_tz_name(name):
    """解析用户输入的时区，返回 (tz, 显示名)，解析不了返回 None。
    优先接受 UTC 序号：8、+8、-8、UTC+8、UTC-8、UTC（范围 -12 到 +12），
    这是固定偏移，不自动跟夏令时；IANA 名（如 America/Los_Angeles）也还接受，
    写 IANA 名的会按当地规则自动处理夏令时。"""
    if not name:
        return None
    s = name.strip()
    m = re.fullmatch(r"(?:UTC)?([+-]?\d{1,2})", s, re.IGNORECASE)
    if m:
        try:
            hours = int(m.group(1))
        except Exception:
            return None
        if -12 <= hours <= 12:
            if hours == 0:
                return timezone.utc, "UTC"
            sign = "+" if hours > 0 else "-"
            return timezone(timedelta(hours=hours)), f"UTC{sign}{abs(hours)}"
        return None
    try:
        return ZoneInfo(s), s
    except Exception:
        return None


def get_user_tz(uid):
    """取某个用户的时区：设过就用他的，没设过就用 TIMEZONE 默认值。"""
    name = _user_timezones.get(str(uid))
    if name:
        parsed = _parse_tz_name(name)
        if parsed:
            return parsed
    return _DEFAULT_TZ, TIMEZONE


# 没文件名时生成的名字用过哪些：每个生成的名字都在 Unix 时间戳后面直接加
# 两位序号，从 01 开始（01 到 99，超过继续往上加），同一秒多个同类型文件
# 依次往后排，保证 OD 里不互相覆盖。
_USED_GENERATED_NAMES = set()


def _generated_name(event, tz):
    """TG 没给文件名时按规则生成：类型_年_月_日_当前 Unix 时间戳+两位序号，
    比如 video_2026_11_25_176402553301（扩展名在外面再按 MIME 补）。
    日期取消息时间（换算到用户时区），时间戳取生成那一刻，序号从 01 开始，
    同一秒多个同类型文件依次是 01、02、03……"""
    mime = (event.file.mime_type or "") if event.file else ""
    kind = mime.split("/")[0] if "/" in mime else "file"
    kind = re.sub(r"[^A-Za-z0-9]+", "", kind) or "file"
    msg_date = getattr(event, "date", None)
    if msg_date is not None:
        try:
            d = msg_date.astimezone(tz)
        except Exception:
            d = msg_date
        date_part = d.strftime("%Y_%m_%d")
    else:
        date_part = datetime.now(tz).strftime("%Y_%m_%d")
    base = f"{kind}_{date_part}_{int(time.time())}"
    n = 1
    while True:
        # 序号直接跟在 Unix 时间戳后面，不加下划线，从 01 开始。
        name = f"{base}{n:02d}"
        if name not in _USED_GENERATED_NAMES:
            break
        n += 1
    _USED_GENERATED_NAMES.add(name)
    return name


def _file_name_and_size(msg, tz):
    """从一条带文件的消息里拿上传用的文件名和大小：有原名就用原名，
    没有就按规则生成；没扩展名时按 media 的 MIME 类型补一个。
    msg 是 Telethon 的 Message（私聊里传 event.message）。"""
    if msg.file.name:
        name = msg.file.name
    else:
        name = _generated_name(msg, tz)
    name = name.replace("/", "_")
    media = getattr(msg, "media", None)
    if "." not in name and media:
        try:
            ext = tg_utils.get_extension(media) or ""
            if ext and not ext.startswith("."):
                ext = "." + ext
            name += ext
        except Exception:
            pass
    return name, (msg.file.size or 0)


def _fmt_time(s, tz=None):
    """把 rclone 的 UTC 时间（如 2026-11-24T18:52:12Z）换算成指定时区的本地时间显示。"""
    if not s:
        return s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz or _DEFAULT_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s
import time
import json
import math
import asyncio
import itertools
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from telethon import TelegramClient, events, Button
from telethon import utils as tg_utils
from telethon.tl import functions as tg_functions
from telethon.tl import types as tg_types

API_ID = int(os.environ.get("API_ID", "0") or 0)
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "./downloads")
# 并行下载连接数：Telethon 默认是单连接顺序下载，512KB 一块等回包，
# 大文件会被 Telegram 单连接限速拖到 ~0.7MB/s。改成多连接并行分片下载。
PARALLEL_CONNECTIONS = int(os.environ.get("PARALLEL_CONNECTIONS", "6") or 6)
# 同时处理的文件数上限：默认 5；10 个以下是比较稳妥的数量，
# 再多会抢带宽还容易撞 Telegram 限速。0 = 不限制。
MAX_CONCURRENT_FILES = int(os.environ.get("MAX_CONCURRENT_FILES", "5") or 0)
PARALLEL_CHUNK = 512 * 1024  # 必须与 request_size 一致，且是 4096 的倍数
SERVER_PORT = int(os.environ.get("SERVER_PORT", os.environ.get("PORT", "25850")) or 25850)
# 白名单模式：只有白名单用户能用 bot。ALLOWED_USER_IDS 必填，
# 为空就是谁都不能用，不在代码里写任何默认 ID。
ALLOWED = {
    int(x.strip())
    for x in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
# 失败任务：job_id -> {chat_id, user_id, name, size, media, msg_id}，供“重试”按钮用
FAILED_JOBS = {}

# 任务 id：全局自增，私聊和群组的文件都用它，避免不同聊天的消息 id 撞号
#（消息 id 是按聊天分的，群和私聊里可能有相同的 id）。
_JOB_SEQ = itertools.count(1)


def _next_job_id():
    return next(_JOB_SEQ)


# ---------- 多网盘存储：rclone remote 注册表 ----------
# 凭据存在 rclone 自己的配置文件里（/root/.config/rclone/rclone.conf），
# 跟现在 [od] 的放法一样；bot 只在 storages.json 里记“哪个 remote、
# 存哪个文件夹、哪个是默认”，storages.json 同样 chmod 600。
_STORAGES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storages.json")
_storages = {"default": None, "storages": {}}
# 下载完还没选存哪个网盘的任务：job_id -> {event, msg, name, size, media, local, user_id, tz, tz_name}
PENDING_DST = {}


def _rclone_config_path():
    return os.environ.get("RCLONE_CONFIG") or os.path.expanduser("~/.config/rclone/rclone.conf")


def _rclone_conf_sections():
    """读 rclone 配置文件，只返回 {remote: {key: value}}；值里可能有密钥，绝不能记日志。"""
    sections, cur = {}, None
    try:
        with open(_rclone_config_path(), encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    cur = line[1:-1].strip()
                    sections[cur] = {}
                elif "=" in line and cur:
                    k, v = line.split("=", 1)
                    sections[cur][k.strip()] = v.strip()
    except Exception:
        pass
    return sections


def _rclone_remote_type(remote):
    return _rclone_conf_sections().get(remote, {}).get("type", "")


def _list_rclone_remotes():
    try:
        r = subprocess.run(["rclone", "listremotes"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        return [ln.strip().rstrip(":") for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def _load_storages():
    """读 storages.json；第一次运行（还没有这个文件）就建个空的——
    全新部署是个干干净净的 bot，没有预置的存储，文件夹在 /storage 添加存储时用选文件夹器定，
    不用提前在 .env 里把路径想好。"""
    global _storages
    try:
        with open(_STORAGES_FILE, encoding="utf-8") as f:
            data = json.load(f) or {}
        if isinstance(data.get("storages"), dict):
            _storages = {"default": data.get("default"), "storages": data["storages"]}
            return
    except Exception:
        pass
    _storages = {"default": None, "storages": {}}
    _save_storages()


def _save_storages():
    try:
        with open(_STORAGES_FILE, "w", encoding="utf-8") as f:
            json.dump(_storages, f, ensure_ascii=False, indent=2)
        os.chmod(_STORAGES_FILE, 0o600)
    except Exception as e:
        log(f"保存存储设置失败：{e}")


# ---------- 频道白名单：channels.json ----------
# bot 被加进频道当管理员后才会收到频道的帖子；频道消息没有发送者，
# 所以白名单按频道 ID（-100 开头那个）认，不按用户认。
_CHANNELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "channels.json")
_channels = {"channels": {}}


def _load_channels():
    """读 channels.json；没有就建个空的。"""
    global _channels
    try:
        with open(_CHANNELS_FILE, encoding="utf-8") as f:
            data = json.load(f) or {}
        if isinstance(data.get("channels"), dict):
            _channels = {"channels": data["channels"]}
            return
    except Exception:
        pass
    _channels = {"channels": {}}
    _save_channels()


def _save_channels():
    try:
        with open(_CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(_channels, f, ensure_ascii=False, indent=2)
        os.chmod(_CHANNELS_FILE, 0o600)
    except Exception as e:
        log(f"保存频道白名单失败：{e}")


def _channel_list():
    out = []
    for k in sorted(_channels["channels"]):
        c = dict(_channels["channels"][k])
        c["id"] = k
        out.append(c)
    return out


def _storage_list():
    return [_storages["storages"][k] for k in sorted(_storages["storages"])]


def _storage_display(s):
    """菜单里显示的名字：优先显示用户起的名字（remote 名），没有再显示网盘名；
    名字后面括号里跟网盘名，方便区分。"""
    remote = (s.get("remote") or "").strip()
    label = (s.get("label") or "").strip()
    if remote:
        if label and label != remote:
            return f"{remote}（{label}）"
        return remote
    return label


def _resolve_storage():
    """收到文件该往哪存：返回 (storage, 需要询问)。
    有默认就用默认；没默认但只有一个就用那个；没默认且有多个就要问；一个都没有返回 (None, False)。"""
    items = _storage_list()
    default = _storages.get("default")
    if default and default in _storages["storages"]:
        return _storages["storages"][default], False
    if len(items) == 1:
        return items[0], False
    if len(items) > 1:
        return None, True
    return None, False


def _storage_menu_text():
    lines = ["📦 存储管理", ""]
    items = _storage_list()
    if not items:
        lines.append("还没添加网盘，点下面按钮添加一个。")
    else:
        default = _storages.get("default")
        for s in items:
            mark = " ⭐ 默认" if s["remote"] == default else ""
            folder = f"/{s['folder']}" if s.get("folder") else "/（根目录）"
            lines.append(f"• {_storage_display(s)} → {folder}{mark}")
        lines.append("")
        if not default and len(items) > 1:
            lines.append("没选默认存储，收到文件时会问你存到哪个。")
        elif not default:
            lines.append("没选默认存储，只有一个网盘，直接存它。")
    return "\n".join(lines)


def _run_rclone_config_create(name, type_, params):
    """调 rclone config create 写一个 remote。params 里可能有密钥：命令和输出一律不记日志。
    只给非 OAuth 后端用；OAuth 后端走 _write_rclone_remote_direct，
    因为 config create 会重新跑一遍 OAuth、在那等 code 卡住（实测 onedrive 即使给了
    token 和 drive_id 也一样，120 秒超时）。"""
    cmd = ["rclone", "config", "create", name, type_]
    for k, v in params.items():
        if v is None or v == "":
            continue
        cmd += [k, str(v)]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        # 注意：TimeoutExpired 的 str 里会带上完整命令（含 token），绝不能原样记日志。
        raise RuntimeError("rclone 写入配置超时（60 秒），这个后端可能在等交互输入")
    if r.returncode != 0:
        raise RuntimeError("rclone 写入配置失败，请检查填的内容")
    try:
        os.chmod(_rclone_config_path(), 0o600)
    except Exception:
        pass


def _redact(s):
    """把日志/报错里的 token 之类长串抹掉，避免密钥进日志。"""
    if not s:
        return ""
    return re.sub(r"[A-Za-z0-9_\-!*/+=.]{80,}", "[REDACTED]", str(s))


def _write_rclone_remote_direct(name, type_, params, path=None):
    """直接把 remote 写进一个 rclone 配置文件（默认真实的 rclone.conf，不用 rclone config create）。
    原因见 _run_rclone_config_create：OAuth 后端用 config create 会重新跑 OAuth 卡住。
    用 configparser 读改写，原子替换，权限保持 600。"""
    path = path or _rclone_config_path()
    cp = configparser.RawConfigParser()
    cp.optionxform = str  # 保持键名大小写
    if os.path.exists(path):
        cp.read(path, encoding="utf-8")
    if cp.has_section(name):
        cp.remove_section(name)
    cp.add_section(name)
    cp.set(name, "type", type_)
    for k, v in params.items():
        if v:
            cp.set(name, k, v)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        cp.write(f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _fetch_onedrive_drive(access_token):
    """用 access_token 问 Graph 拿默认 OneDrive 的 drive_id 和 drive_type。
    OneDrive 光有 token 不够，lsd 会报缺 drive_id/drive_type，所以建 remote 前要先拿。
    返回 (drive_id, drive_type)，拿不到就抛错。"""
    req = urllib.request.Request(
        "https://graph.microsoft.com/v1.0/me/drive",
        headers={"Authorization": "Bearer " + access_token},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            d = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"问 OneDrive 要 drive 信息失败（HTTP {e.code}），token 可能有问题")
    except Exception as e:
        raise RuntimeError(f"问 OneDrive 要 drive 信息失败：{e}")
    drive_id = d.get("id")
    drive_type = d.get("driveType") or "personal"
    if not drive_id:
        raise RuntimeError("问 OneDrive 要 drive 信息失败：没拿到 drive id")
    return drive_id, drive_type


def _list_remote_dirs(remote, path, config_args=None):
    """列出网盘上某个目录下的子目录（只要目录，按名字排好）。返回 [名字]，失败抛错。"""
    args = ["rclone", "lsjson"] + list(config_args or [])
    target = f"{remote}:{path}" if path else f"{remote}:"
    r = subprocess.run(args + [target], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"列目录失败：{(r.stderr or '').strip()[-200:]}")
    try:
        items = json.loads(r.stdout or "[]")
    except Exception:
        items = []
    names = sorted(
        [d.get("Name", "") for d in items if isinstance(d, dict) and d.get("IsDir") and d.get("Name")],
        key=str.lower,
    )
    return names


def _rclone_mkdir(remote, path, config_args=None):
    """在网盘上建一个文件夹（连父目录一起建）。失败抛错。"""
    args = ["rclone", "mkdir"] + list(config_args or [])
    target = f"{remote}:{path}"
    r = subprocess.run(args + [target], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"建文件夹失败：{(r.stderr or '').strip()[-200:]}")


def _verify_remote(remote):
    """新建的 remote 能不能列目录，能才算配好了。"""
    r = subprocess.run(["rclone", "lsd", f"{remote}:"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def _delete_rclone_remote(remote):
    try:
        subprocess.run(["rclone", "config", "delete", remote], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    except Exception:
        pass


# rclone 后端注册表：从 providers.json 加载（由 `rclone config providers` 生成，
# 跟着装的 rclone 版本走；升级 rclone 后重新跑一遍生成）。
# 没有 providers.json 就只用内置的几种常见网盘兜底。
_PROVIDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.json")
_PROVIDERS = []          # [{"name", "prefix", "desc", "options"}]
_PROVIDER_MAP = {}       # prefix -> provider
_PROVIDER_PAGES = []     # 分页后的 provider 列表，每页 10 个

_DISPLAY_OVERRIDES = {
    "onedrive": "Microsoft OneDrive",
    "drive": "Google Drive",
    "dropbox": "Dropbox",
    "s3": "Amazon S3",
    "gphotos": "Google Photos",
    "gcs": "Google Cloud Storage",
    "box": "Box",
    "pcloud": "pCloud",
    "webdav": "WebDAV",
    "ftp": "FTP",
    "sftp": "SFTP",
    "smb": "SMB",
    "mega": "MEGA",
    "b2": "Backblaze B2",
    "yandex": "Yandex Disk",
    "mailru": "Mail.ru Cloud",
    "jottacloud": "Jottacloud",
    "hidrive": "HiDrive",
    "koofr": "Koofr",
    "pikpak": "PikPak",
    "protondrive": "Proton Drive",
    "oos": "Oracle Object Storage",
    "internetarchive": "Internet Archive",
    "imagekit": "ImageKit",
    "filefabric": "File Fabric",
    "opendrive": "OpenDrive",
    "huaweidrive": "Huawei Drive",
    "kdrive": "kDrive",
    "sugarsync": "SugarSync",
    "seafile": "Seafile",
}


def _load_providers():
    global _PROVIDERS, _PROVIDER_MAP, _PROVIDER_PAGES
    try:
        with open(_PROVIDERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        _PROVIDERS = []
        for p in raw:
            _PROVIDERS.append({
                "name": p.get("Name", ""),
                "prefix": p.get("Prefix", "") or p.get("Name", ""),
                "desc": p.get("Description", ""),
                "options": p.get("Options") or [],
            })
        _PROVIDER_MAP = {x["prefix"]: x for x in _PROVIDERS}
        log(f"已加载 {len(_PROVIDERS)} 个 rclone 后端")
    except Exception as e:
        log(f"加载 providers.json 失败（{e}），只用内置的几种常见网盘")
        _PROVIDERS = []
        _PROVIDER_MAP = {}
    if not _PROVIDERS:
        for prefix, label in (("onedrive", "OneDrive"), ("drive", "Google Drive"), ("dropbox", "Dropbox"), ("s3", "S3 兼容"), ("webdav", "WebDAV")):
            _PROVIDERS.append({"name": prefix, "prefix": prefix, "desc": label, "options": []})
            _PROVIDER_MAP[prefix] = _PROVIDERS[-1]
    _PROVIDERS.sort(key=lambda x: x["prefix"].lower())
    _PROVIDER_PAGES = [_PROVIDERS[i:i + 10] for i in range(0, len(_PROVIDERS), 10)]


def _provider_label(prefix):
    if prefix in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[prefix]
    p = _PROVIDER_MAP.get(prefix)
    if p and p.get("name"):
        return p["name"].replace("_", " ").title()
    return prefix


def _is_oauth(prefix):
    """这个后端走 OAuth 吗？——看它有没有 token 这一项（有就是 OAuth 的）。"""
    p = _PROVIDER_MAP.get(prefix)
    if not p:
        return False
    return any((o.get("Name") == "token") for o in p.get("options", []))


# 手写引导字段（常见非 OAuth 后端）：(rclone 参数名, 提示语, 是不是密钥, 是不是可跳过)
_MANUAL_FIELDS = {
    "s3": [
        ("provider", "服务商是哪个？比如 AWS、Minio、Cloudflare R2；不知道就发“跳过”", False, True),
        ("endpoint", "S3 的 endpoint 地址，比如 https://xxx.r2.cloudflarestorage.com；用 AWS 就发“跳过”", False, True),
        ("region", "区域，比如 us-east-1；不知道就发“跳过”", False, True),
        ("access_key_id", "发一下 Access Key ID", True, False),
        ("secret_access_key", "发一下 Secret Access Key", True, False),
    ],
    "webdav": [
        ("url", "发一下 WebDAV 地址，比如 https://example.com/dav", False, False),
        ("user", "发一下用户名", False, False),
        ("pass", "发一下密码", True, False),
    ],
    "ftp": [
        ("host", "发一下 FTP 服务器地址，比如 ftp.example.com", False, False),
        ("user", "发一下用户名（匿名就发“跳过”）", False, True),
        ("pass", "发一下密码（匿名就发“跳过”）", True, True),
    ],
    "sftp": [
        ("host", "发一下 SFTP 服务器地址，比如 sftp.example.com", False, False),
        ("user", "发一下用户名", False, False),
        ("pass", "发一下密码（用密钥文件登录就发“跳过”）", True, True),
    ],
    "smb": [
        ("host", "发一下 SMB 服务器地址，比如 192.168.1.10", False, False),
        ("user", "发一下用户名", False, False),
        ("pass", "发一下密码", True, False),
    ],
    "mega": [
        ("user", "发一下 MEGA 账号（邮箱）", False, False),
        ("pass", "发一下 MEGA 密码", True, False),
    ],
    "b2": [
        ("account", "发一下 B2 的 Key ID", True, False),
        ("key", "发一下 B2 的 Application Key", True, False),
    ],
    "seafile": [
        ("url", "发一下 Seafile 服务器地址，比如 https://seafile.example.com", False, False),
        ("user", "发一下账号（邮箱）", False, False),
        ("pass", "发一下密码", True, False),
    ],
    "protondrive": [
        ("username", "发一下 Proton 账号（邮箱）", False, False),
        ("password", "发一下 Proton 密码", True, False),
    ],
    "alias": [
        ("remote", "指向哪个已有的 remote？比如 mydrive:folder", False, False),
    ],
    "crypt": [
        ("remote", "加密后指向哪个 remote？比如 mydrive:crypt", False, False),
        ("password", "发一下加密密码（丢了就解不开，自己记好）", True, False),
    ],
}


def _manual_fields(prefix):
    """这个后端要填的字段：先用手写的，没有就按 providers.json 里 Required 的来。"""
    if prefix in _MANUAL_FIELDS:
        return _MANUAL_FIELDS[prefix]
    p = _PROVIDER_MAP.get(prefix)
    if not p:
        return []
    fields = []
    seen = set()
    for o in p.get("options", []):
        name = o.get("Name", "")
        if not name or name in seen:
            continue
        if name in ("token", "client_id", "client_secret"):
            continue
        if not o.get("Required") or o.get("Advanced"):
            continue
        seen.add(name)
        help_text = (o.get("Help") or "").split("\n")[0].strip()
        if len(help_text) > 80:
            help_text = help_text[:80] + "…"
        prompt = f"发一下 {name}" + (f"（{help_text}）" if help_text else "")
        secret = bool(o.get("IsPassword") or o.get("Sensitive"))
        fields.append((name, prompt, secret, False))
    return fields


def _extra_hint(prefix):
    """补充参数步骤里给的提示：这个后端还能填哪些参数。"""
    p = _PROVIDER_MAP.get(prefix)
    if not p:
        return ""
    names = []
    for o in p.get("options", []):
        name = o.get("Name", "")
        if not name or name in ("token", "client_id", "client_secret"):
            continue
        if o.get("Advanced"):
            continue
        if name not in names:
            names.append(name)
    return "、".join(names[:12])


def _build_create_params(type_, data, token=None):
    """rclone config create 用的参数。OAuth 的只传 authorize 拿到的 token；
    手动的传填好的键值对，空的去掉。"""
    if token:
        return {"token": token}
    return {k: v for k, v in (data or {}).items() if v}


_OAUTH_TIMEOUT = 600            # 从开始授权算起，10 分钟内没完成就作废
_OAUTH_EXCHANGE_TIMEOUT = 120   # 拿到 code 后等 token 的最长时间（秒）

_HELP_TEXT = (
    "使用帮助\n"
    "\n"
    "📤 发文件：把文件发给我或转发给我，我会下载并上传到网盘，支持大文件（>20MB）。\n"
    "📦 /storage：添加网盘、选默认存储、改保存位置、删网盘。\n"
    "  添加：OAuth 的网盘点登录链接登录，登录后把跳回来的 localhost 链接发我；其它的按提示填配置。\n"
    "  默认存储：设了就直接往它发；没设又有多个网盘时，收到文件会问你存哪个。\n"
    "📺 /channels：频道管理。把 bot 加进频道当管理员，再把频道加进白名单，频道新帖里的文件会自动下载。\n"
    "🕐 /timezone：设置上传时间的显示时区，发 UTC 序号（比如 -8、+8）或时区名（比如 Europe/London）。\n"
    "👥 群组：把 bot 拉进群，引用一条带文件的消息并艾特 bot，我就下载它。\n"
    "上传失败会有重试按钮；添加存储中途不想加了，发“取消”。"
)


def _parse_oauth_redirect(text):
    """从用户发来的 localhost 链接里解析 code 和 state。返回 (code, state)，没有就是 (None, None)。"""
    text = (text or "").strip()
    if "localhost" not in text and "127.0.0.1" not in text:
        return None, None
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
    code = (qs.get("code") or [None])[0]
    state = (qs.get("state") or [None])[0]
    return code, state


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def _progress_text(label, done, total, t0):
    pct = done * 100 // total if total else 0
    mb_done = done / 1024 / 1024
    mb_total = total / 1024 / 1024
    dt = max(time.time() - t0, 0.1)
    speed = mb_done / dt
    eta = (mb_total - mb_done) / speed if speed > 0 else 0
    bar_len = 12
    filled = pct * bar_len // 100
    bar = "█" * filled + "░" * (bar_len - filled)
    return (
        f"{label}\n{bar} {pct}%\n"
        f"{mb_done:.1f} / {mb_total:.1f} MB\n"
        f"速度 {speed:.1f} MB/s，预计还剩 {eta:.0f}s"
    )


async def _watch_progress(msg, label, get_done, total, t0, stop):
    """后台每 2 秒用 tg 消息实时更新一次进度（节流，避免刷屏被限流）。"""
    last_pct = -1
    while not stop["done"]:
        await asyncio.sleep(2)
        done = get_done()
        pct = done * 100 // total if total else 0
        if pct == last_pct and done < total:
            continue
        last_pct = pct
        try:
            await msg.edit(_progress_text(label, done, total, t0))
        except Exception:
            pass
        if done >= total:
            break


# ---------- 单实例保护：绝不能两个 bot 进程同时跑 ----------
# 两个实例共用同一个 bot_session.session 会互相锁 SQLite，
# 一个崩（database is locked），另一个拿不到 sender 实体还可能乱回白名单提示。
# 启动时先看 bot.pid：里面 pid 还活着就直接退出；pid 已死就是残留文件，直接覆盖。
_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pid")


def _single_instance_guard():
    if os.path.exists(_PID_FILE):
        try:
            old = int(open(_PID_FILE, encoding="utf-8").read().strip())
        except Exception:
            old = 0
        if old:
            try:
                os.kill(old, 0)
                print(f"已有 bot 实例在运行（PID {old}），本次不启动，避免双开抢 session。")
                raise SystemExit(2)
            except ProcessLookupError:
                pass  # 旧进程已死，pidfile 是残留的，可以覆盖
            except PermissionError:
                print(f"bot.pid 里的 PID {old} 无法确认，本次不启动。")
                raise SystemExit(2)
    try:
        with open(_PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"写 bot.pid 失败：{e}")
        raise SystemExit(2)


def _clear_pid_file():
    try:
        if os.path.exists(_PID_FILE) and open(_PID_FILE, encoding="utf-8").read().strip() == str(os.getpid()):
            os.remove(_PID_FILE)
    except Exception:
        pass
import re
import subprocess


def _parse_rclone_bytes(s):
    m = re.search(r"Transferred:\s*([\d.]+)\s*([KMGT]?i?B)\s*/\s*([\d.]+)", s)
    if not m:
        return None
    units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3,
             "KB": 1000, "MB": 1000**2, "GB": 1000**3}
    done = float(m.group(1)) * units.get(m.group(2), 1)
    return int(done)


def upload_to_storage(local_path, remote_name, storage, on_progress=None):
    """只用 rclone copyto 上传到指定存储（断点续传、自动重试、分块上传）。
    rclone 失败就直接抛错，由调用方给用户弹重试按钮，不再回落 Graph。
    返回远端路径（不带 remote 名，如 folder/xxx.mp4）。"""
    size = os.path.getsize(local_path)
    folder = (storage.get("folder") or "").strip("/")
    remote_path = f"{folder}/{remote_name}" if folder else remote_name
    dest = f"{storage['remote']}:{remote_path}"
    cmd = [
        "rclone", "copyto", local_path, dest,
        "--retries", "3",
        "--low-level-retries", "10",
        "--stats", "2s",
        "--use-json-log",
        "--log-level", "INFO",
    ]
    if (storage.get("kind") or "") == "onedrive":
        cmd += ["--onedrive-chunk-size", "10M"]
    log(f"rclone 上传：{local_path} -> {dest}")
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    last_err = ""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        last_err = line
        done = None
        try:
            j = json.loads(line)
            stats = j.get("stats") or {}
            if "bytes" in stats:
                done = int(stats["bytes"])
            elif j.get("msg"):
                done = _parse_rclone_bytes(j["msg"])
        except Exception:
            done = _parse_rclone_bytes(line)
        if done is not None and on_progress:
            on_progress(min(done, size), size)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"rclone 上传失败，退出码 {rc}：{last_err[-300:]}")
    if on_progress:
        on_progress(size, size)
    log(f"rclone 上传完成：{dest}")
    return remote_path


def get_remote_file_info(remote, remote_path):
    """上传成功后用 rclone lsjson 查落盘文件信息：名字、大小、修改时间。"""
    target = f"{remote}:{remote_path.lstrip('/')}"
    r = subprocess.run(
        ["rclone", "lsjson", target],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"rclone lsjson 失败：{r.stderr.strip()[-200:]}")
    d = json.loads(r.stdout)
    if isinstance(d, list):
        d = d[0] if d else {}
    return {
        "name": d.get("Name", ""),
        "size": d.get("Size", 0),
        "webUrl": "",
        "created": "",
        "modified": d.get("ModTime", ""),
        "path": "/" + remote_path.lstrip("/"),
    }


def format_file_info(info, tz=None, tz_name="", dest_label=""):
    size_mb = info["size"] / 1024 / 1024
    lines = [
        f"✅ 已上传到 {dest_label or '网盘'}",
        f"文件名：{info['name']}",
        f"大小：{size_mb:.1f} MB（{info['size']} 字节）",
        f"位置：{info['path']}",
    ]
    if info.get("modified"):
        # rclone 给的 ModTime 是 UTC（…Z），直接显示会跟用户的时间对不上，
        # 按这个用户自己的时区换算后再显示，括号里标明是哪个时区。
        text = f"上传时间：{_fmt_time(info['modified'], tz)}"
        if tz_name:
            text += f"（{tz_name}）"
        lines.append(text)
    if info.get("webUrl"):
        lines.append(f"打开：{info['webUrl']}")
    return "\n".join(lines)


# ---------- 占位 HTTP 服务（部分托管平台要求应用监听端口） ----------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok - telegram bot running\n")

    def log_message(self, *a):
        pass


def serve_http():
    try:
        HTTPServer(("0.0.0.0", SERVER_PORT), Handler).serve_forever()
    except Exception as e:
        log(f"HTTP 服务启动失败（不影响 bot）: {e}")


# ---------- Telegram Bot ----------
async def download_parallel(client, media, local, size, progress=None):
    """多连接并行下载：把文件按 512KB 切片，N 个连接各下自己的分片，
    写到文件的对应偏移处。小文件直接单连接下，不折腾。
    progress 是可选的 {"done": 0} 字典，供实时进度上报用。"""
    if size <= 10 * 1024 * 1024 or PARALLEL_CONNECTIONS <= 1:
        # 注意：download_media 会在没有扩展名的路径后自动补扩展名
        # （比如 ./downloads/6_file_6 -> ./downloads/6_file_6.mp4），
        # 必须用它返回的实际路径，否则后面按原路径找文件会报 No such file。
        result = await client.download_media(media, file=local)
        if isinstance(result, str) and result:
            return result
        return local
    n = PARALLEL_CONNECTIONS
    stride = n * PARALLEL_CHUNK
    # 预分配文件，避免多连接写时互相覆盖
    with open(local, "wb") as f:
        f.truncate(size)
    downloaded = {"bytes": 0}
    lock = asyncio.Lock()

    async def worker(idx):
        offset = idx * PARALLEL_CHUNK
        if offset >= size:
            return
        limit = math.ceil((size - offset) / stride)
        fh = open(local, "r+b")
        try:
            # 关键：iter_download 带 stride 时，每次返回的块在文件里相隔 stride，
            # 不是连续的。必须按块序号算绝对偏移写，不能用 pos += len(chunk) 顺序写，
            # 否则第 2 块起全写错位置，文件后半段留空（预分配的 0），mp4 就坏了。
            k = 0
            async for chunk in client.iter_download(
                media,
                offset=offset,
                stride=stride,
                limit=limit,
                chunk_size=PARALLEL_CHUNK,
                request_size=PARALLEL_CHUNK,
                file_size=size,
            ):
                fh.seek(offset + k * stride)
                fh.write(chunk)
                k += 1
                async with lock:
                    downloaded["bytes"] += len(chunk)
                    if progress is not None:
                        progress["done"] = downloaded["bytes"]
        finally:
            fh.close()

    log(f"并行下载：{n} 连接，{size/1024/1024:.1f} MB")
    await asyncio.gather(*[worker(i) for i in range(n)])
    got = os.path.getsize(local)
    if got != size:
        raise RuntimeError(f"下载不完整：{got}/{size} 字节")
    if downloaded["bytes"] != size:
        raise RuntimeError(f"下载字节数不对：实际 {downloaded['bytes']}/{size} 字节，可能有分片没下到")
    log(f"并行下载完成：{got/1024/1024:.1f} MB")
    return local


async def main():
    _single_instance_guard()
    if not API_ID or not API_HASH or not BOT_TOKEN:
        log("❌ 缺少 API_ID / API_HASH / BOT_TOKEN，bot 无法启动")
        log("设置环境变量或上传 .env 后重启")
        # 别直接退出，让 HTTP 服务活着，方便在面板里看到状态
        while True:
            time.sleep(3600)
    if not ALLOWED:
        log("⚠️ ALLOWED_USER_IDS 为空：白名单模式下谁都不能用 bot，请在 .env 里填 ALLOWED_USER_IDS")
    _load_user_timezones()
    log(f"已加载 {len(_user_timezones)} 个用户的时区设置")
    _load_providers()
    _load_storages()
    log(f"已加载 {len(_storages['storages'])} 个存储，默认：{_storages.get('default') or '未设置'}")
    _load_channels()
    log(f"已加载 {len(_channels['channels'])} 个白名单频道")
    # 清掉上次没走完的选文件夹流程留下的临时配置（里面有 token）。
    for _f in glob.glob(os.path.join(tempfile.gettempdir(), "rclone-picker-*.conf")):
        try:
            os.remove(_f)
        except Exception:
            pass
    if not shutil.which("rclone"):
        log("⚠️ 没找到 rclone：上传会失败，请先装 rclone 并配好 [od] remote")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    threading.Thread(target=serve_http, daemon=True).start()
    log(f"HTTP 保活服务已起，端口 {SERVER_PORT}")

    client = TelegramClient("bot_session", API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    log(f"Bot 已上线：@{me.username} (id={me.id})，已配存储 {len(_storages['storages'])} 个，默认：{_storages.get('default') or '未设置'}")
    bot_username = (me.username or "").lower()
    # 启动时顺手把命令菜单同步成代码里的（/start /help /storage /channels /timezone）。
    try:
        await client(tg_functions.bots.SetBotCommandsRequest(
            scope=tg_types.BotCommandScopeDefault(),
            lang_code="",
            commands=[
                tg_types.BotCommand("start", "开始使用"),
                tg_types.BotCommand("help", "使用帮助"),
                tg_types.BotCommand("storage", "存储管理"),
                tg_types.BotCommand("channels", "频道管理"),
                tg_types.BotCommand("timezone", "查看或设置时区"),
            ],
        ))
        log("命令菜单已同步")
    except Exception as e:
        log(f"同步命令菜单失败（不影响 bot）：{e}")

    def _mentions_bot(event):
        """群里是不是艾特了 bot：文本里有 @用户名。"""
        if not bot_username:
            return False
        return f"@{bot_username}" in (event.text or "").lower()

    async def _handle_group_mention(event, uid):
        """群里艾特 bot：要么这条消息自己带文件，要么是引用了一条带文件的消息，下载它。"""
        tz, tz_name = get_user_tz(uid)
        target = None
        if event.file:
            target = event.message
        elif event.is_reply:
            replied = await event.get_reply_message()
            if replied is None:
                await event.reply("找不到被引用的那条消息了。")
                return
            if not replied.file:
                await event.reply("被引用的那条消息里没有文件。")
                return
            target = replied
        else:
            await event.reply("引用一条带文件的消息并艾特我，我就下载它。")
            return
        name, size = _file_name_and_size(target, tz)
        size_mb = size / 1024 / 1024
        _tz_pending.discard(uid)
        log(f"群里收到文件 {name} ({size_mb:.1f} MB) 来自 {uid}（群 {event.chat_id}）")
        msg = await event.reply(f"收到 {name}（{size_mb:.1f} MB），正在下载…")
        await process_file(event, msg, name, size, target.media, _next_job_id(), tz=tz, tz_name=tz_name)

    # ---------- 频道 ----------
    # 正在添加频道的用户：uid -> {"step": "add"}
    _channel_state = {}

    def _cancel_channel_flow(uid):
        _channel_state.pop(uid, None)

    def _channels_menu_text():
        items = _channel_list()
        if not items:
            return "频道白名单是空的。\n加了频道后，bot 会自动下载那个频道新帖里的文件。\n先把 bot 加进频道当管理员，不然它收不到频道的消息。"
        lines = ["频道白名单："]
        for c in items:
            disp = c.get("title") or c.get("username") or ""
            lines.append(f"• {disp}" + (f" (@{c['username']})" if c.get("username") else "") + f" — {c['id']}")
        lines.append("\n加了频道后，bot 会自动下载那个频道新帖里的文件。")
        return "\n".join(lines)

    def _channels_menu_buttons():
        return [
            [Button.inline("➕ 添加频道", data=b"chan:add")],
            [Button.inline("🗑 删除频道", data=b"chan:dellist")],
        ]

    def _forwarded_channel_id(event):
        """这条消息是不是从频道转发来的，是就返回频道 ID（-100 开头那个），不是返回 None。"""
        msg = event.message if event else None
        fwd = getattr(msg, "fwd_from", None) if msg else None
        if fwd is None:
            return None
        peer = getattr(fwd, "from_id", None)
        if peer is None:
            return None
        try:
            cid = tg_utils.get_peer_id(peer)
        except Exception:
            return None
        if isinstance(peer, tg_types.PeerChannel) and str(cid).startswith("-100"):
            return cid
        return None

    async def _resolve_channel(text, event):
        """把用户给的频道解析成 (chat_id, title, username)；失败返回 (None, 错误提示, None)。"""
        # 1. 转发的频道消息：直接拿频道 ID 和名字。
        cid = _forwarded_channel_id(event)
        if cid is not None:
            fwd = event.message.fwd_from
            title = getattr(fwd, "from_name", None) or ""
            return cid, title, ""
        # 2. 文字：@用户名 或 ID。
        t = (text or "").strip().lstrip("@")
        if not t:
            return None, "没看懂，发频道的 @用户名 或者 ID（比如 -1001234567890），或者转发一条那个频道的消息给我。", None
        try:
            ent = await client.get_entity(int(t) if re.fullmatch(r"-?\d+", t) else t)
        except Exception:
            return None, f"找不到这个频道：{t}。确认没写错，频道是公开的或者 bot 已经被加进去了。", None
        if not isinstance(ent, tg_types.Channel):
            return None, f"{t} 不是频道。", None
        cid = tg_utils.get_peer_id(ent)
        return cid, getattr(ent, "title", "") or "", getattr(ent, "username", "") or ""

    async def _handle_channel_input(event, uid):
        """添加频道流程里用户发来的东西：转发的频道消息、@用户名或 ID。"""
        text = (event.text or "").strip()
        if text in ("取消", "/cancel"):
            _cancel_channel_flow(uid)
            await event.reply("不加了。")
            return
        cid, title, username = await _resolve_channel(text, event)
        if cid is None:
            await event.reply(title)
            return
        key = str(cid)
        if key in _channels["channels"]:
            _cancel_channel_flow(uid)
            await event.reply(f"这个频道已经在白名单里了：{title or cid}。")
            return
        _channels["channels"][key] = {"title": title or "", "username": username or "", "added_by": uid}
        _save_channels()
        _cancel_channel_flow(uid)
        await event.reply(
            f"已加进频道白名单：{title or cid}" + (f" (@{username})" if username else "") + "\n"
            "记得把 bot 加进这个频道当管理员，不然它收不到频道的消息，下载不了。"
        )

    async def _handle_channel_post(event):
        """频道新帖：只处理白名单里的频道，带文件的就下载，进度发到加这个频道的人的私聊里，不在频道里刷屏。"""
        cid = event.chat_id
        ch = _channels["channels"].get(str(cid))
        if not ch:
            return
        if not event.file:
            return
        owner = ch.get("added_by") or next(iter(ALLOWED), None)
        if not owner:
            return
        tz, tz_name = get_user_tz(owner)
        name, size = _file_name_and_size(event.message, tz)
        size_mb = size / 1024 / 1024
        title = ch.get("title") or str(cid)
        log(f"频道 {title} 收到文件 {name} ({size_mb:.1f} MB)")
        try:
            msg = await client.send_message(owner, f"频道 {title} 收到 {name}（{size_mb:.1f} MB），正在下载…")
        except Exception as e:
            log(f"给频道主发进度消息失败：{e}")
            return
        await process_file(event, msg, name, size, event.message.media if event.message else None, _next_job_id(), tz=tz, tz_name=tz_name)

    # 同时处理的文件数上限（MAX_CONCURRENT_FILES，0 = 不限制）
    _file_sem = asyncio.Semaphore(MAX_CONCURRENT_FILES) if MAX_CONCURRENT_FILES > 0 else None
    if _file_sem is None:
        log("同时处理文件数：不限制（MAX_CONCURRENT_FILES=0）")
    else:
        log(f"同时处理文件数：最多 {MAX_CONCURRENT_FILES} 个")

    async def _finish_upload(event, msg, name, size, media, local, storage, job_id, tz=None, tz_name=""):
        """上传本地文件到指定存储，全程用 tg 消息实时更新进度。
        成功回落盘文件信息；失败把任务记下来，消息带重试按钮。
        上传成功/失败都清理本地临时文件。"""
        try:
            # ---- 上传（实时进度，上传跑在线程里，不堵消息更新） ----
            t0 = time.time()
            up = {"done": 0}
            stop = {"done": False}
            watcher = asyncio.create_task(
                _watch_progress(msg, f"⬆️ 上传到 {_storage_display(storage)}：{name}", lambda: up["done"], size, t0, stop)
            )
            try:
                loop = asyncio.get_running_loop()
                remote = await loop.run_in_executor(
                    None,
                    lambda: upload_to_storage(
                        local, name, storage,
                        on_progress=lambda d, t: up.update({"done": d}),
                    ),
                )
            finally:
                stop["done"] = True
                await watcher
            dt = time.time() - t0
            got = os.path.getsize(local)
            log(f"上传完成 {name}：{got/1024/1024:.1f} MB，用时 {dt:.0f}s")

            # ---- 成功：返回落盘文件信息 ----
            try:
                info = await loop.run_in_executor(None, lambda: get_remote_file_info(storage["remote"], remote))
                text = format_file_info(info, tz=tz, tz_name=tz_name, dest_label=_storage_display(storage))
            except Exception as e:
                log(f"查落盘文件信息失败：{e}")
                text = f"✅ 已上传到 {_storage_display(storage)}：/{remote}"
            await msg.edit(text)
            log(f"完成：{name} -> {storage['remote']}:{remote}")
            FAILED_JOBS.pop(job_id, None)
            return True
        except Exception as e:
            log(f"上传失败 {name}: {e}")
            FAILED_JOBS[job_id] = {
                "chat_id": event.chat_id if event else 0,
                "user_id": (event.sender_id or 0) if event else 0,
                "name": name,
                "size": size,
                "media": media,
            }
            try:
                await msg.edit(
                    f"❌ 失败：{name}\n{e}\n\n点下面按钮可以重试。",
                    buttons=[[Button.inline("🔁 重试", data=f"retry:{job_id}".encode())]],
                )
            except Exception:
                pass
            return False
        finally:
            # 上传成功/失败都清理本地临时文件；小文件下载时 Telethon 会补扩展名，
            # 所以连同 local.* 的同名文件一起删，避免残留孤儿文件。
            try:
                if os.path.exists(local):
                    os.remove(local)
                for orphan in glob.glob(local + ".*"):
                    os.remove(orphan)
            except Exception:
                pass

    async def _process_file_impl(event, msg, name, size, media, job_id, tz=None, tz_name=""):
        """下载 + 上传一个文件，全程用 tg 消息实时更新进度。
        成功返回 OneDrive 落盘文件信息；失败把任务记下来，消息带重试按钮。"""
        local = os.path.join(DOWNLOAD_DIR, f"{job_id}_{name}")
        try:
            # ---- 下载（实时进度） ----
            t0 = time.time()
            dl = {"done": 0}
            stop = {"done": False}
            watcher = asyncio.create_task(
                _watch_progress(msg, f"⬇️ 下载中：{name}", lambda: dl["done"], size, t0, stop)
            )
            try:
                if media and size > 10 * 1024 * 1024:
                    await download_parallel(client, media, local, size, progress=dl)
                else:
                    # 小文件单连接下载：用返回的实际路径（Telethon 会补扩展名）
                    local = await download_parallel(client, media, local, size, progress=dl)
                    dl["done"] = os.path.getsize(local) if os.path.exists(local) else 0
            finally:
                stop["done"] = True
                await watcher
            dt = time.time() - t0
            got = os.path.getsize(local)
            log(f"下载完成 {name}：{got/1024/1024:.1f} MB，用时 {dt:.0f}s，{got/1024/1024/dt:.1f} MB/s")
            if got != size:
                raise RuntimeError(f"下载不完整：{got}/{size} 字节")
            # 上传用的文件名以实际下载下来的文件名为准（Telethon 会补扩展名），
            # 不能用收到的原名，否则存到 OD 就丢扩展名。
            # 注意：本地临时文件叫 {job_id}_{name}（job_id 是消息 id，防重名），
            # 但这个前缀只属于本地，上传到 OD 的名字必须把它去掉，
            # 否则 OD 里就成了 27_IMG_3831.MP4 这种奇怪的名字。
            name = os.path.basename(local)
            prefix = f"{job_id}_"
            if name.startswith(prefix):
                name = name[len(prefix):]

        except Exception as e:
            log(f"下载失败 {name}: {e}")
            FAILED_JOBS[job_id] = {
                "chat_id": event.chat_id if event else 0,
                "user_id": (event.sender_id or 0) if event else 0,
                "name": name,
                "size": size,
                "media": media,
            }
            try:
                await msg.edit(
                    f"❌ 失败：{name}\n{e}\n\n点下面按钮可以重试。",
                    buttons=[[Button.inline("🔁 重试", data=f"retry:{job_id}".encode())]],
                )
            except Exception:
                pass
            try:
                if os.path.exists(local):
                    os.remove(local)
                for orphan in glob.glob(local + ".*"):
                    os.remove(orphan)
            except Exception:
                pass
            return False

        # ---- 下载完了，决定存到哪个网盘 ----
        storage, need_choice = _resolve_storage()
        if need_choice:
            # 先不上传，等用户选；本地文件留着，选完再传。等选择时不占并发名额，
            # 选完上传时再重新拿信号量（见 dst 回调）。
            PENDING_DST[job_id] = {
                "event": event, "msg": msg, "name": name, "size": size,
                "media": media, "local": local,
                "user_id": event.sender_id or 0, "tz": tz, "tz_name": tz_name,
            }
            buttons = [[Button.inline(f"📦 {_storage_display(s)}", data=f"dst:{job_id}:{s['remote']}".encode())] for s in _storage_list()]
            buttons.append([Button.inline("❌ 取消", data=f"dst:cancel:{job_id}".encode())])
            try:
                await msg.edit(f"下载完了：{name}（{size/1024/1024:.1f} MB）\n转存到哪个网盘？", buttons=buttons)
            except Exception:
                pass
            log(f"等用户选存储：{name} (job {job_id})")
            return "waiting"
        if storage is None:
            try:
                await msg.edit("❌ 还没配好存储，先用 /storage 添加一个网盘。")
            except Exception:
                pass
            try:
                if os.path.exists(local):
                    os.remove(local)
            except Exception:
                pass
            return False
        return await _finish_upload(event, msg, name, size, media, local, storage, job_id, tz=tz, tz_name=tz_name)

    async def process_file(event, msg, name, size, media, job_id, tz=None, tz_name=""):
        """包一层并发上限：超过 MAX_CONCURRENT_FILES 的任务在信号量上排队等。"""
        if _file_sem is None:
            return await _process_file_impl(event, msg, name, size, media, job_id, tz=tz, tz_name=tz_name)
        async with _file_sem:
            return await _process_file_impl(event, msg, name, size, media, job_id, tz=tz, tz_name=tz_name)

    # 正在添加存储的用户：uid -> {"step": "name"/"field"/"folder"/"confirm", "type": ..., "remote": ..., "idx": int, "data": {...}, "folder": ..., "import": bool}
    _storage_state = {}

    def _storage_menu_buttons():
        buttons = [
            [Button.inline("➕ 添加存储", data=b"stor:add")],
            [Button.inline("⭐ 选择默认存储", data=b"stor:default")],
            [Button.inline("📁 修改保存位置", data=b"stor:editfolder")],
            [Button.inline("🗑 删除存储", data=b"stor:dellist")],
        ]
        return buttons

    def _storage_add_text(page):
        total = len(_PROVIDERS)
        pages = len(_PROVIDER_PAGES)
        return f"加哪种网盘？一共 {total} 种（第 {page + 1}/{pages} 页），选一个。\nOAuth 的网盘会给你登录链接，登录后把 localhost 链接发我。"

    def _storage_add_buttons(page):
        buttons = []
        page_items = _PROVIDER_PAGES[page]
        for i in range(0, len(page_items), 2):
            row = [Button.inline(_provider_label(p["prefix"]), data=f"stor:type:{p['prefix']}".encode()) for p in page_items[i:i + 2]]
            buttons.append(row)
        nav = []
        if page > 0:
            nav.append(Button.inline("⬅️ 上一页", data=f"stor:page:{page - 1}".encode()))
        if page < len(_PROVIDER_PAGES) - 1:
            nav.append(Button.inline("下一页 ➡️", data=f"stor:page:{page + 1}".encode()))
        if nav:
            buttons.append(nav)
        buttons.append([Button.inline("📥 已在 rclone 配好（导入）", data=b"stor:type:import")])
        buttons.append([Button.inline("❌ 取消", data=b"stor:cancel")])
        return buttons

    def _picker_config_path(uid):
        return os.path.join(tempfile.gettempdir(), f"rclone-picker-{uid}.conf")

    def _picker_rclone_args(st, uid):
        """选文件夹时调 rclone 用的 --config 参数：导入的直接用真实配置；
        OAuth/手动的用临时配置（不污染真实配置，流程结束就删）。"""
        if st.get("import"):
            return []
        params = {}
        if _is_oauth(st["type"]):
            params = {"token": st.get("token") or ""}
            if st.get("drive_id"):
                params["drive_id"] = st["drive_id"]
            if st.get("drive_type"):
                params["drive_type"] = st["drive_type"]
        else:
            params = dict(st.get("data") or {})
        path = _picker_config_path(uid)
        _write_rclone_remote_direct(st["remote"], st["type"], params, path=path)
        return ["--config", path]

    def _cleanup_picker_config(uid):
        try:
            os.remove(_picker_config_path(uid))
        except Exception:
            pass

    def _confirm_storage_text(st):
        kind_label = _provider_label(st["type"])
        folder = st.get("folder", "")
        return (f"确认一下：\n类型：{kind_label}\n名字：{st['remote']}\n文件夹：/{folder or '（根目录）'}\n\n没问题就点确认添加。")

    def _confirm_storage_buttons():
        return [[Button.inline("✅ 确认添加", data=b"stor:confirm"), Button.inline("❌ 取消", data=b"stor:cancel")]]

    async def _finish_edit_folder(event, uid, folder, edit=False):
        """改位置收尾：把文件夹存进 storages.json，告诉用户改好了。"""
        st = _storage_state.get(uid)
        if not st:
            return
        remote = st["remote"]
        _storages["storages"][remote]["folder"] = folder
        _save_storages()
        _storage_state.pop(uid, None)
        _cleanup_picker_config(uid)
        disp = _storage_display(_storages["storages"][remote])
        folder_disp = "/" + folder if folder else "/（根目录）"
        text = f"✅ 已把 {disp} 的保存位置改成 {folder_disp}。"
        buttons = [[Button.inline("🔙 返回存储管理", data=b"stor:menu")]]
        if edit:
            await event.edit(text, buttons=buttons)
        else:
            await event.reply(text, buttons=buttons)

    async def _show_folder_picker(event, uid, edit=False):
        """显示文件夹选择器：列出当前目录的子目录，按钮进目录/选定/新建/手动输入。"""
        st = _storage_state.get(uid)
        if not st:
            return
        path = st.get("browse_path", "")
        try:
            loop = asyncio.get_running_loop()
            dirs = await loop.run_in_executor(
                None, lambda: _list_remote_dirs(st["remote"], path, _picker_rclone_args(st, uid)))
        except Exception as e:
            # 列不出目录就回落到手动输入。
            st["step"] = "folder"
            text = f"列不出网盘目录（{_redact(str(e))[:150]}），手动发文件夹名；想存根目录就发“根目录”。"
            if edit:
                await event.edit(text)
            else:
                await event.reply(text)
            return
        st["browse_dirs"] = dirs
        disp_path = "/" + path if path else "/（根目录）"
        if st.get("mode") == "edit":
            disp = _storage_display(_storages["storages"].get(st["remote"], st))
            text = f"把 {disp} 的保存位置改成哪个文件夹？当前：{disp_path}\n点一个目录进去，或者直接选“就存在这里”。"
        else:
            text = f"存在哪个文件夹？当前：{disp_path}\n点一个目录进去，或者直接选“就存在这里”。"
        buttons = []
        for i, name in enumerate(dirs[:25]):
            label = name if len(name) <= 30 else name[:29] + "…"
            buttons.append([Button.inline(f"📁 {label}", data=f"stor:cd:{i}".encode())])
        if len(dirs) > 25:
            buttons.append([Button.inline(f"…还有 {len(dirs) - 25} 个，手动输入进更深的目录", data=b"stor:manual")])
        row = [Button.inline("✅ 就存在这里", data=b"stor:sel")]
        if path:
            row.append(Button.inline("⬆️ 上一级", data=b"stor:up"))
        buttons.append(row)
        buttons.append([Button.inline("➕ 新建文件夹", data=b"stor:mkdir"), Button.inline("✏️ 手动输入", data=b"stor:manual")])
        buttons.append([Button.inline("❌ 取消", data=b"stor:cancel")])
        if edit:
            await event.edit(text, buttons=buttons)
        else:
            await event.reply(text, buttons=buttons)

    async def _enter_folder_step(event, uid, edit=False, start_path=None):
        """进入选文件夹这一步：列目录，给用户选。改位置时从现在的文件夹开始，添加时从根目录开始。"""
        st = _storage_state.get(uid)
        if not st:
            return
        st["step"] = "folder"
        st["browse_path"] = start_path or ""
        st["browse_dirs"] = []
        await _show_folder_picker(event, uid, edit=edit)

    def _cancel_storage_flow(uid):
        """作废一次添加流程：正在跑的 authorize 进程也杀掉，正在等的任务会被唤醒后悄悄退出。"""
        _cleanup_picker_config(uid)
        st = _storage_state.pop(uid, None)
        if not st:
            return
        proc = st.get("proc")
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        q = st.get("oauth_queue")
        if q is not None:
            q.put_nowait(None)
        st["cancelled"] = True

    async def _storage_ask_field(event, uid):
        """问添加流程的下一项（按类型要填的字段顺序）。"""
        st = _storage_state.get(uid)
        if not st:
            return
        fields = _manual_fields(st["type"])
        if st["idx"] < len(fields):
            key, prompt, secret, optional = fields[st["idx"]]
            await event.reply(prompt + ("（发完我会删掉这条消息）" if secret else ""))

    async def _run_oauth_flow(event, uid, st):
        """跑 rclone authorize：拿登录链接发给用户，等用户把 localhost 链接发回来，换 token。
        换到 token 后把步骤切到 folder 并问文件夹；中途取消/超时就悄悄收尾。"""
        prefix = st["type"]
        t0 = time.time()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "rclone", "authorize", "--auth-no-open-browser", prefix,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        except Exception as e:
            await event.reply(f"启动授权失败：{e}")
            _storage_state.pop(uid, None)
            return
        st["proc"] = proc
        st["oauth_queue"] = asyncio.Queue()
        try:
            # 1. 等 rclone 吐出本地授权链接（/auth?state=...）
            auth_url = None
            try:
                while time.time() - t0 < 60:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=60)
                    if not line:
                        break
                    m = re.search(r"http://127\.0\.0\.1:53682/auth\?state=\S+", line.decode(errors="replace"))
                    if m:
                        auth_url = m.group(0).rstrip("\"'<>")
                        break
            except asyncio.TimeoutError:
                pass
            if not auth_url:
                if st.get("cancelled"):
                    return
                await event.reply("没拿到登录链接，授权启动失败了，从 /storage 重新试一次吧。")
                _storage_state.pop(uid, None)
                return
            # 记下这次授权的 state：用户贴回来的链接 state 得跟它一样才是这次的，
            # 不一样就是贴了上一次（旧）的链接，直接告诉用户，不用等回放超时才发现。
            m_state = re.search(r"state=([A-Za-z0-9_-]+)", auth_url)
            if m_state:
                st["oauth_state"] = m_state.group(1)
            # 2. 跟着本地链接的 307 跳转，拿到真正的登录页地址（用 rclone 自带的应用）
            def _fetch_redirect(url):
                req = urllib.request.Request(url, method="GET")

                class NoRedir(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None

                opener = urllib.request.build_opener(NoRedir)
                try:
                    opener.open(req, timeout=15)
                    return None
                except urllib.error.HTTPError as e:
                    return e.headers.get("Location")
                except Exception:
                    return None

            loop = asyncio.get_running_loop()
            provider_url = await loop.run_in_executor(None, lambda: _fetch_redirect(auth_url))
            if not provider_url:
                if st.get("cancelled"):
                    return
                await event.reply("没拿到登录页地址，授权启动失败了，从 /storage 重新试一次吧。")
                _storage_state.pop(uid, None)
                return
            st["step"] = "oauth_wait"
            await event.reply(
                f"点这个链接登录{_provider_label(prefix)}：\n{provider_url}\n\n登录后浏览器会跳到一个打不开的 localhost 页面，把地址栏的链接完整复制发我。10 分钟内有效，不加了就发“取消”。")
            # 3. 等用户把 localhost 链接发回来（带 code 的），回放给本机上的 authorize 服务
            # 链接有问题就直接提示、结束这次添加（同时杀掉 authorize 进程），别让它一直挂着等。
            got_code = False
            while time.time() - t0 < _OAUTH_TIMEOUT:
                try:
                    pasted = await asyncio.wait_for(st["oauth_queue"].get(), timeout=max(1, _OAUTH_TIMEOUT - (time.time() - t0)))
                except asyncio.TimeoutError:
                    break
                if pasted is None:  # 取消了
                    return
                code, pasted_state = _parse_oauth_redirect(pasted)
                if not code:
                    await event.reply("这个链接里没有 code——登录完浏览器地址栏那个 localhost 链接才是。这次添加作废了，从 /storage 重新来吧。")
                    _cancel_storage_flow(uid)
                    return
                expected = st.get("oauth_state")
                if not pasted_state:
                    await event.reply("这个链接里没有 state，可能是复制得不完整。这次添加作废了，从 /storage 重新来吧。")
                    _cancel_storage_flow(uid)
                    return
                if expected and pasted_state != expected:
                    log(f"OAuth state 对不上：这次要 {expected[:8]}…，收到 {pasted_state[:8]}…（贴了旧链接）")
                    await event.reply("这个链接不是这次授权的（state 对不上），是之前那次的链接。这次添加作废了，从 /storage 重新来一遍，点最新那条消息里的登录链接，别用浏览器里旧的那个标签页。")
                    _cancel_storage_flow(uid)
                    return
                parsed = urllib.parse.urlparse(pasted.strip())
                cb_url = f"http://127.0.0.1:53682{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")

                def _replay(url):
                    try:
                        with urllib.request.urlopen(url, timeout=10) as resp:
                            return resp.status
                    except urllib.error.HTTPError as e:
                        return e.code
                    except Exception as e:
                        return str(e)

                await loop.run_in_executor(None, lambda: _replay(cb_url))
                got = False
                try:
                    for _ in range(10):
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=1)
                        if not line:
                            break
                        if "Got code" in line.decode(errors="replace"):
                            got = True
                            break
                except asyncio.TimeoutError:
                    pass
                if not got:
                    # state 对上了但回放没拿到 code：code 过期或已经用过了。
                    log("OAuth 回放后没拿到 Got code：state 对上了，但 code 可能过期或已用过")
                    await event.reply("这个链接的 code 好像过期或已经用过了。这次添加作废了，从 /storage 重新来一遍。")
                    _cancel_storage_flow(uid)
                    return
                got_code = True
                break
            if not got_code:
                if st.get("cancelled"):
                    return
                await event.reply("授权超时了（10 分钟），这次作废，从 /storage 重新来吧。")
                _storage_state.pop(uid, None)
                return
            # 4. 等 rclone 拿 code 换 token（换完进程自己退出）
            out_lines = []
            token = None
            try:
                while True:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=_OAUTH_EXCHANGE_TIMEOUT)
                    if not line:
                        break
                    text = line.decode(errors="replace")
                    out_lines.append(text)
                    m = re.search(r"\{[^{}]*\"access_token\"[^{}]*\}", text)
                    if m:
                        token = m.group(0)
                        break
            except asyncio.TimeoutError:
                pass
            if proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            if not token:
                if st.get("cancelled"):
                    return
                tail = "".join(out_lines[-6:]).strip()
                await event.reply(f"换 token 失败了：\n{tail or 'rclone 没给回 token'}\n可以从 /storage 重新试一次。")
                _storage_state.pop(uid, None)
                return
            st["token"] = token
            await event.reply("✅ 登录好了，token 已拿到。")
            if st["type"] == "onedrive":
                # OneDrive 还得先拿 drive_id / drive_type，不然列目录和 lsd 都会报缺这两项。
                try:
                    tok = json.loads(token)
                except Exception:
                    tok = {}
                try:
                    drive_id, drive_type = await loop.run_in_executor(None, lambda: _fetch_onedrive_drive(tok.get("access_token", "")))
                except Exception as e:
                    await event.reply(f"拿 OneDrive 的 drive 信息失败了：{str(e)[:200]}\n可以从 /storage 重新试一次。")
                    _storage_state.pop(uid, None)
                    return
                st["drive_id"] = drive_id
                st["drive_type"] = drive_type
            await _enter_folder_step(event, uid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log(f"OAuth 授权流程出错：{e}")
            if not st.get("cancelled"):
                try:
                    await event.reply(f"授权流程出错了：{e}\n可以从 /storage 重新试一次。")
                except Exception:
                    pass
            _storage_state.pop(uid, None)
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            st.pop("proc", None)
            st.pop("oauth_queue", None)

    async def _handle_storage_input(event, uid):
        """添加存储流程中用户发来的文字：名字 / 某一项凭据 / 补充参数 / 文件夹。"""
        st = _storage_state.get(uid)
        if not st:
            return
        text = (event.text or "").strip()
        if text in ("取消", "/cancel"):
            _cancel_storage_flow(uid)
            await event.reply("已取消添加存储。")
            return
        if st["step"] == "name":
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", text):
                await event.reply("名字只能用字母、数字、_ 和 -，1 到 32 个字符，再发一次。")
                return
            if text in _list_rclone_remotes() or text in _storages["storages"]:
                await event.reply(f"已经有个叫 {text} 的存储了，换个名字。")
                return
            st["remote"] = text
            if _is_oauth(st["type"]):
                st["step"] = "oauth"
                await event.reply(f"好的，名字就叫 {text}。\n正在启动授权…")
                asyncio.create_task(_run_oauth_flow(event, uid, st))
            else:
                st["step"] = "field"
                st["idx"] = 0
                fields = _manual_fields(st["type"])
                if fields:
                    await _storage_ask_field(event, uid)
                else:
                    st["step"] = "extra"
                    hint = _extra_hint(st["type"])
                    await event.reply("发配置参数，一行一个 key=value。" + (f"\n常用参数：{hint}。" if hint else "") + "\n没有就发“跳过”。")
            return
        if st["step"] == "field":
            fields = _manual_fields(st["type"])
            key, prompt, secret, optional = fields[st["idx"]]
            if secret:
                # 密钥消息读完就删掉，不留在聊天记录里；删不掉就提醒用户自己删。
                try:
                    await event.delete()
                except Exception:
                    pass
            if optional and text in ("跳过", "skip", ""):
                st["data"][key] = ""
            else:
                if not text:
                    await event.reply("这一项不能为空，再发一次。")
                    return
                st["data"][key] = text
            st["idx"] += 1
            if st["idx"] < len(fields):
                await _storage_ask_field(event, uid)
            else:
                st["step"] = "extra"
                await event.reply("还要补充参数吗？一行一个 key=value，没有就发“跳过”。")
            return
        if st["step"] == "extra":
            if text not in ("跳过", "完成", "skip", "done", ""):
                bad = []
                sensitive = False
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if "=" not in line:
                        bad.append(line)
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if not k:
                        bad.append(line)
                        continue
                    st["data"][k] = v
                    kl = k.lower()
                    if any(s in kl for s in ("secret", "pass", "token", "key", "pwd")):
                        sensitive = True
                if bad:
                    await event.reply(f"这几行没看懂（要 key=value 的格式）：{', '.join(bad)}，重新发，或者发“跳过”。")
                    return
                if sensitive:
                    # 里面有密钥，读完删掉这条消息。
                    try:
                        await event.delete()
                    except Exception:
                        pass
            st["step"] = "folder"
            await _enter_folder_step(event, uid)
            return
        if st["step"] == "mkdir":
            name = text.strip().strip("/")
            if not name or name in (".", "..") or "/" in name or not re.fullmatch(r"[A-Za-z0-9_.\- ]+", name):
                await event.reply("名字不太对，只能用字母、数字、_、-、. 和空格（不能带 /），再发一次。")
                return
            cur = st.get("browse_path", "")
            new_path = f"{cur}/{name}" if cur else name
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: _rclone_mkdir(st["remote"], new_path, _picker_rclone_args(st, uid)))
            except Exception as e:
                await event.reply(f"建文件夹失败：{_redact(str(e))[:200]}\n再发一个名字试试，或者发“取消”。")
                return
            st["folder"] = new_path
            if st.get("mode") == "edit":
                await _finish_edit_folder(event, uid, new_path)
                return
            st["step"] = "confirm"
            _cleanup_picker_config(uid)
            await event.reply(_confirm_storage_text(st), buttons=_confirm_storage_buttons())
            return
        if st["step"] == "folder":
            folder = "" if text in ("根目录", "跳过", "") else text.strip("/")
            if folder and not re.fullmatch(r"[A-Za-z0-9_.\-/]+", folder):
                await event.reply("文件夹名不太对，只能用字母、数字、_、-、. 和 /，再发一次。")
                return
            if st.get("mode") == "edit":
                await _finish_edit_folder(event, uid, folder)
                return
            st["folder"] = folder
            st["step"] = "confirm"
            _cleanup_picker_config(uid)
            await event.reply(_confirm_storage_text(st), buttons=_confirm_storage_buttons())
            return

    # 等着输 UTC 序号的用户（点了 /timezone 还没发数字的），只放内存里。
    _tz_pending = set()

    @client.on(events.NewMessage)
    async def handler(event):
        # 直接用 sender_id，不用 get_sender()：后者要查 session 数据库解析实体，
        # 数据库一旦被锁就会失败/返回空，导致把你自己的消息也当成陌生人拒绝。
        uid = event.sender_id or 0
        if event.is_group:
            # 群里只理艾特 bot 的消息（不然每条群消息都回“请发文件”太吵），
            # 白名单外的直接忽略，不回。加存储、改时区这些只在私聊里做。
            if uid not in ALLOWED or not _mentions_bot(event):
                return
            await _handle_group_mention(event, uid)
            return
        if event.is_channel:
            # 频道新帖：只处理白名单里的频道（bot 得是频道管理员才会收到）。
            await _handle_channel_post(event)
            return
        if not event.is_private:
            return  # 其它类型，不理
        if uid not in ALLOWED:
            # 记下来是谁被拒绝了，不然下次再刷屏又查不到原因。
            log(f"白名单拒绝：sender_id={uid}（0 表示拿不到发送者，常是频道转发的消息）")
            await event.reply("这个 bot 是私用的，只有白名单用户能用。")
            return
        if event.text and event.text.startswith("/"):
            if event.text.startswith("/start"):
                await event.reply(
                    "发文件给我，我会下载并上传到网盘（支持大文件）。\n"
                    "/storage 管网盘，/channels 管频道，/timezone 设时区。",
                    buttons=[
                        [Button.inline("📦 存储管理", data=b"stor:menu")],
                        [Button.inline("❓ 使用帮助", data=b"help")],
                    ],
                )
            elif event.text.startswith("/help"):
                await event.reply(_HELP_TEXT, buttons=[
                    [Button.inline("📦 存储管理", data=b"stor:menu")],
                    [Button.inline("📺 频道管理", data=b"chan:menu")],
                ])
            elif event.text.startswith("/timezone"):
                # /timezone：提示输入 UTC 序号；/timezone -8：直接设置。
                # Telegram 不提供用户的时区，只能让每个人自己设一次，存在 timezones.json。
                parts = event.text.split()
                if len(parts) == 1:
                    _, cur = get_user_tz(uid)
                    _tz_pending.add(uid)
                    await event.reply(
                        f"你当前的时区是：{cur}\n"
                        "发 UTC 序号改时区，比如 -8、+8（范围 -12 到 +12）；也可以发时区名，比如 Europe/London。"
                    )
                else:
                    parsed = _parse_tz_name(parts[1])
                    if not parsed:
                        await event.reply(
                            f"看不懂：{parts[1]}\n发一个 UTC 序号就行，比如 -8、+8，范围 -12 到 +12。"
                        )
                        return
                    _, disp = parsed
                    _user_timezones[str(uid)] = disp
                    _save_user_timezones()
                    _tz_pending.discard(uid)
                    await event.reply(f"时区已设为 {disp}，以后上传时间就按这个时区显示。")
            elif event.text.startswith("/storage"):
                _cancel_channel_flow(uid)
                _storage_state.pop(uid, None)
                await event.reply(_storage_menu_text(), buttons=_storage_menu_buttons())
            elif event.text.startswith("/channels"):
                _cancel_storage_flow(uid)
                _channel_state.pop(uid, None)
                await event.reply(_channels_menu_text(), buttons=_channels_menu_buttons())
            return
        # 刚点了 /timezone 的用户直接发了个数字：当成 UTC 序号设置时区。
        if event.text and uid in _tz_pending:
            text = event.text.strip()
            if re.fullmatch(r"[+-]?\d{1,2}", text):
                parsed = _parse_tz_name(text)
                if parsed:
                    _, disp = parsed
                    _user_timezones[str(uid)] = disp
                    _save_user_timezones()
                    _tz_pending.discard(uid)
                    await event.reply(f"时区已设为 {disp}，以后上传时间就按这个时区显示。")
                    return
                await event.reply("UTC 序号范围是 -12 到 +12，再发一次，比如 -8。")
                return
            _tz_pending.discard(uid)
        # 正在添加频道的流程中：用户转发的频道消息或发的 @用户名/ID 就是要加的频道。
        if uid in _channel_state:
            if event.file and _forwarded_channel_id(event) is None:
                # 发了个普通文件，添加流程作废，先处理文件。
                _cancel_channel_flow(uid)
            else:
                await _handle_channel_input(event, uid)
                return
        # 正在添加存储的流程中：用户发的文字就是要填的那一项。
        if uid in _storage_state:
            if event.file:
                # 发文件了，添加流程作废，先处理文件。
                _cancel_storage_flow(uid)
            else:
                st = _storage_state.get(uid)
                text = (event.text or "").strip()
                if st and st.get("step") == "oauth_wait" and text not in ("取消", "/cancel"):
                    # 授权等着收 localhost 链接：交给后台的 authorize 任务。
                    q = st.get("oauth_queue")
                    if q is not None:
                        q.put_nowait(text)
                    else:
                        await event.reply("授权还没准备好，稍等一下再发这个链接。")
                    return
                await _handle_storage_input(event, uid)
                return
        if not event.file:
            await event.reply("请发文件给我（文档/视频/图片/音频都行）。")
            return

        # 时区要先取：没文件名时生成名字里的日期用消息时间换算到用户时区。
        tz, tz_name = get_user_tz(uid)
        name, size = _file_name_and_size(event.message, tz)
        size_mb = size / 1024 / 1024
        _tz_pending.discard(uid)  # 发文件了，之前等的那次时区输入就作废
        log(f"收到文件 {name} ({size_mb:.1f} MB) 来自 {uid}")
        msg = await event.reply(f"收到 {name}（{size_mb:.1f} MB），正在下载…")
        await process_file(event, msg, name, size, event.message.media if event.message else None, _next_job_id(), tz=tz, tz_name=tz_name)

    async def _cb_uid(event, log_tag=None):
        """回调按钮的白名单检查：有权限返回 sender_id，没权限弹提示并返回 None。"""
        uid = event.sender_id or 0
        if uid not in ALLOWED:
            if log_tag:
                log(f"白名单拒绝（{log_tag}）：sender_id={uid}")
            await event.answer("你没有权限用这个 bot。", alert=True)
            return None
        return uid

    @client.on(events.CallbackQuery(pattern=rb"help"))
    async def help_button_handler(event):
        if await _cb_uid(event) is None:
            return
        await event.edit(_HELP_TEXT, buttons=[[Button.inline("📦 存储管理", data=b"stor:menu")]])

    @client.on(events.CallbackQuery(pattern=rb"retry:(\d+)"))
    async def retry_handler(event):
        uid = await _cb_uid(event, "重试按钮")
        if uid is None:
            return
        job_id = int(event.pattern_match.group(1))
        job = FAILED_JOBS.get(job_id)
        if not job:
            await event.answer("这个任务已经不在了，请重新发一次文件。", alert=True)
            return
        await event.answer("正在重试…")
        msg = await event.get_message()
        tz, tz_name = get_user_tz(job["user_id"])
        await process_file(event, msg, job["name"], job["size"], job["media"], job_id, tz=tz, tz_name=tz_name)

    # ---------- 存储管理：stor: 回调 ----------
    # ---------- 频道管理：chan: 回调 ----------
    @client.on(events.CallbackQuery(pattern=rb"chan:menu"))
    async def chan_menu_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        await event.edit(_channels_menu_text(), buttons=_channels_menu_buttons())

    @client.on(events.CallbackQuery(pattern=rb"chan:add"))
    async def chan_add_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        _cancel_storage_flow(uid)
        _channel_state[uid] = {"step": "add"}
        await event.edit(
            "加哪个频道？\n转发一条那个频道的消息给我，或者发频道的 @用户名 / ID（比如 -1001234567890）。\n不想加了发“取消”。",
            buttons=[[Button.inline("❌ 取消", data=b"chan:cancel")]],
        )

    @client.on(events.CallbackQuery(pattern=rb"chan:dellist"))
    async def chan_dellist_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        items = _channel_list()
        if not items:
            await event.answer("白名单是空的，没什么可删的。", alert=True)
            return
        buttons = []
        for c in items:
            disp = c.get("title") or c.get("username") or c["id"]
            buttons.append([Button.inline(f"🗑 {disp}", data=f"chan:del:{c['id']}".encode())])
        buttons.append([Button.inline("⬅️ 返回", data=b"chan:menu")])
        await event.edit("删哪个频道？", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"chan:del:(-?\d+)"))
    async def chan_del_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        cid = event.pattern_match.group(1).decode()
        ch = _channels["channels"].pop(cid, None)
        if not ch:
            await event.answer("这个频道已经不在白名单里了。", alert=True)
            return
        _save_channels()
        await event.edit(f"已删：{ch.get('title') or cid}。", buttons=[[Button.inline("⬅️ 返回频道管理", data=b"chan:menu")]])

    @client.on(events.CallbackQuery(pattern=rb"chan:cancel"))
    async def chan_cancel_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        _cancel_channel_flow(uid)
        await event.edit("不加了。", buttons=[[Button.inline("⬅️ 返回频道管理", data=b"chan:menu")]])

    @client.on(events.CallbackQuery(pattern=rb"stor:menu"))
    async def storage_menu_handler(event):
        if await _cb_uid(event) is None:
            return
        await event.edit(_storage_menu_text(), buttons=_storage_menu_buttons())

    @client.on(events.CallbackQuery(pattern=rb"stor:add"))
    async def storage_add_handler(event):
        if await _cb_uid(event) is None:
            return
        await event.edit(_storage_add_text(0), buttons=_storage_add_buttons(0))

    @client.on(events.CallbackQuery(pattern=rb"stor:page:(\d+)"))
    async def storage_page_handler(event):
        if await _cb_uid(event) is None:
            return
        page = int(event.pattern_match.group(1))
        page = max(0, min(page, len(_PROVIDER_PAGES) - 1))
        await event.edit(_storage_add_text(page), buttons=_storage_add_buttons(page))

    @client.on(events.CallbackQuery(pattern=rb"stor:type:(.+)"))
    async def storage_type_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        type_ = event.pattern_match.group(1).decode()
        if type_ == "import":
            loop = asyncio.get_running_loop()
            remotes = await loop.run_in_executor(None, _list_rclone_remotes)
            candidates = [r for r in remotes if r not in _storages["storages"]]
            if not candidates:
                await event.answer("rclone 配置里没有还没加进来的网盘。", alert=True)
                return
            buttons = [[Button.inline(r, data=f"stor:import:{r}".encode())] for r in candidates]
            buttons.append([Button.inline("❌ 取消", data=b"stor:cancel")])
            await event.edit("rclone 配置里有下面这些还没加进来的网盘，选一个导入：", buttons=buttons)
            return
        if type_ not in _PROVIDER_MAP:
            await event.answer("不认识这个类型。", alert=True)
            return
        # 先把上一次没走完的流程作废掉（正在跑的 authorize 进程也杀掉），不然旧进程还占着
        # 53682 端口，新流程的授权链接会对不上，用户贴回来的链接就一直报“对不上”。
        _cancel_storage_flow(uid)
        _storage_state[uid] = {"step": "name", "type": type_, "remote": "", "idx": 0, "data": {}, "folder": "", "import": False}
        if _is_oauth(type_):
            note = "接下来给你登录链接，登录后把跳回来的 localhost 链接发我。"
        else:
            note = "接下来按提示发配置。"
        await event.edit(f"添加{_provider_label(type_)}。先给它起个名字，只能用字母、数字、_ 和 -，比如 mydrive：\n{note}")

    @client.on(events.CallbackQuery(pattern=rb"stor:import:(.+)"))
    async def storage_import_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        remote = event.pattern_match.group(1).decode()
        if remote in _storages["storages"]:
            await event.answer("这个已经加过了。", alert=True)
            return
        kind = _rclone_remote_type(remote) or "other"
        _cancel_storage_flow(uid)
        _storage_state[uid] = {"step": "folder", "type": kind, "remote": remote, "idx": 0, "data": {}, "folder": "", "import": True}
        await event.edit(f"导入 {remote}（{kind}）。正在列目录…")
        await _enter_folder_step(event, uid, edit=True)

    @client.on(events.CallbackQuery(pattern=rb"stor:confirm"))
    async def storage_confirm_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        st = _storage_state.pop(uid, None)
        if not st or st.get("step") != "confirm":
            await event.answer("这个添加流程已经不在了，请重新从 /storage 开始。", alert=True)
            return
        _cleanup_picker_config(uid)
        await event.answer("正在添加…")
        try:
            loop = asyncio.get_running_loop()
            if not st.get("import"):
                if _is_oauth(st["type"]):
                    # OAuth 后端：config create 会重新跑 OAuth 卡住，直接写 rclone.conf。
                    # OneDrive 还得带上 drive_id / drive_type，不然 lsd 会报缺这两项
                    #（登录后就已经拿到了，这里只是兜底再拿一次）。
                    params = {"token": st.get("token") or ""}
                    if st["type"] == "onedrive":
                        if not st.get("drive_id"):
                            try:
                                tok = json.loads(st.get("token") or "{}")
                            except Exception:
                                tok = {}
                            drive_id, drive_type = await loop.run_in_executor(None, lambda: _fetch_onedrive_drive(tok.get("access_token", "")))
                            st["drive_id"], st["drive_type"] = drive_id, drive_type
                        params["drive_id"] = st["drive_id"]
                        params["drive_type"] = st["drive_type"]
                    await event.edit("正在写入 rclone 配置…")
                    await loop.run_in_executor(None, lambda: _write_rclone_remote_direct(st["remote"], st["type"], params))
                else:
                    params = _build_create_params(st["type"], st["data"], token=st.get("token"))
                    await event.edit("正在写入 rclone 配置…")
                    await loop.run_in_executor(None, lambda: _run_rclone_config_create(st["remote"], st["type"], params))
            await event.edit("正在验证这个网盘能不能用…")
            ok = await loop.run_in_executor(None, lambda: _verify_remote(st["remote"]))
            if not ok:
                # 有些网盘第一次要现发现 drive 之类，隔 5 秒再试一次。
                await asyncio.sleep(5)
                ok = await loop.run_in_executor(None, lambda: _verify_remote(st["remote"]))
            if not ok:
                if not st.get("import"):
                    _delete_rclone_remote(st["remote"])
                raise RuntimeError("验证失败：rclone 列不出这个网盘的目录，请检查填的凭据对不对")
            label = _provider_label(st["type"])
            _storages["storages"][st["remote"]] = {
                "remote": st["remote"],
                "folder": st.get("folder", ""),
                "kind": st["type"],
                "label": label,
            }
            _save_storages()
            disp = _storage_display(_storages["storages"][st["remote"]])
            folder = f"/{st.get('folder')}" if st.get("folder") else "/（根目录）"
            extra = ""
            if not _storages.get("default") and len(_storages["storages"]) > 1:
                extra = "\n还没选默认存储，收到文件时会问你存到哪个；也可以现在点下面设为默认。"
            buttons = None
            if not _storages.get("default"):
                buttons = [[Button.inline("⭐ 设为默认存储", data=f"stor:setdef:{st['remote']}".encode())]]
            await event.edit(f"✅ 已添加存储：{disp}\n文件夹：{folder}{extra}", buttons=buttons)
            log(f"已添加存储 {st['remote']}（{st['type']}）")
        except Exception as e:
            # 报错里可能带上完整命令（含 token），记日志前先抹掉。
            log(f"添加存储失败：{_redact(str(e))[:300]}")
            await event.edit(f"❌ 添加失败：{str(e)[:300]}\n可以从 /storage 重新试一次。")

    @client.on(events.CallbackQuery(pattern=rb"stor:cancel"))
    async def storage_cancel_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        _cancel_storage_flow(uid)
        await event.edit("已取消添加存储。", buttons=[[Button.inline("🔙 返回存储管理", data=b"stor:menu")]])

    # ---------- 选文件夹：进目录 / 选定 / 新建 / 手动输入 ----------
    async def _picker_guard(event):
        """选文件夹的按钮都先过这一关：流程不在了就别往下走。返回 st 或 None。"""
        uid = await _cb_uid(event)
        if uid is None:
            return None
        st = _storage_state.get(uid)
        if not st or st.get("step") not in ("folder", "mkdir"):
            await event.answer("这个选择已经不在了，请重新从 /storage 开始。", alert=True)
            return None
        return st

    @client.on(events.CallbackQuery(pattern=rb"stor:cd:(\d+)"))
    async def storage_cd_handler(event):
        st = await _picker_guard(event)
        if not st:
            return
        if st.get("step") != "folder":
            await event.answer("先完成新建文件夹那一步。", alert=True)
            return
        idx = int(event.pattern_match.group(1))
        dirs = st.get("browse_dirs") or []
        if idx < 0 or idx >= len(dirs):
            await event.answer("这个目录已经不在了。", alert=True)
            return
        cur = st.get("browse_path", "")
        st["browse_path"] = f"{cur}/{dirs[idx]}" if cur else dirs[idx]
        await _show_folder_picker(event, event.sender_id or 0, edit=True)

    @client.on(events.CallbackQuery(pattern=rb"stor:up"))
    async def storage_up_handler(event):
        st = await _picker_guard(event)
        if not st:
            return
        if st.get("step") != "folder":
            await event.answer("先完成新建文件夹那一步。", alert=True)
            return
        cur = st.get("browse_path", "")
        st["browse_path"] = cur.rsplit("/", 1)[0] if "/" in cur else ""
        await _show_folder_picker(event, event.sender_id or 0, edit=True)

    @client.on(events.CallbackQuery(pattern=rb"stor:sel"))
    async def storage_sel_handler(event):
        st = await _picker_guard(event)
        if not st:
            return
        if st.get("step") != "folder":
            await event.answer("先完成新建文件夹那一步。", alert=True)
            return
        if st.get("mode") == "edit":
            # 改位置：直接把选好的文件夹存进 storages.json，不用再确认。
            await _finish_edit_folder(event, event.sender_id or 0, st.get("browse_path", ""), edit=True)
            return
        st["folder"] = st.get("browse_path", "")
        st["step"] = "confirm"
        _cleanup_picker_config(event.sender_id or 0)
        await event.edit(_confirm_storage_text(st), buttons=_confirm_storage_buttons())

    @client.on(events.CallbackQuery(pattern=rb"stor:mkdir"))
    async def storage_mkdir_handler(event):
        st = await _picker_guard(event)
        if not st:
            return
        if st.get("step") != "folder":
            await event.answer("已经在新建了，直接发名字就行。", alert=True)
            return
        st["step"] = "mkdir"
        cur = st.get("browse_path", "")
        disp = "/" + cur if cur else "/（根目录）"
        await event.edit(f"新文件夹叫什么名字？只会建在 {disp} 下面。发一个名字就行。", buttons=[[Button.inline("❌ 取消", data=b"stor:cancel")]])

    @client.on(events.CallbackQuery(pattern=rb"stor:manual"))
    async def storage_manual_handler(event):
        st = await _picker_guard(event)
        if not st:
            return
        st["step"] = "folder"
        if st.get("mode") == "edit":
            await event.edit("发一下新的保存位置：文件夹名；想存根目录就发“根目录”。")
        else:
            await event.edit("发文件夹名；想存根目录就发“根目录”。")

    @client.on(events.CallbackQuery(pattern=rb"stor:editfolder"))
    async def storage_editfolder_handler(event):
        if await _cb_uid(event) is None:
            return
        items = _storage_list()
        if not items:
            await event.answer("还没有存储，先添加一个。", alert=True)
            return
        buttons = []
        for s in items:
            folder = f"/{s.get('folder')}" if s.get("folder") else "/（根目录）"
            buttons.append([Button.inline(f"📁 {_storage_display(s)} → {folder}", data=f"stor:edit:{s['remote']}".encode())])
        buttons.append([Button.inline("🔙 返回存储管理", data=b"stor:menu")])
        await event.edit("改哪个存储的保存位置？", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"stor:edit:(.+)"))
    async def storage_edit_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        remote = event.pattern_match.group(1).decode()
        s = _storages["storages"].get(remote)
        if not s:
            await event.answer("这个存储已经不在了。", alert=True)
            return
        # 先把正在进行的添加/改位置流程作废掉，再开改位置的流程。
        _cancel_storage_flow(uid)
        _storage_state[uid] = {
            "step": "folder", "mode": "edit", "type": s.get("kind", ""), "remote": remote,
            "idx": 0, "data": {}, "folder": s.get("folder", ""), "import": True,
        }
        await event.edit("正在列目录…")
        await _enter_folder_step(event, uid, edit=True, start_path=s.get("folder", ""))

    @client.on(events.CallbackQuery(pattern=rb"stor:default"))
    async def storage_default_handler(event):
        if await _cb_uid(event) is None:
            return
        buttons = [[Button.inline(f"⭐ {_storage_display(s)}", data=f"stor:setdef:{s['remote']}".encode())] for s in _storage_list()]
        if _storages.get("default"):
            buttons.append([Button.inline("清除默认存储", data=b"stor:cleardef")])
        buttons.append([Button.inline("🔙 返回", data=b"stor:menu")])
        await event.edit("选一个作为默认存储，收到文件就直接往它发：", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"stor:setdef:(.+)"))
    async def storage_setdef_handler(event):
        if await _cb_uid(event) is None:
            return
        remote = event.pattern_match.group(1).decode()
        s = _storages["storages"].get(remote)
        if not s:
            await event.answer("这个存储已经不在了。", alert=True)
            return
        _storages["default"] = remote
        _save_storages()
        log(f"默认存储改为 {remote}")
        await event.edit(f"✅ 默认存储已设为：{_storage_display(s)}\n以后收到文件默认往它发。", buttons=[[Button.inline("🔙 返回存储管理", data=b"stor:menu")]])

    @client.on(events.CallbackQuery(pattern=rb"stor:cleardef"))
    async def storage_cleardef_handler(event):
        if await _cb_uid(event) is None:
            return
        _storages["default"] = None
        _save_storages()
        await event.edit("已清除默认存储。多个网盘时，收到文件会问你存到哪个。", buttons=[[Button.inline("🔙 返回存储管理", data=b"stor:menu")]])

    @client.on(events.CallbackQuery(pattern=rb"stor:dellist"))
    async def storage_dellist_handler(event):
        if await _cb_uid(event) is None:
            return
        items = _storage_list()
        if not items:
            await event.answer("还没有存储，先添加一个。", alert=True)
            return
        buttons = []
        for s in items:
            buttons.append([Button.inline(f"🗑 删除 {_storage_display(s)}", data=f"stor:del:{s['remote']}".encode())])
        buttons.append([Button.inline("🔙 返回存储管理", data=b"stor:menu")])
        await event.edit("删除哪个存储？", buttons=buttons)

    @client.on(events.CallbackQuery(pattern=rb"stor:del:(.+)"))
    async def storage_del_handler(event):
        if await _cb_uid(event) is None:
            return
        remote = event.pattern_match.group(1).decode()
        s = _storages["storages"].get(remote)
        if not s:
            await event.answer("这个存储已经不在了。", alert=True)
            return
        await event.edit(
            f"确定删除 {_storage_display(s)} 吗？\nrclone 配置里的这个网盘也会删掉，网盘上的文件不动；是默认存储的话默认也会清除。",
            buttons=[[Button.inline("🗑 确认删除", data=f"stor:delconfirm:{remote}".encode()), Button.inline("取消", data=b"stor:menu")]],
        )

    @client.on(events.CallbackQuery(pattern=rb"stor:delconfirm:(.+)"))
    async def storage_delconfirm_handler(event):
        if await _cb_uid(event) is None:
            return
        remote = event.pattern_match.group(1).decode()
        s = _storages["storages"].pop(remote, None)
        if not s:
            await event.answer("这个存储已经不在了。", alert=True)
            return
        if _storages.get("default") == remote:
            _storages["default"] = None
        _save_storages()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: _delete_rclone_remote(remote))
        log(f"已删除存储 {remote}")
        await event.edit(f"已删除存储 {_storage_display(s)}。", buttons=[[Button.inline("🔙 返回存储管理", data=b"stor:menu")]])

    # ---------- 下载完选存哪个网盘：dst: 回调 ----------
    @client.on(events.CallbackQuery(pattern=rb"dst:(cancel:)?(\d+)(?::(.+))?"))
    async def dst_handler(event):
        uid = await _cb_uid(event)
        if uid is None:
            return
        cancel = event.pattern_match.group(1)
        job_id = int(event.pattern_match.group(2))
        pending = PENDING_DST.pop(job_id, None)
        if not pending:
            await event.answer("这个任务已经不在了，请重新发一次文件。", alert=True)
            return
        if cancel:
            try:
                if os.path.exists(pending["local"]):
                    os.remove(pending["local"])
            except Exception:
                pass
            await event.edit("已取消，本地文件已删。")
            return
        remote = (event.pattern_match.group(3) or b"").decode()
        storage = _storages["storages"].get(remote)
        if not storage:
            await event.answer("这个存储已经不在了，请重新发一次文件。", alert=True)
            try:
                if os.path.exists(pending["local"]):
                    os.remove(pending["local"])
            except Exception:
                pass
            return
        await event.answer("正在上传…")
        msg = await event.get_message()

        async def _do_upload():
            return await _finish_upload(event, msg, pending["name"], pending["size"], pending["media"], pending["local"], storage, job_id, tz=pending["tz"], tz_name=pending["tz_name"])

        if _file_sem is None:
            await _do_upload()
        else:
            async with _file_sem:
                await _do_upload()

    await client.run_until_disconnected()
    _clear_pid_file()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
