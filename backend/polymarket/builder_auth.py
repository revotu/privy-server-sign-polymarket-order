"""
Polymarket Builder API 认证头生成 / Polymarket Builder API Auth Header Generation
=================================================================================
使用 py_builder_signing_sdk 生成 Polymarket Builder API 认证头。
Generates Polymarket Builder API auth headers using py_builder_signing_sdk.

Builder API 认证头 / Builder API Auth Headers:
    POLY_BUILDER_API_KEY       Builder API Key
    POLY_BUILDER_TIMESTAMP     Unix 时间戳（秒）/ Unix timestamp (seconds)
    POLY_BUILDER_PASSPHRASE    Builder API Passphrase
    POLY_BUILDER_SIGNATURE     HMAC-SHA256 签名 / HMAC-SHA256 signature

Builder 方案下单时需要同时携带 L2 头 + Builder 头：
When placing orders via Builder scheme, both L2 headers + Builder headers are required:
    L2 头：POLY_ADDRESS, POLY_SIGNATURE, POLY_TIMESTAMP, POLY_API_KEY, POLY_PASSPHRASE
    Builder 头：POLY_BUILDER_* 四个字段

参考 / Reference:
    https://docs.polymarket.com/developers/builders/builder-profile
    py_builder_signing_sdk (installed in venv)
"""

from typing import Optional

from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds

from config import settings


def _get_builder_config() -> BuilderConfig:
    """
    从 settings 构建 BuilderConfig 实例。
    Builds BuilderConfig instance from settings.
    """
    creds = BuilderApiKeyCreds(
        key=settings.polymarket_builder_api_key,
        secret=settings.polymarket_builder_secret,
        passphrase=settings.polymarket_builder_passphrase,
    )
    return BuilderConfig(local_builder_creds=creds)


def build_builder_headers(
    method: str,
    path: str,
    body: Optional[str] = None,
) -> dict:
    """
    生成 Polymarket Builder API 认证头。
    Generates Polymarket Builder API authentication headers.

    使用 py_builder_signing_sdk.BuilderConfig 生成 HMAC-SHA256 签名。
    Uses py_builder_signing_sdk.BuilderConfig to generate HMAC-SHA256 signature.

    Args:
        method: HTTP 方法（"GET", "POST" 等）/ HTTP method ("GET", "POST", etc.)
        path: 请求路径（如 "/order"）/ Request path (e.g., "/order")
        body: 请求体字符串（POST 请求时为 JSON 字符串，GET 为 None）
              Request body string (JSON string for POST, None for GET)

    Returns:
        包含 4 个 POLY_BUILDER_* 头的字典 / Dict with 4 POLY_BUILDER_* headers

    Raises:
        ValueError: 如果 Builder 凭据未配置 / If Builder credentials not configured

    Example:
        >>> headers = build_builder_headers("POST", "/order", '{"order":...}')
        >>> # {"POLY_BUILDER_API_KEY": "...", "POLY_BUILDER_TIMESTAMP": "...", ...}
    """
    if not all([
        settings.polymarket_builder_api_key,
        settings.polymarket_builder_secret,
        settings.polymarket_builder_passphrase,
    ]):
        raise ValueError(
            "Builder API 凭据未配置。请在 .env 中设置 POLYMARKET_BUILDER_API_KEY, "
            "POLYMARKET_BUILDER_SECRET, POLYMARKET_BUILDER_PASSPHRASE。\n"
            "Builder API credentials not configured. Please set POLYMARKET_BUILDER_API_KEY, "
            "POLYMARKET_BUILDER_SECRET, POLYMARKET_BUILDER_PASSPHRASE in .env."
        )

    config = _get_builder_config()
    header_payload = config.generate_builder_headers(
        method=method.upper(),
        path=path,
        body=body,
    )

    if header_payload is None:
        raise RuntimeError("Builder 头生成失败 / Builder header generation failed")

    return header_payload.to_dict()
