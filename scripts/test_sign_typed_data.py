#!/usr/bin/env python3
"""
调试脚本：直接测试 Privy sign_typed_data（无弹窗签名）
Debug script: directly test Privy sign_typed_data (no-popup signing)

用途：诊断 400 错误，确认 P256 授权签名 + Privy wallet 签名链路是否正常。
Purpose: Diagnose 400 errors, confirm P256 auth signature + Privy wallet signing chain works.

使用方法 / Usage:
    cd backend && python ../scripts/test_sign_typed_data.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import httpx
from config import settings
from privy.auth_signature import compute_authorization_signature


def test_sign_clob_auth(wallet_id: str, wallet_address: str) -> None:
    """
    测试用 ClobAuth EIP-712 数据签名（最简单的 EIP-712 结构）。
    Test signing with ClobAuth EIP-712 data (simplest EIP-712 structure).

    这是 derive-clob-credentials 用到的数据格式。
    This is the data format used by derive-clob-credentials.
    """
    print("=" * 60)
    print("测试 1: ClobAuth 签名 / Test 1: ClobAuth signing")
    print("=" * 60)

    timestamp = str(int(time.time()))

    typed_data = {
        "domain": {
            "name": "ClobAuthDomain",
            "version": "1",
            "chainId": 137,
        },
        "types": {
            "ClobAuth": [
                {"name": "address", "type": "address"},
                {"name": "timestamp", "type": "string"},
                {"name": "nonce", "type": "uint256"},
                {"name": "message", "type": "string"},
            ]
        },
        "primary_type": "ClobAuth",
        "message": {
            "address": wallet_address,
            "timestamp": timestamp,
            "nonce": 0,
            "message": "This message attests that I control the given wallet",
        },
    }

    url = f"{settings.privy_api_base_url}/wallets/{wallet_id}/rpc"

    body = {
        "chain_type": "ethereum",
        "method": "eth_signTypedData_v4",
        "params": {
            "typed_data": typed_data,
        },
    }

    auth_signature = compute_authorization_signature(
        url=url,
        body=body,
        app_id=settings.privy_app_id,
        authorization_key=settings.privy_authorization_key,
        method="POST",
    )

    headers = {
        "Content-Type": "application/json",
        "privy-app-id": settings.privy_app_id,
        "privy-authorization-signature": auth_signature,
    }

    print(f"URL: {url}")
    print(f"wallet_id: {wallet_id}")
    print(f"wallet_address: {wallet_address}")
    print(f"auth_signature (first 40 chars): {auth_signature[:40]}...")
    print()

    resp = httpx.post(
        url,
        json=body,
        auth=(settings.privy_app_id, settings.privy_app_secret),
        headers=headers,
    )

    print(f"HTTP 状态码 / Status: {resp.status_code}")
    print(f"响应体 / Response body:")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)

    if resp.is_success:
        result = resp.json()
        signature = result.get("data", {}).get("signature", "")
        print()
        print(f"✅ 签名成功 / Signing succeeded!")
        print(f"   signature: {signature[:60]}...")
        return signature
    else:
        print()
        print(f"❌ 签名失败 / Signing failed")
        return None


def main():
    # 读取测试用户信息
    test_info_path = os.path.join(os.path.dirname(__file__), "test_user_info.json")
    if not os.path.exists(test_info_path):
        print("❌ 未找到 test_user_info.json，请先运行 create_test_user.py")
        sys.exit(1)

    with open(test_info_path) as f:
        test_info = json.load(f)

    wallet_id = test_info["wallet_id"]
    wallet_address = test_info["wallet_address"]

    print(f"Privy App ID: {settings.privy_app_id}")
    print(f"Key Quorum ID: {settings.privy_key_quorum_id}")
    print(f"wallet_id: {wallet_id}")
    print(f"wallet_address: {wallet_address}")
    print(f"delegated: {test_info.get('delegated', 'unknown')}")
    print()

    test_sign_clob_auth(wallet_id, wallet_address)


if __name__ == "__main__":
    main()
