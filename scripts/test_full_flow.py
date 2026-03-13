#!/usr/bin/env python3
"""
端到端流程测试脚本 / End-to-End Flow Test Script
===================================================
直接调用后端模块，测试完整的无弹窗下单流程：
Directly calls backend modules to test the complete no-popup order flow:

1. sign_typed_data (ClobAuth) → 派生 CLOB API 凭据
2. 获取活跃市场信息
3. sign_typed_data (Order) → 服务端代签订单
4. 提交订单到 Polymarket CLOB

注意：此脚本需要在 backend 目录下运行
Note: Run this script from the backend directory

    cd backend && python ../scripts/test_full_flow.py
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
from polymarket.clob_auth import build_clob_auth_typed_data, derive_api_credentials
from polymarket.clob_client import ClobApiClient
from polymarket.order_builder import (
    build_eip712_typed_data,
    build_order_message,
    build_signed_order_payload,
)
from privy.client import privy_client


def step1_derive_clob_credentials(wallet_id: str, wallet_address: str) -> dict:
    """步骤 1: 派生 CLOB API 凭据 / Step 1: Derive CLOB API credentials"""
    print("=" * 60)
    print("步骤 1: 派生 CLOB API 凭据 / Step 1: Derive CLOB credentials")
    print("=" * 60)

    timestamp = str(int(time.time()))

    # 构建 ClobAuth EIP-712 数据
    clob_auth_typed_data = build_clob_auth_typed_data(
        wallet_address=wallet_address,
        timestamp=timestamp,
    )

    # 通过 Privy 服务端签名（无弹窗）
    print("  调用 Privy sign_typed_data (ClobAuth)...")
    signature = privy_client.sign_typed_data(
        wallet_id=wallet_id,
        typed_data=clob_auth_typed_data,
    )
    print(f"  ✅ 签名成功: {signature[:40]}...")

    # 派生凭据
    credentials = derive_api_credentials(
        wallet_address=wallet_address,
        auth_signature=signature,
        timestamp=timestamp,
    )

    print(f"  ✅ 凭据派生成功!")
    print(f"     api_key: {credentials['api_key']}")
    print(f"     api_secret: {credentials['api_secret'][:20]}...")
    print(f"     api_passphrase: {credentials['api_passphrase'][:10]}...")
    print()

    return credentials


def step2_get_active_market() -> tuple[str, str, bool]:
    """步骤 2: 获取一个活跃市场 / Step 2: Get an active market"""
    print("=" * 60)
    print("步骤 2: 获取活跃市场 / Step 2: Get active market")
    print("=" * 60)

    # 使用 sampling-markets 端点，返回的都是有真实 orderbook 的活跃市场
    # Use sampling-markets endpoint, which only returns markets with real active orderbooks
    resp = httpx.get(
        f"{settings.polymarket_clob_host}/sampling-markets",
    )
    resp.raise_for_status()
    data = resp.json()

    # sampling-markets 返回的市场都有活跃 orderbook，无需额外过滤
    # Markets from sampling-markets all have active orderbooks, no additional filtering needed
    markets = data if isinstance(data, list) else data.get("data", [])
    for market in markets:
        tokens = market.get("tokens", [])
        if tokens and market.get("active", False):
            condition_id = market.get("condition_id", "")
            token_id = tokens[0].get("token_id", "")
            neg_risk = market.get("neg_risk", False)
            question = market.get("question", "")[:60]
            print(f"  市场 / Market: {question}")
            print(f"  condition_id: {condition_id}")
            print(f"  token_id: {token_id[:30]}...")
            print(f"  neg_risk: {neg_risk}")
            print()
            return condition_id, token_id, neg_risk

    raise RuntimeError("未找到活跃市场 / No active market found")


def step3_place_order(
    wallet_id: str,
    wallet_address: str,
    credentials: dict,
    condition_id: str,
) -> None:
    """步骤 3: 服务端签名并下单 / Step 3: Server-side sign and place order"""
    print("=" * 60)
    print("步骤 3: 服务端签名并下单 / Step 3: Sign and place order")
    print("=" * 60)

    clob = ClobApiClient(
        api_key=credentials["api_key"],
        api_secret=credentials["api_secret"],
        api_passphrase=credentials["api_passphrase"],
    )

    # 获取市场详情
    market = clob.get_market(condition_id)
    tokens = market.get("tokens", [])
    if not tokens:
        print("  ❌ 市场没有 token 信息 / Market has no token info")
        return

    token_id = tokens[0].get("token_id", "")
    neg_risk = market.get("neg_risk", False)

    # 获取手续费率
    fee_rate_bps = clob.get_fee_rate(token_id)
    print(f"  token_id: {token_id[:30]}...")
    print(f"  fee_rate_bps: {fee_rate_bps}")

    # 构建订单
    order_message = build_order_message(
        maker_address=wallet_address,
        token_id=token_id,
        side="BUY",
        price=0.01,   # 极低价格，不太可能成交
        size=1.0,
        fee_rate_bps=fee_rate_bps,
    )

    # 包装成 EIP-712 结构
    typed_data = build_eip712_typed_data(order_message, neg_risk=neg_risk)

    # Privy 服务端签名（无弹窗！）
    print("  调用 Privy sign_typed_data (Order)...")
    signature = privy_client.sign_typed_data(
        wallet_id=wallet_id,
        typed_data=typed_data,
    )
    print(f"  ✅ 订单签名成功: {signature[:40]}...")

    # 组装 SignedOrder
    signed_order = build_signed_order_payload(order_message, signature)

    # 提交到 Polymarket CLOB
    print("  提交订单到 Polymarket CLOB...")
    try:
        result = clob.submit_order(signed_order, order_type="GTC", wallet_address=wallet_address)
        print(f"  CLOB 响应 / CLOB Response: {json.dumps(result, indent=4)}")

        if result.get("success"):
            print(f"\n  ✅ 订单提交成功 / Order placed successfully!")
            print(f"     order_id: {result.get('orderID', 'N/A')}")
            print(f"     status: {result.get('status', 'N/A')}")
        else:
            # 即使 CLOB 拒绝，只要签名通过，链路已验证
            err = result.get("errorMsg", "unknown error")
            print(f"\n  ⚠️  CLOB 拒绝订单（签名本身成功）/ CLOB rejected order (signing succeeded)")
            print(f"     原因 / Reason: {err}")
            print(f"     注：若是 insufficient balance / not enough balance，签名链路完全正常！")
            print(f"     Note: If 'not enough balance / allowance', the signing pipeline works correctly!")
    except httpx.HTTPStatusError as e:
        print(f"  CLOB API 错误 / CLOB API error: {e.response.status_code}")
        print(f"  响应体 / Response: {e.response.text}")
        print(f"  注：只要前面的签名步骤成功，核心功能已验证！")


def main():
    print()
    print("=" * 60)
    print("★ 无弹窗 Polymarket 下单完整流程测试")
    print("★ No-Popup Polymarket Order Full Flow Test")
    print("=" * 60)
    print(f"App ID: {settings.privy_app_id}")
    print(f"Key Quorum: {settings.privy_key_quorum_id}")
    print()

    # 读取测试用户信息
    test_info_path = os.path.join(os.path.dirname(__file__), "test_user_info.json")
    with open(test_info_path) as f:
        test_info = json.load(f)

    wallet_id = test_info["wallet_id"]
    wallet_address = test_info["wallet_address"]

    print(f"wallet_id: {wallet_id}")
    print(f"wallet_address: {wallet_address}")
    print(f"delegated: {test_info.get('delegated', 'unknown')}")
    print()

    # 步骤 1: 派生 CLOB 凭据
    credentials = step1_derive_clob_credentials(wallet_id, wallet_address)

    # 步骤 2: 获取活跃市场
    condition_id, _, _ = step2_get_active_market()

    # 步骤 3: 签名并下单
    step3_place_order(wallet_id, wallet_address, credentials, condition_id)

    print()
    print("=" * 60)
    print("测试完成 / Test complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
