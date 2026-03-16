"""
订单路由 / Order Router
========================
处理 Polymarket 下单相关的 API 端点。
Handles Polymarket order-related API endpoints.

端点 / Endpoints:
    GET  /api/markets/{condition_id}       获取市场信息
    POST /api/derive-clob-credentials      派生 CLOB API 凭据（首次需要）
    POST /api/place-order                  EOA 方案：服务端签名并提交订单（无弹窗）
    POST /api/get-safe-address             计算用户 Safe 地址（纯本地 CREATE2 计算，无链上操作）
    POST /api/setup-safe                   首次 onboarding：无 gas 部署 Safe + 授权 USDC
    POST /api/place-order-builder          Builder 方案：maker=Safe，服务端签名（无弹窗）

核心流程 / Core Flow (place-order-builder):
    1. 获取市场信息（token_id, tick_size, neg_risk）
    2. 从 CLOB API 获取当前手续费率
    3. 构建 EIP-712 订单结构（maker=Safe, signer=EOA, signatureType=2）
    4. 调用 Privy API 用 EOA wallet 签名（服务端授权密钥，无需用户参与）
    5. 组装 SignedOrder 并携带 Builder 头提交到 Polymarket CLOB
    6. 返回订单 ID
"""

import json
import time
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings

from polymarket.builder_auth import build_builder_headers
from polymarket.clob_auth import build_clob_auth_typed_data, derive_api_credentials
from polymarket.clob_client import ClobApiClient
from polymarket.order_builder import (
    SIG_TYPE_GNOSIS_SAFE,
    build_eip712_typed_data,
    build_order_message,
    build_signed_order_payload,
)
from polymarket.relayer_client import compute_safe_tx_hash, relayer_client, split_and_pack_sig
from polymarket.safe_wallet import (
    build_safe_approve_usdc_tx_data,
    derive_safe_address,
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


# ============================================================
# 路由处理器 / Route Handlers
# ============================================================

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


# ============================================================
# Builder / Safe 方案请求响应模型 / Builder / Safe Request & Response Models
# ============================================================

class GetSafeAddressRequest(BaseModel):
    """查询用户 Safe 地址请求体 / Request body for getting user Safe address"""

    # 用户的 EOA 地址（Privy wallet 地址）/ User's EOA address (Privy wallet address)
    wallet_address: str


class GetSafeAddressResponse(BaseModel):
    """查询用户 Safe 地址响应体 / Response body for Safe address"""

    # 计算得到的 Safe 地址 / Computed Safe address
    safe_address: str

    # EOA 地址（Safe owner）/ EOA address (Safe owner)
    eoa_address: str


class SetupSafeRequest(BaseModel):
    """首次 Safe onboarding 请求体 / Request body for first-time Safe onboarding"""

    # Privy wallet ID（用于签名）/ Privy wallet ID (for signing)
    wallet_id: str

    # 用户 EOA 地址 / User EOA address
    wallet_address: str

    # 是否等待交易确认（部署和授权）/ Whether to wait for transaction confirmations
    wait_for_confirmation: bool = True


class SetupSafeResponse(BaseModel):
    """Safe onboarding 响应体 / Safe onboarding response body"""

    success: bool

    # Safe 地址 / Safe address
    safe_address: str

    # Safe 部署交易哈希 / Safe deploy tx hash
    deploy_tx_hash: str = ""

    # USDC approve 交易哈希列表（3 个合约）/ USDC approve tx hashes (3 contracts)
    approve_tx_hashes: list[str] = []

    # 消息 / Message
    message: str = ""


class PlaceOrderBuilderRequest(BaseModel):
    """Builder 方案下单请求体 / Builder scheme order placement request body"""

    # Privy wallet ID（用于 Privy 签名调用）/ Privy wallet ID (for Privy signing)
    wallet_id: str

    # 用户 EOA 地址（签名者，Safe 的 owner）/ User EOA address (signer, Safe owner)
    wallet_address: str

    # Safe 地址（订单 maker）/ Safe address (order maker)
    safe_address: str

    # 市场 condition ID / Market condition ID
    condition_id: str

    # 订单方向 / Order side
    side: Literal["BUY", "SELL"]

    # 订单价格 / Order price
    price: float = Field(..., gt=0, lt=1)

    # 订单数量 / Order size
    size: float = Field(..., gt=0)

    # CLOB API Key（L2 认证）/ CLOB API Key (L2 auth)
    clob_api_key: str

    # CLOB API Secret / CLOB API Secret
    clob_api_secret: str

    # CLOB API Passphrase / CLOB API Passphrase
    clob_api_passphrase: str

    # 是否为多结果市场 / Whether multi-outcome market
    neg_risk: bool = False

    # 订单类型 / Order type
    order_type: Literal["GTC", "GTD", "FOK", "FAK"] = "GTC"


# ============================================================
# Builder / Safe 方案端点 / Builder / Safe Endpoints
# ============================================================

@router.post("/get-safe-address", response_model=GetSafeAddressResponse)
async def get_safe_address(request: GetSafeAddressRequest):
    """
    计算用户的 Gnosis Safe 地址（纯本地计算，无链上操作）。
    Computes user's Gnosis Safe address (pure local computation, no chain operation).

    使用 CREATE2 确定性算法，给定相同的 EOA 地址和 salt_nonce，
    每次计算结果相同，且与实际部署的 Safe 地址一致。
    Uses CREATE2 deterministic algorithm — given the same EOA and salt_nonce,
    result is always identical and matches the actual deployed Safe address.

    Args:
        wallet_address: 用户 EOA 地址 / User EOA address
        salt_nonce: CREATE2 salt nonce（通常为 0）/ CREATE2 salt nonce (usually 0)
    """
    try:
        safe_addr = derive_safe_address(eoa_address=request.wallet_address)
        return GetSafeAddressResponse(
            safe_address=safe_addr,
            eoa_address=request.wallet_address,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Safe 地址计算失败 / Failed to compute Safe address: {str(e)}",
        )


@router.post("/setup-safe", response_model=SetupSafeResponse)
async def setup_safe(request: SetupSafeRequest):
    """
    首次 Safe onboarding：无 gas 部署 Gnosis Safe + 授权 USDC 给 3 个合约。
    First-time Safe onboarding: gasless deploy Gnosis Safe + approve USDC for 3 contracts.

    完整流程 / Complete Flow:
        1. 派生 Safe 地址（CREATE2 确定性计算）
        2. 构建部署 Safe 的交易数据（createProxyWithNonce calldata）
        3. 通过 Privy 服务端签名部署授权（EOA 对 Safe 部署 EIP-712 数据签名）
        4. 提交 Relayer 部署 Safe（无 gas）
        5. 等待 Safe 部署确认
        6. 依次对 3 个合约授权 USDC MAX_UINT256（nonce 递增，每次确认后再下一个）：
           a. CTF Exchange（标准市场所需）
           b. NegRisk CTF Exchange（多结果市场所需）
           c. NegRisk Adapter（CLOB 验证 neg_risk 余额时同时检查此地址）

    ★ 为何需要 3 个授权 / Why 3 approvals:
        CLOB 的 /balance-allowance 端点对 signatureType=2 同时检查这 3 个地址的 allowance，
        任意一个为 0 都会导致下单时返回 "not enough balance / allowance"。
        CLOB's /balance-allowance checks all 3 addresses for signatureType=2;
        any zero allowance causes "not enough balance / allowance" when placing orders.

    前提 / Prerequisites:
        - 用户 wallet 已通过 /api/bind-signer 绑定服务端 Key Quorum
        - 已配置 Builder API 凭据（POLYMARKET_BUILDER_API_KEY 等）

    注意 / Note:
        此端点只需调用一次（首次 onboarding），之后使用 /api/place-order-builder 下单。
        This endpoint only needs to be called once (first-time onboarding),
        then use /api/place-order-builder for orders.
    """
    try:
        # 步骤 1: 派生 Safe 地址（纯本地 CREATE2 计算）
        # Step 1: Derive Safe address (pure local CREATE2 computation)
        safe_addr = derive_safe_address(eoa_address=request.wallet_address)

        # 步骤 2: 构建 CreateProxy EIP-712 数据并通过 Privy 签名
        # Step 2: Build CreateProxy EIP-712 data and sign via Privy
        # EOA 签名 CreateProxy typed data 以授权 Relayer 代为部署 Safe
        # EOA signs CreateProxy typed data to authorize Relayer to deploy Safe
        deploy_typed_data = relayer_client.build_safe_create_typed_data()

        deploy_signature = privy_client.sign_typed_data(
            wallet_id=request.wallet_id,
            typed_data=deploy_typed_data,
        )

        # 步骤 3: 提交 Relayer 部署 Safe（type="SAFE-CREATE"）
        # Step 3: Submit to Relayer to deploy Safe (type="SAFE-CREATE")
        deploy_result = relayer_client.deploy_safe(
            eoa_address=request.wallet_address,
            safe_address=safe_addr,
            signature=deploy_signature,
        )
        deploy_tx_id = deploy_result.get("transactionID", "")
        deploy_tx_hash = deploy_result.get("transactionHash", deploy_tx_id)

        # 步骤 4: 等待 Safe 部署确认
        # Step 4: Wait for Safe deployment confirmation
        if request.wait_for_confirmation and deploy_tx_id:
            relayer_client.wait_for_tx(deploy_tx_id)

        # 步骤 5: 依次对 3 个合约授权 USDC MAX_UINT256
        # Step 5: Approve USDC MAX_UINT256 to all 3 required contracts sequentially
        # ★ CLOB 验证余额时同时检查这 3 个地址的 allowance，任意为 0 都会导致下单失败
        # ★ CLOB checks allowance for all 3 addresses; any zero causes order rejection
        approve_spenders = [
            settings.polymarket_ctf_exchange_address,          # CTF Exchange（标准市场）
            settings.polymarket_neg_risk_ctf_exchange_address,  # NegRisk CTF Exchange（多结果市场）
            settings.polymarket_neg_risk_adapter_address,       # NegRisk Adapter（CLOB 额外检查）
        ]

        approve_tx_hashes = []
        for spender in approve_spenders:
            # 每次重新获取 nonce（前一笔确认后 nonce +1）
            # Re-fetch nonce each time (increments after each confirmed tx)
            safe_nonce = relayer_client.get_safe_nonce(request.wallet_address)
            approve_tx = build_safe_approve_usdc_tx_data(spender_address=spender)

            safe_tx_hash = compute_safe_tx_hash(
                safe_address=safe_addr,
                to=approve_tx["to"],
                data=approve_tx["data"],
                nonce=int(safe_nonce),
            )
            raw_signature = privy_client.sign_message(
                wallet_id=request.wallet_id,
                message_hash=safe_tx_hash,
            )
            approve_signature = split_and_pack_sig(raw_signature)

            approve_result = relayer_client.execute_safe_transaction(
                eoa_address=request.wallet_address,
                safe_address=safe_addr,
                to=approve_tx["to"],
                data=approve_tx["data"],
                signature=approve_signature,
                nonce=safe_nonce,
            )
            approve_tx_id = approve_result.get("transactionID", "")
            approve_tx_hashes.append(approve_result.get("transactionHash", approve_tx_id))

            if request.wait_for_confirmation and approve_tx_id:
                relayer_client.wait_for_tx(approve_tx_id)

        return SetupSafeResponse(
            success=True,
            safe_address=safe_addr,
            deploy_tx_hash=deploy_tx_hash,
            approve_tx_hashes=approve_tx_hashes,
            message=(
                f"Safe 部署并授权成功！Safe 地址：{safe_addr} / "
                f"Safe deployed and approved successfully! Safe address: {safe_addr}"
            ),
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Safe 部署失败 / Safe setup failed: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Safe 部署内部错误 / Safe setup internal error: {str(e)}",
        )


@router.post("/place-order-builder", response_model=PlaceOrderResponse)
async def place_order_builder(request: PlaceOrderBuilderRequest):
    """
    ★ Builder 方案：maker=Safe，服务端 EOA 签名，携带 Builder 头提交订单。
    ★ Builder Scheme: maker=Safe, server-side EOA signing, submit with Builder headers.

    与 EOA 方案 (/api/place-order) 的差异 / Differences from EOA scheme:
        - maker = Safe 地址（资金来自 Safe）/ maker = Safe address (funds from Safe)
        - signer = 用户 EOA（Safe 的 owner，实际签名者）/ signer = user EOA (Safe owner, actual signer)
        - signatureType = 2（POLY_GNOSIS_SAFE）
        - 请求头额外携带 POLY_BUILDER_* 四个头
          Request headers additionally carry 4 POLY_BUILDER_* headers

    完整流程 / Complete Flow:
        1. 获取市场信息，确认 token_id 和 neg_risk
        2. 动态获取当前手续费率
        3. 构建 EIP-712 订单结构（maker=Safe, signer=EOA, signatureType=2）
        4. 调用 Privy API 用 EOA wallet 签名（无弹窗！）
        5. 生成 Builder 认证头（POLY_BUILDER_*）
        6. 组装 SignedOrder + L2 头 + Builder 头 提交到 Polymarket CLOB
        7. 返回订单 ID 和状态

    前提条件 / Prerequisites:
        - 用户 wallet 已通过 /api/bind-signer 绑定服务端 Key Quorum
        - 用户已通过 /api/derive-clob-credentials 获取 CLOB API 凭据
        - 用户 Safe 已通过 /api/setup-safe 部署并授权 USDC
        - Safe 中有足够的 USDC.e（Polygon 主网）
        - 已配置 Builder API 凭据（POLYMARKET_BUILDER_API_KEY 等）
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

        tokens = market.get("tokens", [])
        if not tokens:
            raise HTTPException(status_code=400, detail="市场没有 token 信息 / Market has no token info")

        token_id = tokens[0].get("token_id", "")
        neg_risk = market.get("neg_risk", False)

        # 步骤 2: 获取当前手续费率
        # Step 2: Get current fee rate
        fee_rate_bps = clob.get_fee_rate(token_id)

        # 步骤 3: 构建订单 message（maker=Safe, signer=EOA, signatureType=2）
        # Step 3: Build order message (maker=Safe, signer=EOA, signatureType=2)
        order_message = build_order_message(
            maker_address=request.safe_address,       # ★ maker = Safe 地址 / Safe address
            signer_address=request.wallet_address,    # ★ signer = EOA（Safe owner）
            token_id=token_id,
            side=request.side,
            price=request.price,
            size=request.size,
            fee_rate_bps=fee_rate_bps,
            signature_type=SIG_TYPE_GNOSIS_SAFE,      # ★ signatureType=2
        )

        # 步骤 4: 包装成完整的 EIP-712 结构化数据
        # Step 4: Wrap into complete EIP-712 structured data
        typed_data = build_eip712_typed_data(order_message, neg_risk=neg_risk)

        # 步骤 5: 通过 Privy 服务端签名（★ 用 EOA wallet_id，无弹窗！）
        # Step 5: Sign via Privy server side (★ using EOA wallet_id, no popup!)
        signature = privy_client.sign_typed_data(
            wallet_id=request.wallet_id,
            typed_data=typed_data,
        )

        # 步骤 6: 组装 SignedOrder
        # Step 6: Assemble SignedOrder
        signed_order = build_signed_order_payload(order_message, signature)

        # 步骤 7: 生成 Builder 认证头
        # Step 7: Generate Builder auth headers
        body_preview = json.dumps(
            {"order": signed_order, "owner": request.clob_api_key,
             "orderType": request.order_type, "postOnly": False},
            separators=(",", ":"),
        )
        builder_hdrs = build_builder_headers(
            method="POST",
            path="/order",
            body=body_preview,
        )

        # 步骤 8: 提交到 Polymarket CLOB（L2 头 + Builder 头）
        # Step 8: Submit to Polymarket CLOB (L2 headers + Builder headers)
        result = clob.submit_order(
            signed_order,
            order_type=request.order_type,
            wallet_address=request.wallet_address,
            builder_headers=builder_hdrs,
        )

        return PlaceOrderResponse(
            success=result.get("success", False),
            order_id=result.get("orderID", ""),
            status=result.get("status", ""),
            error_message=result.get("errorMsg", ""),
            signature=signature[:20] + "..." if signature else "",
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Builder 下单失败 / Builder order placement failed: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"内部错误 / Internal error: {str(e)}",
        )
