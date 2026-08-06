# TRX 能量租赁机器人

Telegram **TRX 能量租赁**机器人（适合自用）。

发送「笔数 + 地址」→ 二次确认 → 调用上游能量 API 下单 → 回执成功 / 失败。仅作者与被授权用户可用，无公开下单入口、无广告。支持主 bot + N 个克隆 bot 同进程托管，各自独立 API 与管理员。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

**作者**：[Telegram @yuuu](https://t.me/yuuu)

> **关于 trxfee.io（重要）**  
> 默认适配 [trxfee.io](https://doc.trxfee.io) **仅为示例上游**，可自行更换。该平台与作者无关，不构成推荐或背书。换源主要改 [`energy_bot/trxfee.py`](energy_bot/trxfee.py) 与相关环境变量。

---

## 目录

1. [适合谁 / 不适合谁](#适合谁--不适合谁)
2. [功能一览](#功能一览)
3. [架构](#架构)
4. [技术栈](#技术栈)
5. [上游能量平台（可更换）](#上游能量平台可更换)
6. [能量规则](#能量规则)
7. [完整部署教程](#完整部署教程)
8. [环境变量](#环境变量)
9. [使用方式](#使用方式)
10. [管理员指令](#管理员指令)
11. [克隆机器人](#克隆机器人)
12. [目录结构](#目录结构)
13. [安全说明](#安全说明)
14. [常见问题](#常见问题)
15. [免责声明](#免责声明)
16. [License](#license)

---

## 适合谁 / 不适合谁

| ✅ 适合 | ❌ 不适合 |
|---|---|
| 个人自用：给自己的地址租能量 | 面向陌生用户的公开租赁商城 |
| 小团队：作者授权若干同事使用 | 需要收款、套餐、用户余额体系 |
| 多号运营：主 bot + 克隆 bot 分账号 | 需要 Web 管理后台 / 订单库 |
| 快速挂一个能量上游、少依赖上线 | 需要链上自建能量池 |

本仓库定位是**自用工具型**机器人，不是 C 端能量商城。若你要做对客售卖、收款归集、管理后台，请另选完整业务系统。

---

## 功能一览

| 能力 | 说明 |
|---|---|
| 快捷下单 | 文本 `N笔` + TRON 地址（同行或分行），弹出确认后下单 |
| 能量套餐 | 1 笔 = 65000；2 笔 = 131000（市场对齐）；其余 `N × 65000` |
| 时长 | 固定 `1H`（有效期约 60 分钟，请尽快使用） |
| 访问控制 | 仅 `AUTHOR_ID`（作者）与被授权用户可用；其余用户静默 |
| 授权管理 | `授权 @用户` / `授权 ID` / 引用消息授权；`授权列表` |
| 余额查询 | 发「余额」查看上游 API 余额与充值地址 |
| 多 bot 托管 | 主 bot 可「克隆」出独立 token / API / 管理员的子 bot |
| 二次确认 | 下单前内联确认，降低误触 |

---

## 架构

```
Telegram 用户（作者 / 已授权）
        │  long polling
        ▼
┌─────────────────── 同进程 ───────────────────┐
│  主 bot (AUTHOR_ID)                          │
│    ├─ handlers   笔数解析 / 授权 / 克隆流程    │
│    ├─ trxfee     上游能量 API 客户端（默认可换） │
│    ├─ AuthStore  authorized_<bot_id>.json     │
│    └─ CloneManager ←→ N 个克隆 Application    │
│         各自：token / api_key / admin / 授权名单 │
└──────────────────────────────────────────────┘
        │ HTTPS + API-KEY / SIGNATURE（默认实现）
        ▼
     上游能量平台（默认示例：trxfee.io，可更换）
```

**设计要点**

- **自用优先**：默认拒绝未授权用户，不暴露公开菜单
- **笔数抽象**：用户按「笔」思考，能量换算集中在一处，避免散落魔法数
- **二次确认**：callback 再校验权限后才真正扣费下单
- **克隆隔离**：每个 bot 独立上游账号与授权名单；密钥落盘 `clones.json`（勿提交）
- **轻量持久化**：授权 / 克隆配置用本地 JSON 原子写，无需数据库
- **上游可替换**：能量下单集中在 `trxfee.py`，与 Telegram 交互层解耦

---

## 技术栈

| 组件 | 版本 / 说明 |
|---|---|
| Python | 3.10+（推荐 3.12 / 3.14） |
| [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | v22（含 JobQueue） |
| httpx | 调用上游能量 HTTP API |
| python-dotenv | 加载 `.env` |
| 持久化 | 本地 JSON（授权名单 / 克隆配置） |
| 上游（默认示例） | [trxfee.io](https://doc.trxfee.io) —— 可更换，与作者无关 |

---

## 上游能量平台（可更换）

本仓库**默认**实现了对 [trxfee.io](https://doc.trxfee.io) 的适配，原因只是开发时随手选用，**并非唯一方案，也不代表作者与该平台有任何关系**。

| 说明 | 内容 |
|---|---|
| 默认上游 | trxfee.io（示例） |
| 与作者关系 | **无关**；无合作、无分成、无官方背书 |
| 是否必须用它 | **否**，可自行更换 |
| 主要改动点 | [`energy_bot/trxfee.py`](energy_bot/trxfee.py)（请求/签名/字段映射） |
| 配置项 | `TRXFEE_BASE_URL` / `TRXFEE_API_KEY` / `TRXFEE_API_SECRET`（变量名沿用历史，换源后可继续复用或自行改名） |

更换建议：保持 `create_order` / `api_info` 等调用面大致稳定，handlers 几乎不用动；若新平台字段或鉴权方式不同，只在客户端层做适配即可。

---

## 能量规则

| 笔数 | 下单能量 | 说明 |
|---|---|---|
| 1 | `65000` | 单笔转账常见用量 |
| 2 | `131000` | 市场双笔套餐（**非线性**，不是 `2 × 65000`） |
| N≥3 | `N × 65000` | 按单笔累加 |

时长固定 `1H`。常量见 `energy_bot/handlers.py` 中的 `ENERGY_PER_DEAL` / `ENERGY_TWO_DEALS`。

---

## 完整部署教程

假设你有一台 Linux 服务器（Debian / Ubuntu / 宝塔均可）。本项目仅需出网访问 Telegram API 与 trxfee.io，**不需要公网域名或 Webhook**。

### 第 0 步：准备材料

| 材料 | 怎么拿 |
|---|---|
| Bot Token | 私聊 [@BotFather](https://t.me/BotFather) → `/newbot` → 复制 Token |
| 你的 Telegram 数字 ID | 私聊 [@userinfobot](https://t.me/userinfobot) |
| trxfee API-KEY / SECRET | 登录 [trxfee.io](https://trxfee.io) 创建 API，并**把服务器出口 IP 加入白名单** |
| 充值地址 | trxfee 账户充值地址（用于「余额」指令展示） |

> trxfee 侧常见坑：未加 IP 白名单会被 Cloudflare 拦截，日志里会出现 `cf-ray=...`。

### 第 1 步：服务器环境

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

python3 --version   # ≥ 3.10
```

### 第 2 步：拉取代码并安装依赖

```bash
cd /opt   # 或 /www/wwwroot 等自定目录
sudo git clone https://github.com/shuaiqideyu/trx-energy-rental-bot.git
cd trx-energy-rental-bot

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 第 3 步：配置 `.env`

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

**最少必填：**

```env
BOT_TOKEN=123456789:AA...your_bot_token
AUTHOR_ID=你的Telegram数字ID
TRXFEE_API_KEY=你的KEY
TRXFEE_API_SECRET=你的SECRET
RECHARGE_ADDR=T你的充值地址
```

完整字段见下文 [环境变量](#环境变量)。

### 第 4 步：进程守护（systemd）

创建 `/etc/systemd/system/trx-energy-bot.service`：

```ini
[Unit]
Description=TRX Energy Rental Bot (self-use)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trx-energy-rental-bot
Environment=PATH=/opt/trx-energy-rental-bot/.venv/bin
ExecStart=/opt/trx-energy-rental-bot/.venv/bin/python run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trx-energy-bot
sudo systemctl status trx-energy-bot
sudo journalctl -u trx-energy-bot -f
```

宝塔「Python 项目」：启动命令：

```bash
.venv/bin/python run.py
```

### 第 5 步：验收清单

| # | 检查项 | 怎么验 |
|---|---|---|
| 1 | 进程存活 | `systemctl status trx-energy-bot` 为 active |
| 2 | 作者可用 | 用 `AUTHOR_ID` 账号私聊 `/start`，出现使用说明 |
| 3 | 陌生人静默 | 未授权账号发消息，机器人无任何回复 |
| 4 | 下单闭环 | 发 `1笔` + 地址 → 确认 → 成功回执 |
| 5 | 能量数值 | `1笔` 显示 65000；`2笔` 显示 **131000** |
| 6 | 余额 | 发「余额」能看到 TRX 余额与充值地址 |
| 7 | 单实例 | `ps` 里同一 token 只应有 **一个** 进程（避免 getUpdates Conflict） |

### 第 6 步：日常运维

```bash
# 日志
sudo journalctl -u trx-energy-bot -n 200 --no-pager

# 改 .env 后重启
sudo systemctl restart trx-energy-bot

# 备份运行数据（授权 / 克隆含密钥，务必保密）
cp clones.json "clones.json.bak.$(date +%F-%H%M%S)" 2>/dev/null
cp authorized_*.json ./backup/ 2>/dev/null
```

更新代码：

```bash
cd /opt/trx-energy-rental-bot
source .venv/bin/activate
git pull
pip install -r requirements.txt
sudo systemctl restart trx-energy-bot
```

---

## 环境变量

权威模板：[`.env.example`](.env.example)。

| 变量 | 必填 | 说明 |
|---|---|---|
| `BOT_TOKEN` | ✅ | `@BotFather` 发放的 Token |
| `AUTHOR_ID` | ✅ | 作者 Telegram 数字 ID（超级管理员） |
| `TRXFEE_API_KEY` | ✅ | trxfee.io API-KEY |
| `TRXFEE_API_SECRET` | ✅ | 与 KEY 成对的 SECRET（HMAC-SHA256 签名） |
| `TRXFEE_BASE_URL` | ❌ | 默认 `https://trxfee.io/v1` |
| `RECHARGE_ADDR` | 建议填 | 「余额」指令展示的充值地址 |

### 签名说明（trxfee.io）

POST 请求按官方规则：

1. 请求体 key 字母序排序 → 无空格 JSON  
2. `message = "{timestamp}&{json}"`  
3. `SIGNATURE = HMAC-SHA256(API_SECRET, message).hexdigest()`  
4. 请求头携带 `API-KEY` / `TIMESTAMP` / `SIGNATURE`

GET 仅需 `API-KEY`。实现见 [`energy_bot/trxfee.py`](energy_bot/trxfee.py)。

---

## 使用方式

作者或已授权用户，在**私聊或群**发送：

```text
1笔
TABCDEFghijkmnopqrstuvwxyz12345678
```

或同一行：

```text
2笔 TABCDEFghijkmnopqrstuvwxyz12345678
```

机器人弹出确认卡片 → 点「确认发送」→ 下单并回执。

发「`余额`」查询 API 余额与充值地址。

---

## 管理员指令

仅**作者**（`AUTHOR_ID`）可用：

| 指令 | 说明 |
|---|---|
| `授权 @用户名` / `授权 数字ID` | 授予下单权限 |
| 引用对方消息后发「授权」 | 同上 |
| `取消授权 @用户名` / `取消授权 数字ID` | 撤销 |
| `授权列表` | 查看名单 |
| `克隆` | 交互式创建克隆 bot（见下节） |
| `克隆列表` | 列出已托管克隆 |
| `删除克隆 @用户名` 或 bot_id | 停止并移除克隆 |

被授权用户可以下单与查余额，**不能**管理授权或克隆。

---

## 克隆机器人

主 bot 作者发「`克隆`」，按提示依次提供：

1. 克隆 bot 的 Telegram Token  
2. 该 bot 使用的 trxfee API-KEY  
3. API-SECRET  
4. 充值地址  
5. 该 bot 的管理员数字 ID  

确认后写入 `clones.json` 并在同进程内拉起。每个克隆拥有独立授权名单文件 `authorized_<bot_id>.json`。

> **安全提示**：克隆流程会在 Telegram 对话中收取 API Secret；聊天记录即密钥载体。生产环境建议尽量私聊操作，并定期轮换密钥。`clones.json` **禁止**提交到 Git。

---

## 目录结构

```
.
├── energy_bot/
│   ├── __init__.py
│   ├── bot.py           # 主流程装配与优雅退出
│   ├── config.py        # 环境变量加载与校验
│   ├── handlers.py      # 下单 / 授权 / 克隆交互
│   ├── keyboards.py     # 确认按钮
│   ├── manager.py       # 主 bot + 克隆托管
│   ├── store.py         # 授权名单持久化
│   └── trxfee.py        # trxfee.io 客户端（签名 + API）
├── run.py               # 入口：python run.py
├── requirements.txt
├── .env.example
├── LICENSE
└── README.md
```

运行期生成（已在 `.gitignore`，勿提交）：

| 文件 | 内容 |
|---|---|
| `.env` | 密钥与作者 ID |
| `clones.json` | 克隆 bot 的 token / API 密钥 |
| `authorized_<bot_id>.json` | 各 bot 授权名单 |

---

## 安全说明

- 不要提交 `.env`、`clones.json`、`authorized_*.json`
- 生产 `.env` 建议 `chmod 600`
- trxfee API Secret 仅用于本地 HMAC，勿写入日志或群聊留存
- 未授权用户一律静默，降低被扫号骚扰面
- **同一 Bot Token 只允许一个轮询进程**，否则会出现 `Conflict: terminated by other getUpdates request`
- 克隆 bot 的密钥与主 bot 同等敏感，备份时加密存放

---

## 常见问题

**发消息没反应？**  
确认你的 ID 是 `AUTHOR_ID`，或已被作者授权。未授权用户设计为静默。

**下单被 Cloudflare 拦截？**  
把服务器出口 IP 加入 trxfee 白名单；错误信息里通常带 `cf-ray=`。

**2 笔不是 130000？**  
正确。本项目 2 笔固定 **131000**（市场双笔套餐），不是简单的 `2 × 65000`。

**重启后克隆 bot 没了？**  
克隆配置在 `clones.json`。确认该文件仍在工作目录且进程工作目录正确。

**报 Conflict / 消息偶发旧逻辑？**  
几乎一定是同一 token 跑了多个进程（多机或宝塔重复启动）。`ps` 查清后只保留一个。

**余额地址不对？**  
trxfee `/account` 对本账号可能不准；请在 `.env` 设置 `RECHARGE_ADDR`。

---

## 免责声明

本项目以开源软件形式提供，**按现状（AS IS）交付**，定位为**适合自用**的能量租赁辅助工具。使用本软件调用第三方能量接口、操作链上资产时，请自行遵守所在地法律法规、Telegram 服务条款以及所选上游平台规则。

默认示例上游 trxfee.io **与作者无关**，可自行更换；因使用、更换或依赖任何第三方能量平台而产生的纠纷、资损或服务中断，均由使用者自行承担。作者不对因使用本软件产生的任何直接或间接损失承担责任。

---

## License

[MIT](LICENSE)

**作者**：[Telegram @yuuu](https://t.me/yuuu)
