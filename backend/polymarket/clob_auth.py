"""
Polymarket CLOB API 认证模块 / Polymarket CLOB API Authentication Module
=========================================================================
处理 Polymarket CLOB API 的 L1 和 L2 身份认证。
Handles L1 and L2 authentication for the Polymarket CLOB API.

认证级别 / Authentication Levels:
    L1 认证（一次性）：通过 EIP-712 签名派生 API Key/Secret/Passphrase
    L1 Auth (one-time): Derive API Key/Secret/Passphrase via EIP-712 signing

    L2 认证（每次请求）：使用 API Secret 对请求做 HMAC-SHA256 签名
    L2 Auth (per request): HMAC-SHA256 sign each request with API Secret

CLOB API 凭据派生流程 / CLOB API Credentials Derivation Flow:
    1. 构建 ClobAuthDomain EIP-712 消息（不含 message 字段）
    2. 通过 Privy sign_typed_data 用用户钱包签名
    3. 用签名调用 POST /auth/derive-api-key 获取凭据
    4. 存储凭据供后续 L2 认证使用

参考 / Reference:
    https://docs.polymarket.com/developers/CLOB/authentication
"""

import hashlib
import hmac
import time
from base64 import b64encode

import httpx

from config import settings


# EIP-712 域（与 Polymarket CLOB 认证合约匹配）
# EIP-712 domain (matches Polymarket CLOB auth contract)
CLOB_AUTH_DOMAIN = {
    "name": "ClobAuthDomain",
    "version": "1",
    "chainId": 137,
}

# CLOB 认证类型定义 / CLOB auth type definitions
CLOB_AUTH_TYPES = {
    "ClobAuth": [
        {"name": "address", "type": "address"},
        {"name": "timestamp", "type": "string"},
        {"name": "nonce", "type": "uint256"},
        {"name": "message", "type": "string"},
    ]
}


def build_clob_auth_typed_data(wallet_address: str, timestamp: str, nonce: int = 0) -> dict:
    """
    构建 CLOB API 认证用的 EIP-712 结构化数据。
    Builds EIP-712 structured data for CLOB API authentication.

    此数据需要用用户钱包签名，然后发给 CLOB API 换取 API 凭据。
    This data must be signed with the user wallet, then sent to CLOB API to get API credentials.

    Args:
        wallet_address: 用户的 EOA 地址（Privy wallet 地址）/ User's EOA address (Privy wallet)
        timestamp: Unix 时间戳字符串 / Unix timestamp string
        nonce: 认证 nonce（通常为 0）/ Auth nonce (usually 0)

    Returns:
        完整的 EIP-712 typed data / Complete EIP-712 typed data
    """
    return {
        "domain": CLOB_AUTH_DOMAIN,
        "types": CLOB_AUTH_TYPES,
        "primaryType": "ClobAuth",
        "message": {
            "address": wallet_address,
            "timestamp": timestamp,
            "nonce": nonce,
            # Polymarket 固定的认证消息 / Fixed authentication message from Polymarket
            "message": "This message attests that I control the given wallet",
        },
    }


def derive_api_credentials(
    wallet_address: str,
    auth_signature: str,
    timestamp: str,
    nonce: int = 0,
) -> dict:
    """
    通过签名向 CLOB API 派生 API Key/Secret/Passphrase。
    Derives API Key/Secret/Passphrase from CLOB API using the signature.

    Args:
        wallet_address: 用户钱包地址 / User wallet address
        auth_signature: 用户钱包对 CLOB auth EIP-712 数据的签名
                        User wallet signature over CLOB auth EIP-712 data
        timestamp: 签名时使用的时间戳（必须与签名时一致）
                   Timestamp used during signing (must match what was signed)
        nonce: 签名时使用的 nonce / Nonce used during signing

    Returns:
        包含 api_key, api_secret, api_passphrase 的字典
        Dictionary containing api_key, api_secret, api_passphrase

    Raises:
        httpx.HTTPStatusError: 如果 CLOB API 请求失败 / If CLOB API request fails
    """
    # L1 认证：通过签名直接调用 derive-api-key 接口
    # L1 auth: call derive-api-key endpoint directly with signature
    headers = _build_l1_headers(
        wallet_address=wallet_address,
        signature=auth_signature,
        timestamp=timestamp,
        nonce=nonce,
    )

    with httpx.Client() as client:
        response = client.post(
            f"{settings.polymarket_clob_host}/auth/derive-api-key",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    return {
        "api_key": data["apiKey"],
        "api_secret": data["secret"],
        "api_passphrase": data["passphrase"],
    }


def _build_l1_headers(
    wallet_address: str,
    signature: str,
    timestamp: str,
    nonce: int = 0,
) -> dict:
    """
    构建 CLOB API L1 认证请求头。
    Builds CLOB API L1 authentication request headers.

    L1 认证直接用 EIP-712 签名，无需 HMAC。
    L1 auth uses EIP-712 signature directly, no HMAC needed.
    """
    return {
        "Content-Type": "application/json",
        "POLY_ADDRESS": wallet_address,
        "POLY_SIGNATURE": signature,
        "POLY_TIMESTAMP": timestamp,
        "POLY_NONCE": str(nonce),
    }


def build_l2_headers(
    api_key: str,
    api_secret: str,
    api_passphrase: str,
    method: str,
    request_path: str,
    body: str = "",
) -> dict:
    """
    构建 Polymarket CLOB API L2 认证请求头（HMAC-SHA256）。
    Builds Polymarket CLOB API L2 authentication headers (HMAC-SHA256).

    每次 API 请求都需要这些头，用于身份验证和防重放攻击。
    These headers are required for every API request, for authentication and replay prevention.

    签名构建 / Signature construction:
        message = timestamp + method.upper() + requestPath + body
        signature = base64(HMAC-SHA256(api_secret, message))

    Args:
        api_key: CLOB API Key（从 derive_api_credentials 获取）
                 CLOB API Key (obtained from derive_api_credentials)
        api_secret: CLOB API Secret / CLOB API Secret
        api_passphrase: CLOB API Passphrase / CLOB API Passphrase
        method: HTTP 方法（GET, POST 等）/ HTTP method (GET, POST, etc.)
        request_path: 请求路径（如 /order）/ Request path (e.g., /order)
        body: 请求体字符串（POST 请求时为 JSON 字符串，GET 为空）
              Request body string (JSON string for POST, empty for GET)

    Returns:
        包含 L2 认证所需所有 headers 的字典
        Dictionary with all headers required for L2 authentication
    """
    # 使用当前 Unix 时间戳（秒）作为防重放的 nonce
    # Use current Unix timestamp (seconds) as anti-replay nonce
    timestamp = str(int(time.time()))

    # 构建签名消息：timestamp + method + path + body
    # Build signature message: timestamp + method + path + body
    message = timestamp + method.upper() + request_path + body

    # HMAC-SHA256 签名 / HMAC-SHA256 signature
    signature = _hmac_signature(api_secret, message)

    return {
        "Content-Type": "application/json",
        "POLY_ADDRESS": "",  # L2 不需要地址 / L2 doesn't need address
        "POLY_SIGNATURE": signature,
        "POLY_TIMESTAMP": timestamp,
        "POLY_API_KEY": api_key,
        "POLY_PASSPHRASE": api_passphrase,
    }


def _hmac_signature(secret: str, message: str) -> str:
    """
    生成 HMAC-SHA256 签名并 base64 编码。
    Generates HMAC-SHA256 signature and base64 encodes it.

    Args:
        secret: CLOB API Secret
        message: 要签名的消息 / Message to sign

    Returns:
        base64 编码的 HMAC-SHA256 签名 / Base64-encoded HMAC-SHA256 signature
    """
    hashed = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return b64encode(hashed.digest()).decode("utf-8")
