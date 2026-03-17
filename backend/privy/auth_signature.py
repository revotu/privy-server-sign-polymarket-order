"""
Privy 授权签名模块 / Privy Authorization Signature Module
============================================================
实现 Privy REST API 请求的 P256 ECDSA 授权签名。
Implements P256 ECDSA authorization signatures for Privy REST API requests.

背景 / Background:
    Privy 的 wallet 操作（签名、发交易、修改 wallet 配置）需要在请求头中附带
    privy-authorization-signature，用于证明请求方有权执行该操作。
    Privy's wallet operations (signing, transactions, wallet updates) require a
    privy-authorization-signature header to prove the requester is authorized.

签名算法 / Signing Algorithm:
    1. 构建 payload（version, method, url, body, headers）
    2. 对 payload 进行 JSON 规范化（RFC 8785，用 sort_keys=True 近似）
    3. 用 P256 私钥对规范化后的 JSON 做 ECDSA SHA-256 签名
    4. base64 编码签名结果，放入 privy-authorization-signature 请求头

    1. Build payload (version, method, url, body, headers)
    2. Canonicalize payload as JSON (RFC 8785, approximated with sort_keys=True)
    3. Sign canonicalized JSON with P256 private key using ECDSA SHA-256
    4. Base64-encode the signature and add to privy-authorization-signature header

参考 / Reference:
    https://docs.privy.io/controls/authorization-keys/using-owners/sign/direct-implementation
"""

import base64
import json
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def load_private_key_from_authorization_key(authorization_key: str) -> ec.EllipticCurvePrivateKey:
    """
    从 wallet-auth: 格式的授权密钥中加载 P256 私钥对象。
    Loads a P256 private key object from a wallet-auth: format authorization key.

    Args:
        authorization_key: Privy 格式的授权私钥，格式为 "wallet-auth:<base64 PKCS8 DER>"
                           Authorization private key in Privy format: "wallet-auth:<base64 PKCS8 DER>"

    Returns:
        P256 私钥对象 / P256 private key object

    Raises:
        ValueError: 如果格式不正确 / If format is incorrect
    """
    if not authorization_key.startswith("wallet-auth:"):
        raise ValueError(
            "授权密钥必须以 'wallet-auth:' 开头 / "
            "Authorization key must start with 'wallet-auth:'"
        )

    # 去除前缀，解码 base64 得到 PKCS8 DER 字节
    # Strip prefix, decode base64 to get PKCS8 DER bytes
    private_key_b64 = authorization_key.replace("wallet-auth:", "")
    private_key_der = base64.b64decode(private_key_b64)

    # 从 DER 格式加载私钥
    # Load private key from DER format
    private_key = serialization.load_der_private_key(private_key_der, password=None)

    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise ValueError("密钥必须是椭圆曲线私钥 / Key must be an elliptic curve private key")

    return private_key


def canonicalize_payload(payload: dict[str, Any]) -> str:
    """
    对 payload 进行 JSON 规范化（近似 RFC 8785）。
    Canonicalizes the payload as JSON (approximating RFC 8785).

    说明 / Note:
        Privy 文档的 Python 示例使用 sort_keys=True + separators=(",", ":")
        作为 RFC 8785 的近似实现，本函数遵循同样的方式。
        Privy's Python docs example uses sort_keys=True + separators=(",", ":")
        as an approximation of RFC 8785; this function follows the same approach.

    Args:
        payload: 要规范化的字典 / Dictionary to canonicalize

    Returns:
        规范化后的 JSON 字符串 / Canonicalized JSON string
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_authorization_signature(
    url: str,
    body: dict[str, Any],
    app_id: str,
    authorization_key: str,
    method: str = "POST",
) -> str:
    """
    计算 Privy API 请求的授权签名。
    Computes the authorization signature for a Privy API request.

    这是核心签名函数，被所有需要授权的 Privy API 调用使用。
    This is the core signing function, used by all authorized Privy API calls.

    Args:
        url: 完整的请求 URL（不含尾部斜杠）
             Full request URL (without trailing slash)
        body: 请求体字典 / Request body dictionary
        app_id: Privy App ID
        authorization_key: wallet-auth: 格式的 P256 私钥
                           P256 private key in wallet-auth: format
        method: HTTP 方法，"POST" 或 "PATCH"（GET 请求不需要签名）
                HTTP method, "POST" or "PATCH" (GET requests don't need signing)

    Returns:
        base64 编码的 DER 格式 ECDSA 签名 / Base64-encoded DER-format ECDSA signature

    Example:
        >>> sig = compute_authorization_signature(
        ...     url="https://api.privy.io/v1/wallets/wallet_123/rpc",
        ...     body={"chain_type": "ethereum", "method": "eth_signTypedData_v4", ...},
        ...     app_id="my_app_id",
        ...     authorization_key="wallet-auth:...",
        ... )
        >>> # 将 sig 放入请求头 / Add sig to request header:
        >>> headers["privy-authorization-signature"] = sig
    """
    # 步骤 1: 构建签名 payload
    # Step 1: Build the signature payload
    # 格式由 Privy 文档定义，参见 direct-implementation 页面
    # Format defined by Privy docs, see direct-implementation page
    payload = {
        "version": 1,
        "method": method,
        "url": url,
        "body": body,
        "headers": {
            "privy-app-id": app_id,
        },
    }

    # 步骤 2: JSON 规范化
    # Step 2: JSON canonicalization
    serialized_payload = canonicalize_payload(payload)

    # 步骤 3: 加载私钥并签名
    # Step 3: Load private key and sign
    private_key = load_private_key_from_authorization_key(authorization_key)
    signature_bytes = private_key.sign(
        serialized_payload.encode("utf-8"),
        ec.ECDSA(hashes.SHA256()),
    )

    # 步骤 4: base64 编码
    # Step 4: Base64 encode
    return base64.b64encode(signature_bytes).decode("utf-8")
