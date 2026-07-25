"""快捷命令式交互。

作者 / 授权用户在群组 / 私聊发送如下格式即可触发（笔数与地址同行或分行均可，顺序不限）：

    1笔
    TABCDEFghijkmnopqrstuvwxyz12345678

含义：给该地址发送 N 笔能量（1 笔 = 65000，2 笔 = 131000，时长 1H）。
机器人弹出二次确认，点「确认发送」后下单，返回成功/失败。

访问控制：仅作者与授权用户可用；其余用户一律静默。
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import keyboards as kb
from .trxfee import TrxFeeClient, TrxFeeError

logger = logging.getLogger(__name__)

ENERGY_PER_DEAL = 65000  # 1 笔；2 笔固定 131000（非线性，对齐市场标准）
ENERGY_TWO_DEALS = 131000
ORDER_PERIOD = "1H"


def _energy_for_count(count: int) -> int:
    if count == 2:
        return ENERGY_TWO_DEALS
    return count * ENERGY_PER_DEAL

_COUNT_RE = re.compile(r"(\d+)\s*笔")
_ADDR_RE = re.compile(r"T[1-9A-HJ-NP-Za-km-z]{33}")
_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
_BALANCE_WORDS = {"余额", "查余额", "balance"}
_CLONE_TRIGGERS = {"克隆", "克隆机器人", "新增克隆", "添加克隆"}

# 克隆流程依次收集的字段
_CLONE_STEPS: list[tuple[str, str]] = [
    ("token", "第 1/5 步：请发送克隆 bot 的 <b>Telegram Token</b>（@BotFather 获取）："),
    ("api_key", "第 2/5 步：请发送该 bot 使用的 <b>trxfee API-KEY</b>："),
    ("api_secret", "第 3/5 步：请发送对应的 <b>API-SECRET</b>："),
    ("recharge_addr", "第 4/5 步：请发送该 bot 显示的 <b>充值地址</b>（TRON 地址）："),
    ("admin_id", "第 5/5 步：请发送该 bot 的 <b>管理员数字 ID</b>："),
]
_CLONE_PROMPTS = dict(_CLONE_STEPS)


def _client(context: ContextTypes.DEFAULT_TYPE) -> TrxFeeClient:
    return context.bot_data["client"]


def _is_author(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return user_id == context.bot_data["author_id"]


def _is_allowed(context: ContextTypes.DEFAULT_TYPE, user) -> bool:
    """作者或被授权用户（不限量）。"""
    if user is None:
        return False
    if _is_author(context, user.id):
        return True
    return context.bot_data["auth_store"].is_authorized(user.id, user.username)


def _match_auth(text: str) -> tuple[bool, str] | None:
    """识别「授权 / 取消授权」指令，返回 (是否授权, 参数)；非该指令返回 None。"""
    for cmd, grant in (("取消授权", False), ("授权", True)):
        if text == cmd:
            return grant, ""
        if text.startswith(cmd):
            rest = text[len(cmd):]
            head = rest[:1]
            if head in (" ", "\u3000", "@") or rest.strip()[:1].isdigit():
                return grant, rest.strip()
    return None


def _e(value: Any) -> str:
    return html.escape(str(value))


def _parse_command(text: str) -> tuple[int, str] | None:
    """从文本中解析 (笔数, 地址)；二者缺一则返回 None。"""
    m_count = _COUNT_RE.search(text)
    m_addr = _ADDR_RE.search(text)
    if not m_count or not m_addr:
        return None
    count = int(m_count.group(1))
    if count <= 0:
        return None
    return count, m_addr.group(0)


# ---------------- 命令 ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(context, update.effective_user):
        return
    text = (
        "⚡ <b>能量小助手</b>\n\n"
        "直接发送（笔数 + 地址，分行或同行都行）：\n"
        "<code>1笔\nTABCDEFghijkmnopqrstuvwxyz12345678</code>\n\n"
        f"1 笔 = {ENERGY_PER_DEAL} 能量，2 笔 = {ENERGY_TWO_DEALS} 能量，确认后给该地址发送。\n"
        "发「<code>余额</code>」查询余额与充值地址。"
    )
    if _is_clone_admin(context, update.effective_user.id):
        text += (
            "\n\n<b>管理员指令</b>\n"
            "授权：<code>授权 @用户名</code> / <code>授权 ID</code> / 引用消息发「授权」\n"
            "克隆：发「<code>克隆</code>」按步骤创建 ｜ <code>克隆列表</code> ｜ <code>删除克隆 @用户名</code>"
        )
    await update.effective_message.reply_html(text)


# ---------------- 授权管理 ----------------
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


async def _handle_auth(update, context, *, grant: bool, arg: str) -> None:
    msg = update.effective_message
    store = context.bot_data["auth_store"]
    reply = msg.reply_to_message

    target_id: int | None = None
    target_username: str | None = None
    display: str

    if not arg and reply and reply.from_user:
        tu = reply.from_user
        target_id = tu.id
        target_username = tu.username
        display = f"@{tu.username}" if tu.username else f"id {tu.id}"
    elif arg.startswith("@") and _USERNAME_RE.match(arg[1:]):
        target_username = arg[1:]
        display = arg
    elif arg.isdigit():
        target_id = int(arg)
        display = f"id {arg}"
    elif _USERNAME_RE.match(arg):
        target_username = arg
        display = f"@{arg}"
    else:
        await msg.reply_html(
            "用法：\n"
            "<code>授权 @用户名</code>\n"
            "<code>授权 数字ID</code>\n"
            "或 <b>引用</b>对方一条消息发「授权」/「取消授权」"
        )
        return

    if target_id is not None and _is_author(context, target_id):
        await msg.reply_html("ℹ️ 作者本人无需授权。")
        return

    if grant:
        store.add(user_id=target_id, username=target_username)
        await msg.reply_html(f"✅ 已授权 {_e(display)}")
    else:
        ok = store.remove(user_id=target_id, username=target_username)
        await msg.reply_html(
            f"✅ 已取消授权 {_e(display)}" if ok else f"ℹ️ {_e(display)} 不在授权名单"
        )


# ---------------- 克隆机器人管理（仅主 bot 作者）----------------
def _is_clone_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return bool(context.bot_data.get("is_main")) and _is_author(context, user_id)


async def _start_clone_flow(update, context) -> None:
    context.user_data["clone_flow"] = {"step": "token", "data": {}}
    await update.effective_message.reply_html(
        "🧬 <b>新增克隆机器人</b>（随时发「取消」中止）\n\n"
        + _CLONE_PROMPTS["token"]
    )


async def _handle_clone_flow(update, context, text: str) -> None:
    msg = update.effective_message
    flow = context.user_data["clone_flow"]
    step = flow["step"]
    data = flow["data"]
    base_url = context.bot_data["base_url"]

    if step == "token":
        token = text.strip()
        if not _TOKEN_RE.match(token):
            await msg.reply_html("⚠️ Token 格式不对，应形如 <code>123456:AAH...</code>，请重发：")
            return
        try:
            async with Bot(token) as b:
                me = await b.get_me()
        except Exception as exc:  # noqa: BLE001
            await msg.reply_html(f"❌ Token 校验失败：{_e(exc)}\n请重发：")
            return
        data["token"] = token
        data["username"] = me.username
        flow["step"] = "api_key"
        await msg.reply_html(f"✅ 识别到 bot <b>@{_e(me.username)}</b>\n\n" + _CLONE_PROMPTS["api_key"])
        return

    if step == "api_key":
        data["api_key"] = text.strip()
        flow["step"] = "api_secret"
        await msg.reply_html(_CLONE_PROMPTS["api_secret"])
        return

    if step == "api_secret":
        data["api_secret"] = text.strip()
        flow["step"] = "recharge_addr"
        await msg.reply_html(_CLONE_PROMPTS["recharge_addr"])
        return

    if step == "recharge_addr":
        addr = text.strip()
        if not _ADDR_RE.match(addr):
            await msg.reply_html("⚠️ 不是有效的 TRON 地址，请重发：")
            return
        data["recharge_addr"] = addr
        flow["step"] = "admin_id"
        await msg.reply_html(_CLONE_PROMPTS["admin_id"])
        return

    if step == "admin_id":
        if not text.strip().isdigit():
            await msg.reply_html("⚠️ 管理员 ID 应为纯数字，请重发：")
            return
        data["admin_id"] = int(text.strip())
        # 校验 API（顺带确认 IP 白名单）
        balance_line = ""
        try:
            info = await TrxFeeClient(data["api_key"], data["api_secret"], base_url).api_info()
            balance_line = f"\nAPI 余额：<code>{_e(info.get('data', {}).get('balance'))}</code> TRX"
        except TrxFeeError as exc:
            await msg.reply_html(
                f"❌ API 校验失败：{_e(exc)}\n"
                "请确认 API-KEY/SECRET 正确、且该账号已把服务器 IP 加入白名单。"
                "已中止克隆，重新发「克隆」再来一次。"
            )
            context.user_data.pop("clone_flow", None)
            return
        except Exception as exc:  # noqa: BLE001
            await msg.reply_html(f"❌ API 校验异常：{_e(exc)}，已中止。")
            context.user_data.pop("clone_flow", None)
            return
        flow["step"] = "confirm"
        await msg.reply_html(
            "请确认克隆配置：\n"
            f"机器人：<b>@{_e(data.get('username'))}</b>\n"
            f"管理员 ID：<code>{data['admin_id']}</code>\n"
            f"充值地址：<code>{_e(data['recharge_addr'])}</code>"
            f"{balance_line}",
            reply_markup=kb.clone_confirm_kb(),
        )
        return


async def _submit_clone(query, context) -> None:
    flow = context.user_data.get("clone_flow")
    if not flow or flow.get("step") != "confirm":
        await query.edit_message_text("⚠️ 没有待确认的克隆。")
        return
    data = flow["data"]
    manager = context.bot_data.get("manager")
    try:
        await manager.add_clone(
            {
                "token": data["token"],
                "username": data.get("username"),
                "api_key": data["api_key"],
                "api_secret": data["api_secret"],
                "recharge_addr": data["recharge_addr"],
                "admin_id": data["admin_id"],
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("克隆启动失败")
        context.user_data.pop("clone_flow", None)
        await query.edit_message_text(f"❌ 克隆失败：{_e(exc)}", parse_mode=ParseMode.HTML)
        return
    context.user_data.pop("clone_flow", None)
    await query.edit_message_text(
        f"✅ 克隆已上线：<b>@{_e(data.get('username'))}</b>\n"
        f"管理员 ID：<code>{data['admin_id']}</code>\n"
        "该 bot 已开始独立运行。",
        parse_mode=ParseMode.HTML,
    )


async def _handle_clone_list(update, context) -> None:
    manager = context.bot_data.get("manager")
    rows = manager.list() if manager else []
    if not rows:
        await update.effective_message.reply_html("📋 <b>克隆列表</b>\n（空）")
        return
    lines = ["📋 <b>克隆列表</b>"]
    for i, c in enumerate(rows, 1):
        bot_id = str(c["token"]).split(":", 1)[0]
        lines.append(
            f"\n#{i} @{_e(c.get('username'))}\n"
            f"  bot_id：<code>{bot_id}</code>\n"
            f"  管理员：<code>{c.get('admin_id')}</code>\n"
            f"  充值地址：<code>{_e(c.get('recharge_addr'))}</code>"
        )
    await update.effective_message.reply_html("\n".join(lines))


async def _handle_clone_remove(update, context, key: str) -> None:
    manager = context.bot_data.get("manager")
    if not key:
        await update.effective_message.reply_html("用法：<code>删除克隆 &lt;bot_id 或 @用户名&gt;</code>")
        return
    cfg = await manager.remove_clone(key) if manager else None
    if cfg:
        await update.effective_message.reply_html(f"✅ 已删除并停止克隆 @{_e(cfg.get('username'))}")
    else:
        await update.effective_message.reply_html(f"ℹ️ 未找到克隆：{_e(key)}")


# ---------------- 文本：检测格式 ----------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    user = msg.from_user
    text = msg.text.strip()

    # ---- 进行中的克隆流程（仅主 bot 作者）----
    if context.user_data.get("clone_flow"):
        if not _is_clone_admin(context, user.id):
            context.user_data.pop("clone_flow", None)
        elif text in ("取消", "cancel"):
            context.user_data.pop("clone_flow", None)
            await msg.reply_html("已取消克隆。")
            return
        else:
            await _handle_clone_flow(update, context, text)
            return

    # ---- 克隆管理：仅主 bot 作者 ----
    if _is_clone_admin(context, user.id):
        if text in _CLONE_TRIGGERS:
            await _start_clone_flow(update, context)
            return
        if text in ("克隆列表", "克隆名单"):
            await _handle_clone_list(update, context)
            return
        if text.startswith("删除克隆"):
            await _handle_clone_remove(update, context, text[len("删除克隆"):].strip())
            return

    # ---- 授权管理：仅作者 ----
    auth_cmd = _match_auth(text)
    if auth_cmd is not None:
        if not _is_author(context, user.id):
            return  # 非作者，静默
        await _handle_auth(update, context, grant=auth_cmd[0], arg=auth_cmd[1])
        return
    if text in ("授权列表", "授权名单"):
        if not _is_author(context, user.id):
            return
        ids, names = context.bot_data["auth_store"].snapshot()
        lines = ["📋 <b>授权名单</b>"]
        lines += [f"• id <code>{i}</code>" for i in ids]
        lines += [f"• @{_e(n)}" for n in names]
        if not ids and not names:
            lines.append("（空）")
        await msg.reply_html("\n".join(lines))
        return

    if not _is_allowed(context, user):
        return

    # ---- 余额指令（只读）----
    if text.lower() in _BALANCE_WORDS:
        try:
            data = (await _client(context).api_info()).get("data", {})
        except TrxFeeError as exc:
            await msg.reply_html(f"❌ 查询失败：{_e(exc)}")
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("查询余额异常")
            await msg.reply_html(f"❌ 查询异常：{_e(exc)}")
            return
        await msg.reply_html(
            f"余额：<code>{_e(data.get('balance'))}</code> TRX\n"
            f"充值地址：<code>{_e(context.bot_data['recharge_addr'])}</code>"
        )
        return

    # ---- 发送能量 ----
    parsed = _parse_command(msg.text)
    if not parsed:
        return  # 不符合格式 —— 静默，不打扰群聊
    count, address = parsed
    energy = _energy_for_count(count)
    await msg.reply_html(
        "⚡ <b>请确认发送能量</b>\n"
        f"笔数：<b>{count}</b> 笔（<code>{energy}</code> 能量）\n"
        f"地址：<code>{_e(address)}</code>\n"
        f"时长：<code>{ORDER_PERIOD}</code>",
        reply_markup=kb.confirm_kb(count, address),
    )


# ---------------- 回调：确认 / 取消 ----------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data or ""

    # 克隆相关：仅主 bot 作者
    if data == "clone_cancel":
        if not _is_clone_admin(context, user.id):
            return
        context.user_data.pop("clone_flow", None)
        await query.edit_message_text("✖️ 已取消克隆。")
        return
    if data == "clone_confirm":
        if not _is_clone_admin(context, user.id):
            return
        await _submit_clone(query, context)
        return

    # 发送/取消：仅作者/授权
    if not _is_allowed(context, user):
        return

    if data == "cancel":
        await query.edit_message_text("✖️ 已取消。")
        return

    if not data.startswith("send:"):
        return
    try:
        _, count_str, address = data.split(":", 2)
        count = int(count_str)
    except (ValueError, IndexError):
        await query.edit_message_text("⚠️ 指令解析失败。")
        return

    energy = _energy_for_count(count)
    out_trade_no = f"EB{int(time.time())}"
    await query.edit_message_text(
        f"⏳ 正在给 <code>{_e(address)}</code> 发送 {count} 笔（{energy} 能量）…",
        parse_mode=ParseMode.HTML,
    )

    try:
        await _client(context).create_order(
            energy_amount=energy,
            receive_address=address,
            period=ORDER_PERIOD,
            out_trade_no=out_trade_no,
            auto_activation=True,
        )
    except TrxFeeError as exc:
        await query.edit_message_text(
            f"❌ <b>发送失败</b>\n地址：<code>{_e(address)}</code>\n原因：{_e(exc)}",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("下单异常")
        await query.edit_message_text(
            f"❌ <b>发送异常</b>\n地址：<code>{_e(address)}</code>\n{_e(exc)}",
            parse_mode=ParseMode.HTML,
        )
        return

    await query.edit_message_text(
        "✅ <b>发送成功，有效期60分钟。请尽快使用。</b>\n"
        f"笔数：{count} 笔（{energy} 能量）\n"
        f"地址：<code>{_e(address)}</code>",
        parse_mode=ParseMode.HTML,
    )
