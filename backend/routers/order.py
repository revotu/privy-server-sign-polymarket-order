"""
订单路由 / Order Router
========================
处理 Polymarket 下单相关的 API 端点。
Handles Polymarket order-related API endpoints.

端点 / Endpoints:
    GET  /api/markets/{condition_id}       获取市场信息
    POST /api/bind-signer                  首次 onboarding：将服务端 Key Quorum 绑定到用户钱包（需要 user JWT）
    POST /api/derive-clob-credentials      派生 CLOB API 凭据（首次需要）
    POST /api/place-order                  服务端签名并提交订单（核心功能，无弹窗）

核心流程 / Core Flow (place-order):
    1. 获取市场信息（token_id, tick_size, neg_risk）
    2. 从 CLOB API 获取当前手续费率
    3. 构建 EIP-712 订单结构（不含签名）
    4. 调用 Privy API 用用户 wallet 签名（服务端授权密钥，无需用户参与）
    5. 组装 SignedOrder 并提交到 Polymarket CLOB
    6. 返回订单 ID
"""

import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from polymarket.clob_auth import build_clob_auth_typed_data, derive_api_credentials
from polymarket.clob_client import ClobApiClient
from polymarket.order_builder import (
    build_eip712_typed_data,
    build_order_message,
    build_signed_order_payload,
)
from privy.client import privy_client

router = APIRouter(prefix="/api", tags=["order"])


# ============================================================
# 请求/响应模型 / Request / Response Models
# ============================================================

class DeriveCredentialsRequest(BaseModel):
    """派生 CLOB API 凭据的请求体 / Request body for deriving CLOB API credentials"""

    # 用户的 Privy wallet ID / User's Privy wallet ID
    wallet_id: str

    # 用户的钱包地址（EOA）/ User's wallet address (EOA)
    wallet_address: str

    # 用户的 Privy access token（JWT）
    # 在派生 CLOB 凭据时需要用钱包签名认证 EIP-712 消息
    # User's Privy JWT; needed to sign EIP-712 auth message via wallet
    user_jwt: str


class DeriveCredentialsResponse(BaseModel):
    """派生 CLOB API 凭据的响应体 / Response body for CLOB API credentials"""

    success: bool
    api_key: str
    # Demo 模式返回 secret 供前端存储；生产环境应存储在服务端数据库，不返回给前端
    # Demo returns secret for frontend storage; production should store server-side, not return to frontend
    api_secret: str = ""
    api_passphrase: str = ""
    message: str


class PlaceOrderRequest(BaseModel):
    """下单请求体 / Order placement request body"""

    # 用户的 Privy wallet ID（用于 Privy 签名调用）
    # User's Privy wallet ID (for Privy signing call)
    wallet_id: str

    # 用户的钱包地址（作为订单 maker/signer）
    # User's wallet address (as order maker/signer)
    wallet_address: str

    # 市场 condition ID（32 字节十六进制）
    # Market condition ID (32-byte hex)
    condition_id: str

    # 订单方向：BUY 买入 YES/NO token，SELL 卖出
    # Order side: BUY to buy YES/NO token, SELL to sell
    side: Literal["BUY", "SELL"]

    # 订单价格（0.01 ~ 0.99，精度由市场 tick_size 决定）
    # Order price (0.01 ~ 0.99, precision determined by market tick_size)
    price: float = Field(..., gt=0, lt=1)

    # 订单数量（outcome token 数量，精度由市场 tick_size 决定）
    # Order size (outcome token quantity, precision by market tick_size)
    size: float = Field(..., gt=0)

    # CLOB API Key（派生后存储在客户端或由前端传入）
    # CLOB API Key (stored after derivation, passed from client or server)
    clob_api_key: str

    # CLOB API Secret / CLOB API Secret
    clob_api_secret: str

    # CLOB API Passphrase / CLOB API Passphrase
    clob_api_passphrase: str

    # 是否为多结果市场（影响合约地址选择）
    # Whether it's a multi-outcome market (affects contract address selection)
    neg_risk: bool = False

    # 订单类型：GTC（挂单直到成交）、FOK（立即成交否则取消）等
    # Order type: GTC (rest until filled), FOK (immediate all-or-nothing), etc.
    order_type: Literal["GTC", "GTD", "FOK", "FAK"] = "GTC"


class PlaceOrderResponse(BaseModel):
    """下单响应体 / Order placement response body"""

    success: bool

    # Polymarket 订单 ID / Polymarket order ID
    order_id: str = ""

    # 订单状态 / Order status
    status: str = ""

    # 错误信息（如有）/ Error message (if any)
    error_message: str = ""

    # 使用的签名（调试用）/ Signature used (for debugging)
    signature: str = ""


class BindSignerRequest(BaseModel):
    """绑定服务端 signer 的请求体 / Request body for binding server signer"""

    # 用户的 Privy wallet ID / User's Privy wallet ID
    wallet_id: str

    # 用户的 Privy access token（JWT，从 Flutter SDK 获取）
    # User's Privy access token (JWT, obtained from Flutter SDK)
    user_jwt: str


class BindSignerResponse(BaseModel):
    """绑定服务端 signer 的响应体 / Response body for binding server signer"""

    success: bool

    # 绑定的 Key Quorum ID / Bound Key Quorum ID
    key_quorum_id: str = ""

    # 提示信息 / Info message
    message: str = ""


# ============================================================
# 路由处理器 / Route Handlers
# ============================================================

@router.post("/bind-signer", response_model=BindSignerResponse)
async def bind_signer(request: BindSignerRequest):
    """
    将服务端 Key Quorum 绑定到用户钱包（首次 onboarding 时调用一次）。
    Binds server Key Quorum to user wallet (call once during first-time onboarding).

    绑定后服务端即可无弹窗代替用户签名（sign_typed_data）。
    After binding, the server can sign on behalf of the user without popups.

    ⚠️  前置条件 / Prerequisite:
        此接口依赖 Privy 为你的 App 开通「通过 user JWT 执行 wallet 写操作」的权限。
        默认情况下该权限关闭，调用会返回：
            {"error": "Invalid JWT token provided", "code": "invalid_data"}
        需联系 Privy 支持团队申请开通后才能正常使用。

        This endpoint requires Privy to enable "wallet write operations via user JWT" for your app.
        By default this is disabled, and calls will return:
            {"error": "Invalid JWT token provided", "code": "invalid_data"}
        Contact Privy support to request access before using this endpoint.

    流程 / Flow:
        1. 前端（Flutter SDK）获取 user access token（JWT）
        2. 前端将 wallet_id + user_jwt 传给此接口
        3. 后端调用 /v1/wallets/authenticate 将 user_jwt 换成 authorization_key
        4. 后端用 authorization_key 调用 Privy PATCH /wallets/{wallet_id} 添加 signer
        5. 后续所有签名操作无需再传 user_jwt
    """
    try:
        from config import settings
        result = privy_client.add_signer_to_wallet(
            wallet_id=request.wallet_id,
            key_quorum_id=settings.privy_key_quorum_id,
            user_jwt=request.user_jwt,
        )
        return BindSignerResponse(
            success=True,
            key_quorum_id=settings.privy_key_quorum_id,
            message="signer 绑定成功，后续签名无需用户参与 / Signer bound, future signing needs no user interaction",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"绑定 signer 失败 / Failed to bind signer: {e.response.text}",
        )


@router.get("/markets/{condition_id}")
async def get_market(condition_id: str):
    """
    获取 Polymarket 市场信息（公开接口）。
    Gets Polymarket market information (public endpoint).

    返回包含 token_id, tick_size, neg_risk 等下单所需信息。
    Returns token_id, tick_size, neg_risk, and other info needed for ordering.

    Args:
        condition_id: 市场条件 ID / Market condition ID
    """
    clob = ClobApiClient()
    try:
        market = clob.get_market(condition_id)
        return market
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"获取市场信息失败 / Failed to get market: {e.response.text}",
        )


@router.post("/derive-clob-credentials", response_model=DeriveCredentialsResponse)
async def derive_clob_credentials(request: DeriveCredentialsRequest):
    """
    派生用户的 Polymarket CLOB API 凭据（首次使用时调用一次）。
    Derives user's Polymarket CLOB API credentials (call once on first use).

    流程 / Flow:
        1. 构建 ClobAuth EIP-712 消息
        2. 通过 Privy API 用用户 wallet 签名（无弹窗，已绑定 signer）
        3. 用签名调用 CLOB API 派生 API Key/Secret/Passphrase
        4. 返回凭据（生产环境应加密存储在服务端，不返回 secret 给前端）

    前提 / Prerequisite:
        用户 wallet 必须已通过 /api/bind-signer 绑定服务端 Key Quorum。
        User wallet must have server Key Quorum bound via /api/bind-signer.
    """
    timestamp = str(int(time.time()))

    # 1. 构建 CLOB 认证用的 EIP-712 数据
    # 1. Build EIP-712 data for CLOB authentication
    clob_auth_typed_data = build_clob_auth_typed_data(
        wallet_address=request.wallet_address,
        timestamp=timestamp,
    )

    try:
        # 2. 通过 Privy 服务端签名（无弹窗！）
        # 2. Sign via Privy server side (no popup!)
        signature = privy_client.sign_typed_data(
            wallet_id=request.wallet_id,
            typed_data=clob_auth_typed_data,
        )

        # 3. 派生 CLOB API 凭据
        # 3. Derive CLOB API credentials
        credentials = derive_api_credentials(
            wallet_address=request.wallet_address,
            auth_signature=signature,
            timestamp=timestamp,
        )

        # 生产环境：将凭据加密存储在服务端数据库，不返回 secret 给前端
        # Production: store credentials encrypted in server DB, don't return secret to frontend
        # Demo：直接返回，方便测试 / Demo: return directly for testing convenience
        return DeriveCredentialsResponse(
            success=True,
            api_key=credentials["api_key"],
            api_secret=credentials["api_secret"],
            api_passphrase=credentials["api_passphrase"],
            message=(
                f"CLOB API 凭据派生成功（api_key: {credentials['api_key'][:8]}...）/ "
                f"CLOB credentials derived successfully (api_key: {credentials['api_key'][:8]}...)"
            ),
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"派生 CLOB 凭据失败 / Failed to derive CLOB credentials: {e.response.text}",
        )


@router.post("/place-order", response_model=PlaceOrderResponse)
async def place_order(request: PlaceOrderRequest):
    """
    ★ 核心功能：服务端全程签名并提交 Polymarket 订单，全程无需用户弹窗确认。
    ★ Core Feature: Server-side signing and submission of Polymarket order, no user popup needed.

    完整流程 / Complete Flow:
        1. 获取市场信息，确认 token_id 和 neg_risk
        2. 动态获取当前手续费率（不能硬编码！）
        3. 构建 EIP-712 订单结构（包含所有字段）
        4. 调用 Privy API 用 P256 授权密钥签名（无弹窗！）
        5. 组装 SignedOrder（订单数据 + 签名）
        6. 提交到 Polymarket CLOB API
        7. 返回订单 ID 和状态

    前提条件 / Prerequisites:
        - 用户 wallet 已通过 /api/bind-signer 绑定服务端 Key Quorum
        - 用户已通过 /api/derive-clob-credentials 获取 CLOB API 凭据
        - 用户 wallet 中有足够的 USDC.e（Polygon 主网）

    安全说明 / Security Notes:
        - 服务端用 P256 私钥签名 Privy API 请求（privy-authorization-signature header）
        - Privy 在 TEE（可信执行环境）中用用户私钥签名 EIP-712 数据
        - 整个过程不涉及用户交互，也不暴露用户私钥

    前端调用示例 / Frontend call example:
        POST /api/place-order
        {
            "wallet_id": "wallet_abc123",
            "wallet_address": "0x1234...",
            "condition_id": "0xabcd...",
            "side": "BUY",
            "price": 0.6,
            "size": 10.0,
            "clob_api_key": "...",
            "clob_api_secret": "...",
            "clob_api_passphrase": "...",
            "order_type": "GTC"
        }
    """
    clob = ClobApiClient(
        api_key=request.clob_api_key,
        api_secret=request.clob_api_secret,
        api_passphrase=request.clob_api_passphrase,
    )

    try:
        # 步骤 1: 获取市场信息
        # Step 1: Get market information
        market = clob.get_market(request.condition_id)

        # 从市场信息中获取对应方向的 token_id
        # Get token_id for the requested side from market info
        tokens = market.get("tokens", [])
        if not tokens:
            raise HTTPException(status_code=400, detail="市场没有 token 信息 / Market has no token info")

        # Polymarket 市场通常有两个 token：outcome 0 (YES) 和 outcome 1 (NO)
        # BUY YES: 使用 outcome=0 的 token / BUY NO: 使用 outcome=1 的 token
        # Polymarket markets typically have two tokens: outcome 0 (YES) and outcome 1 (NO)
        # 实际应由前端传入具体的 token_id / In practice, frontend should pass specific token_id
        token_id = tokens[0].get("token_id", "")
        neg_risk = market.get("neg_risk", False)

        # 步骤 2: 获取当前手续费率（动态获取，不能硬编码）
        # Step 2: Get current fee rate (dynamic, must not hardcode)
        fee_rate_bps = clob.get_fee_rate(token_id)

        # 步骤 3: 构建订单 message
        # Step 3: Build order message
        order_message = build_order_message(
            maker_address=request.wallet_address,
            token_id=token_id,
            side=request.side,
            price=request.price,
            size=request.size,
            fee_rate_bps=fee_rate_bps,
        )

        # 步骤 4: 包装成完整的 EIP-712 结构化数据
        # Step 4: Wrap into complete EIP-712 structured data
        typed_data = build_eip712_typed_data(order_message, neg_risk=neg_risk)

        # 步骤 5: 通过 Privy 服务端签名（★ 核心：无弹窗！）
        # Step 5: Sign via Privy server side (★ Key: no popup!)
        # 服务端 P256 私钥授权 → Privy TEE 中用用户私钥签名 EIP-712
        # Server P256 key authorizes → Privy TEE signs EIP-712 with user's private key
        signature = privy_client.sign_typed_data(
            wallet_id=request.wallet_id,
            typed_data=typed_data,
        )

        # 步骤 6: 组装 SignedOrder（订单数据 + 签名）
        # Step 6: Assemble SignedOrder (order data + signature)
        signed_order = build_signed_order_payload(order_message, signature)

        # 步骤 7: 提交到 Polymarket CLOB
        # Step 7: Submit to Polymarket CLOB
        result = clob.submit_order(signed_order, order_type=request.order_type, wallet_address=request.wallet_address)

        return PlaceOrderResponse(
            success=result.get("success", False),
            order_id=result.get("orderID", ""),
            status=result.get("status", ""),
            error_message=result.get("errorMsg", ""),
            signature=signature[:20] + "..." if signature else "",  # 只返回前 20 字符供调试 / Only first 20 chars for debug
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"下单失败 / Order placement failed: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"内部错误 / Internal error: {str(e)}",
        )
