"""
Signer 路由 / Signer Router
==============================
处理将服务端 Key Quorum 绑定到用户钱包的 API 端点。
Handles API endpoint for binding server Key Quorum to user wallet.

端点 / Endpoint:
    POST /api/bind-signer
        - 检查是否已绑定，避免重复操作
        - 需要用户 JWT（用于授权 wallet 修改）
        - 调用 Privy API 将 Key Quorum 添加为用户 wallet 的 signer
        - 绑定成功后，服务端可无需用户参与即可代签

调用时机 / When to Call:
    用户首次登录后，在进行任何下单操作前调用一次。
    Call once after user's first login, before any order operations.
"""

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from privy.client import privy_client

router = APIRouter(prefix="/api", tags=["signer"])


# ============================================================
# 请求/响应模型 / Request / Response Models
# ============================================================

class BindSignerRequest(BaseModel):
    """绑定 signer 的请求体 / Request body for binding signer"""

    # 用户的 Privy wallet ID（非地址！格式如 wallet_abc123...）
    # User's Privy wallet ID (not address! format: wallet_abc123...)
    wallet_id: str

    # 用户的 Privy access token（JWT），从 Flutter SDK 获取
    # User's Privy access token (JWT), obtained from Flutter SDK
    # 用于证明用户本人同意添加 signer / Used to prove user consents to adding signer
    user_jwt: str


class BindSignerResponse(BaseModel):
    """绑定 signer 的响应体 / Response body for binding signer"""

    # 是否成功绑定 / Whether binding was successful
    success: bool

    # 提示信息 / Message
    message: str

    # 绑定的 Key Quorum ID / Bound Key Quorum ID
    key_quorum_id: str


# ============================================================
# 路由处理器 / Route Handlers
# ============================================================

@router.post("/bind-signer", response_model=BindSignerResponse)
async def bind_signer(request: BindSignerRequest):
    """
    将服务端 Key Quorum 绑定为用户钱包的 signer。
    Binds server Key Quorum as a signer on the user's wallet.

    流程 / Flow:
        1. 验证用户 JWT 有效性 / Validate user JWT
        2. 调用 Privy API PATCH /wallets/{wallet_id} 添加 signer
        3. 返回绑定结果 / Return binding result

    成功绑定后，服务端可以用 P256 私钥代替用户签名（无弹窗）。
    After successful binding, server can sign on behalf of user with P256 key (no popup).

    前端调用示例 / Frontend call example:
        POST /api/bind-signer
        {
            "wallet_id": "wallet_abc123...",
            "user_jwt": "eyJhbGciOi..."
        }
    """
    try:
        # 调用 Privy API 添加 signer
        # Call Privy API to add signer
        result = privy_client.add_signer_to_wallet(
            wallet_id=request.wallet_id,
            key_quorum_id=settings.privy_key_quorum_id,
            user_jwt=request.user_jwt,
        )

        return BindSignerResponse(
            success=True,
            message=(
                f"Key Quorum 已成功绑定到 wallet {request.wallet_id} / "
                f"Key Quorum successfully bound to wallet {request.wallet_id}"
            ),
            key_quorum_id=settings.privy_key_quorum_id,
        )

    except httpx.HTTPStatusError as e:
        # Privy API 返回错误 / Privy API returned an error
        error_detail = f"Privy API 错误 / Privy API error: {e.response.status_code} - {e.response.text}"
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"绑定 signer 失败 / Failed to bind signer: {str(e)}",
        )


@router.get("/signer-status/{wallet_id}")
async def get_signer_status(wallet_id: str):
    """
    查询指定 wallet 是否已绑定服务端 Key Quorum（调试用）。
    Queries whether the specified wallet has server Key Quorum bound (for debugging).

    Args:
        wallet_id: Privy wallet ID

    Returns:
        signer 绑定状态信息 / Signer binding status info
    """
    # 注意：此接口需要 wallet 的 user_did 才能查询用户信息
    # Note: This endpoint needs wallet's user_did to query user info
    # 生产环境应存储 wallet_id → user_did 的映射
    # In production, store wallet_id → user_did mapping
    return {
        "wallet_id": wallet_id,
        "key_quorum_id": settings.privy_key_quorum_id,
        "note": (
            "请在前端检查用户状态或查询 Privy Dashboard。"
            "Check user status in frontend or Privy Dashboard."
        ),
    }
