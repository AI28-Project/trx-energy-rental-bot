"""trxfee.io 能量 API 客户端。

签名规则（与官方文档一致）：
  1. 请求体按 key 字母序排序，序列化为无空格 JSON（separators=(",", ":")）。
  2. message = f"{timestamp}&{json_data}"，timestamp 为 10 位秒级时间戳。
  3. SIGNATURE = HMAC-SHA256(API_SECRET, message).hexdigest()。
  4. 请求头携带 API-KEY / TIMESTAMP / SIGNATURE。
GET 请求无需签名，仅需 API-KEY。

注意：签名用的 json 串必须与实际发送的 body 完全一致，因此 POST 时直接
发送排序后的字符串（content=），不能交给 httpx 重新序列化。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx


class TrxFeeError(Exception):
    """API 返回业务错误时抛出。"""

    def __init__(self, message: str, payload: Any = None):
        super().__init__(message)
        self.payload = payload


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class TrxFeeClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str, timeout: float = 30.0):
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._ua = _DEFAULT_UA

    # ---- 内部工具 ----
    def _sign(self, body: dict[str, Any]) -> tuple[str, dict[str, str]]:
        json_data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        timestamp = str(int(time.time()))
        message = f"{timestamp}&{json_data}"
        signature = hmac.new(self._api_secret, message.encode(), hashlib.sha256).hexdigest()
        headers = {
            "API-KEY": self._api_key,
            "TIMESTAMP": timestamp,
            "SIGNATURE": signature,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self._ua,
        }
        return json_data, headers

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                params=params,
                headers={
                    "API-KEY": self._api_key,
                    "Accept": "application/json",
                    "User-Agent": self._ua,
                },
            )
        return self._parse(resp)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        json_data, headers = self._sign(body)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}{path}",
                content=json_data.encode(),
                headers=headers,
            )
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> dict[str, Any]:
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype.lower():
            body = resp.text
            if resp.headers.get("server", "").lower() == "cloudflare" or "cloudflare" in body.lower():
                ray = resp.headers.get("cf-ray", "")
                raise TrxFeeError(
                    f"请求被 Cloudflare 拦截（HTTP {resp.status_code}，出口 IP 不在白名单 / 被风控）。"
                    f"请在部署服务器上运行，或联系 trxfee 放行服务器 IP。cf-ray={ray}"
                )
            raise TrxFeeError(f"HTTP {resp.status_code}：响应非 JSON：{body[:200]}")
        try:
            data = resp.json()
        except Exception:
            raise TrxFeeError(f"HTTP {resp.status_code}：响应解析失败：{resp.text[:200]}")

        if not isinstance(data, dict):
            raise TrxFeeError("响应格式异常", data)

        # 下单类接口用 error 字段（0 成功）；查询类用 code 字段（200 成功）。
        if "error" in data and data.get("error") not in (0, "0", None):
            raise TrxFeeError(data.get("msg") or f"下单失败(error={data['error']})", data)
        if "code" in data and data.get("code") not in (200, "200", None):
            raise TrxFeeError(data.get("msg") or f"请求失败(code={data['code']})", data)
        if resp.status_code >= 400 and "error" not in data and "code" not in data:
            raise TrxFeeError(data.get("msg") or f"HTTP {resp.status_code}", data)
        return data

    # ---- 查询类（GET）----
    async def account(self) -> dict[str, Any]:
        return await self._get("/account")

    async def api_info(self) -> dict[str, Any]:
        return await self._get("/apiInfo")

    async def estimate(self, energy: int) -> dict[str, Any]:
        return await self._get("/estimate", {"energy": energy})

    async def order_info(self, orders_num: str) -> dict[str, Any]:
        return await self._get(f"/order/{orders_num}")

    async def times_order_price(self) -> dict[str, Any]:
        return await self._get("/timesOrderPrice")

    async def times_order_info(self, address: str) -> dict[str, Any]:
        return await self._get(f"/timesOrder/{address}")

    # ---- 操作类（POST，需签名）----
    async def create_order(
        self,
        energy_amount: int,
        receive_address: str,
        *,
        period: str = "1H",
        out_trade_no: str = "",
        callback_url: str = "",
        auto_activation: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "energy_amount": energy_amount,
            "period": period,
            "receive_address": receive_address,
            "auto_activation": auto_activation,
        }
        if out_trade_no:
            body["out_trade_no"] = out_trade_no
        if callback_url:
            body["callback_url"] = callback_url
        return await self._post("/api", body)

    async def activate(self, receive_address: str) -> dict[str, Any]:
        return await self._post("/activation", {"receive_address": receive_address})

    async def create_times_order(
        self,
        rent_times: int,
        recv_addr: str,
        *,
        free_pause: int | None = None,
        resource_replenish: str = "0",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "rentTimes": rent_times,
            "recvAddr": recv_addr,
            "resourceReplenish": resource_replenish,
        }
        if free_pause is not None:
            body["freePause"] = free_pause
        return await self._post("/timesOrder", body)

    async def toggle_times_order(self, recv_addr: str) -> dict[str, Any]:
        return await self._post("/enableTimesOrder", {"recvAddr": recv_addr})

    async def edit_times_rent_times(self, recv_addr: str, rent_times: int) -> dict[str, Any]:
        return await self._post(
            "/editTimesOrderRentTimes",
            {"recvAddr": recv_addr, "rentTimes": rent_times},
        )
