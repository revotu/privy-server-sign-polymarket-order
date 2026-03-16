"""
Builder/Safe 方案端到端测试脚本 / Builder/Safe Scheme End-to-End Test Script
==============================================================================
测试 Polymarket Builder/Safe 下单流程的各个步骤。
Tests each step of the Polymarket Builder/Safe order flow.

使用方法 / Usage:
    # 步骤 1: 纯计算派生 Safe 地址（无需链上，无需 Builder 凭据）
    python scripts/test_builder_flow.py --step derive-safe

    # 步骤 2: 通过 Relayer 部署 Safe + 授权 USDC 给 3 个合约（需要 Builder 凭据 + Privy 配置）
    python scripts/test_builder_flow.py --step deploy-safe

    # 步骤 3: Builder 方案下单（需要 Builder 凭据 + Safe 已部署 + Safe 有 USDC）
    python scripts/test_builder_flow.py --step place-order

    # 运行全部步骤（按顺序）
    python scripts/test_builder_flow.py --step all

环境变量配置 / Environment Variables:
    在项目根目录的 .env 文件中配置（参考 .env.example）：
    Configure in project root .env file (see .env.example):

    # EOA 信息（Privy wallet）
    TEST_WALLET_ID=your_privy_wallet_id
    TEST_WALLET_ADDRESS=0xYourEOAAddress

    # CLOB API 凭据（通过 /api/derive-clob-credentials 获取）
    TEST_CLOB_API_KEY=your_clob_api_key
    TEST_CLOB_API_SECRET=your_clob_api_secret
    TEST_CLOB_API_PASSPHRASE=your_clob_api_passphrase

    # 测试市场（用于下单测试）
    TEST_CONDITION_ID=0xYourConditionId

    # Builder API 凭据
    POLYMARKET_BUILDER_API_KEY=your_builder_api_key
    POLYMARKET_BUILDER_SECRET=your_builder_secret
    POLYMARKET_BUILDER_PASSPHRASE=your_builder_passphrase
"""

import argparse
import os
import sys

# 将 backend 目录加入 Python 路径（确保从项目根目录运行）
# Add backend directory to Python path (ensure run from project root)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv

# 加载 .env 文件（从项目根目录）/ Load .env file (from project root)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def test_derive_safe():
    """
    步骤 1: 纯计算派生 Safe 地址（无需链上操作，无需 Builder 凭据）。
    Step 1: Purely compute Safe address (no chain operation, no Builder credentials).
    """
    from polymarket.safe_wallet import derive_safe_address

    wallet_address = os.getenv("TEST_WALLET_ADDRESS", "")
    if not wallet_address:
        print("❌ 请设置环境变量 TEST_WALLET_ADDRESS / Please set TEST_WALLET_ADDRESS env var")
        return False

    print(f"\n{'='*60}")
    print("步骤 1: 派生 Safe 地址 / Step 1: Derive Safe Address")
    print(f"{'='*60}")
    print(f"EOA 地址 / EOA Address: {wallet_address}")

    try:
        safe_address = derive_safe_address(eoa_address=wallet_address)
        print(f"✅ Safe 地址 / Safe Address: {safe_address}")

        return True
    except Exception as e:
        print(f"❌ 派生失败 / Derivation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deploy_safe():
    """
    步骤 2: 通过 Relayer 部署 Safe + 依次授权 USDC 给 3 个合约。
    Step 2: Deploy Safe via Relayer + approve USDC to 3 contracts.
    """
    from polymarket.safe_wallet import build_safe_approve_usdc_tx_data, derive_safe_address
    from polymarket.relayer_client import compute_safe_tx_hash, relayer_client, split_and_pack_sig
    from privy.client import privy_client
    from config import settings

    wallet_id = os.getenv("TEST_WALLET_ID", "")
    wallet_address = os.getenv("TEST_WALLET_ADDRESS", "")

    if not wallet_id or not wallet_address:
        print("❌ 请设置环境变量 TEST_WALLET_ID, TEST_WALLET_ADDRESS")
        return False

    print(f"\n{'='*60}")
    print("步骤 2: 部署 Safe + 授权 USDC / Step 2: Deploy Safe + Approve USDC")
    print(f"{'='*60}")

    # 派生 Safe 地址 / Derive Safe address
    safe_address = derive_safe_address(wallet_address)
    print(f"Safe 地址 / Safe Address: {safe_address}")
    print(f"EOA 地址 / EOA Address: {wallet_address}")

    # 检查是否已部署 / Check if already deployed
    deployed = relayer_client.check_deployed(safe_address)
    print(f"已部署 / Already deployed: {deployed}")

    try:
        if not deployed:
            # 构建 CreateProxy EIP-712 数据并签名 / Build CreateProxy EIP-712 data and sign
            deploy_typed_data = relayer_client.build_safe_create_typed_data()
            print("📝 通过 Privy 签名部署授权... / Signing deploy auth via Privy...")
            deploy_signature = privy_client.sign_typed_data(
                wallet_id=wallet_id,
                typed_data=deploy_typed_data,
            )
            print(f"   签名 / Signature: {deploy_signature[:20]}...")

            # 提交 Relayer 部署 / Submit to Relayer to deploy
            print("🚀 提交 Relayer 部署 Safe... / Submitting to Relayer to deploy Safe...")
            deploy_result = relayer_client.deploy_safe(
                eoa_address=wallet_address,
                safe_address=safe_address,
                signature=deploy_signature,
            )
            deploy_tx_id = deploy_result.get("transactionID", "")
            print(f"   transactionID: {deploy_tx_id}")

            # 等待部署确认 / Wait for deploy confirmation
            print("⏳ 等待 Safe 部署确认... / Waiting for Safe deployment confirmation...")
            relayer_client.wait_for_tx(deploy_tx_id, timeout_seconds=120)
            print("✅ Safe 部署成功！/ Safe deployed successfully!")
        else:
            print("   Safe 已部署，跳过部署步骤 / Safe already deployed, skipping deploy step")

        # 依次授权 USDC 给 3 个合约 / Approve USDC to 3 contracts sequentially
        approve_spenders = [
            (settings.polymarket_ctf_exchange_address, "CTF Exchange"),
            (settings.polymarket_neg_risk_ctf_exchange_address, "NegRisk CTF Exchange"),
            (settings.polymarket_neg_risk_adapter_address, "NegRisk Adapter"),
        ]
        for spender_addr, spender_name in approve_spenders:
            print(f"\n🔐 授权 {spender_name}... / Approving {spender_name}...")
            safe_nonce = relayer_client.get_safe_nonce(wallet_address)
            approve_tx = build_safe_approve_usdc_tx_data(spender_address=spender_addr)

            safe_tx_hash = compute_safe_tx_hash(
                safe_address=safe_address,
                to=approve_tx["to"],
                data=approve_tx["data"],
                nonce=int(safe_nonce),
            )
            raw_sig = privy_client.sign_message(wallet_id=wallet_id, message_hash=safe_tx_hash)
            packed_sig = split_and_pack_sig(raw_sig)

            approve_result = relayer_client.execute_safe_transaction(
                eoa_address=wallet_address,
                safe_address=safe_address,
                to=approve_tx["to"],
                data=approve_tx["data"],
                signature=packed_sig,
                nonce=safe_nonce,
            )
            approve_tx_id = approve_result.get("transactionID", "")
            print(f"   transactionID: {approve_tx_id}")

            print(f"   ⏳ 等待确认... / Waiting for confirmation...")
            relayer_client.wait_for_tx(approve_tx_id, timeout_seconds=120)
            print(f"   ✅ {spender_name} 授权成功！/ Approved successfully!")

        print("\n✅ 全部授权完成！/ All approvals complete!")
        return True

    except Exception as e:
        print(f"❌ 失败 / Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_place_order_builder():
    """
    步骤 3: Builder 方案下单（maker=Safe, signer=EOA, signatureType=2）。
    Step 3: Place order via Builder scheme (maker=Safe, signer=EOA, signatureType=2).
    """
    from polymarket.safe_wallet import derive_safe_address
    from polymarket.builder_auth import build_builder_headers
    from polymarket.clob_client import ClobApiClient
    from polymarket.order_builder import (
        SIG_TYPE_GNOSIS_SAFE,
        build_eip712_typed_data,
        build_order_message,
        build_signed_order_payload,
    )
    from privy.client import privy_client
    import json

    wallet_id = os.getenv("TEST_WALLET_ID", "")
    wallet_address = os.getenv("TEST_WALLET_ADDRESS", "")
    clob_api_key = os.getenv("TEST_CLOB_API_KEY", "")
    clob_api_secret = os.getenv("TEST_CLOB_API_SECRET", "")
    clob_api_passphrase = os.getenv("TEST_CLOB_API_PASSPHRASE", "")
    condition_id = os.getenv(
        "TEST_CONDITION_ID",
        "0x5f65177b394277fd294cd75650044e9b4e9e74c9cef28e7694f98ca99e50a2b4",  # 示例市场
    )

    if not all([wallet_id, wallet_address, clob_api_key, clob_api_secret, clob_api_passphrase]):
        print("❌ 请设置所有必要的环境变量（参考文件头部注释）")
        print("   Please set all required env vars (see file header comments)")
        return False

    print(f"\n{'='*60}")
    print("步骤 3: Builder 方案下单 / Step 3: Place Order (Builder)")
    print(f"{'='*60}")

    # 派生 Safe 地址 / Derive Safe address
    safe_address = derive_safe_address(wallet_address)
    print(f"EOA (signer): {wallet_address}")
    print(f"Safe (maker): {safe_address}")
    print(f"Condition ID: {condition_id}")

    clob = ClobApiClient(
        api_key=clob_api_key,
        api_secret=clob_api_secret,
        api_passphrase=clob_api_passphrase,
    )

    try:
        # 获取市场信息 / Get market info
        print("\n📊 获取市场信息... / Getting market info...")
        market = clob.get_market(condition_id)
        tokens = market.get("tokens", [])
        if not tokens:
            print("❌ 市场没有 token 信息 / Market has no token info")
            return False

        token_id = tokens[0].get("token_id", "")
        neg_risk = market.get("neg_risk", False)
        print(f"   token_id: {token_id[:20]}...")
        print(f"   neg_risk: {neg_risk}")

        # 获取手续费率 / Get fee rate
        fee_rate_bps = clob.get_fee_rate(token_id)
        print(f"   fee_rate_bps: {fee_rate_bps}")

        # 构建订单（maker=Safe, signer=EOA, signatureType=2）
        # Build order (maker=Safe, signer=EOA, signatureType=2)
        print("\n📝 构建订单... / Building order...")
        order_message = build_order_message(
            maker_address=safe_address,
            signer_address=wallet_address,
            token_id=token_id,
            side="BUY",
            price=0.5,
            size=2.0,  # $1.00 total, meets CLOB minimum order size of $1
            fee_rate_bps=fee_rate_bps,
            signature_type=SIG_TYPE_GNOSIS_SAFE,
        )
        print(f"   maker: {order_message['maker']}")
        print(f"   signer: {order_message['signer']}")
        print(f"   signatureType: {order_message['signatureType']}")
        print(f"   makerAmount: {order_message['makerAmount']}")
        print(f"   takerAmount: {order_message['takerAmount']}")

        # EIP-712 typed data / EIP-712 typed data
        typed_data = build_eip712_typed_data(order_message, neg_risk=neg_risk)

        # Privy 签名 / Privy signing
        print("\n🔐 Privy 服务端签名... / Privy server-side signing...")
        signature = privy_client.sign_typed_data(
            wallet_id=wallet_id,
            typed_data=typed_data,
        )
        print(f"   ✅ 签名成功 / Signature: {signature[:20]}...")

        # 组装 SignedOrder / Assemble SignedOrder
        signed_order = build_signed_order_payload(order_message, signature)

        # 生成 Builder 头 / Generate Builder headers
        print("\n🔑 生成 Builder 认证头... / Generating Builder auth headers...")
        body_str = json.dumps(
            {"order": signed_order, "owner": clob_api_key, "orderType": "GTC", "postOnly": False},
            separators=(",", ":"),
        )
        builder_hdrs = build_builder_headers("POST", "/order", body_str)
        print(f"   ✅ POLY_BUILDER_API_KEY: {builder_hdrs['POLY_BUILDER_API_KEY'][:8]}...")
        print(f"   ✅ POLY_BUILDER_TIMESTAMP: {builder_hdrs['POLY_BUILDER_TIMESTAMP']}")

        # 提交订单 / Submit order
        print("\n🚀 提交 Builder 订单... / Submitting Builder order...")
        result = clob.submit_order(
            signed_order,
            order_type="GTC",
            wallet_address=wallet_address,
            builder_headers=builder_hdrs,
        )
        print(f"   响应 / Response: {result}")

        success = result.get("success", False)
        order_id = result.get("orderID", "")
        error_msg = result.get("errorMsg", "")

        if success:
            print(f"\n✅ 订单提交成功！/ Order submitted successfully!")
            print(f"   Order ID: {order_id}")
        else:
            print(f"\n⚠️  订单未成功 / Order not successful")
            print(f"   Error: {error_msg}")
            print(f"   (如报 'not enough balance' 说明签名正确但 Safe 余额不足)")
            print(f"   (if 'not enough balance' — signature is correct, Safe has insufficient funds)")

        return True

    except Exception as e:
        print(f"❌ 下单失败 / Order placement failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Builder/Safe 方案端到端测试 / Builder/Safe E2E Test"
    )
    parser.add_argument(
        "--step",
        choices=["derive-safe", "deploy-safe", "place-order", "all"],
        default="derive-safe",
        help="测试步骤 / Test step: derive-safe | deploy-safe | place-order | all",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Polymarket Builder/Safe 方案测试 / Builder/Safe Scheme Test")
    print("=" * 60)

    if args.step == "derive-safe" or args.step == "all":
        ok = test_derive_safe()
        if not ok and args.step == "all":
            print("\n❌ 步骤 1 失败，终止测试 / Step 1 failed, aborting")
            return

    if args.step == "deploy-safe" or args.step == "all":
        ok = test_deploy_safe()
        if not ok and args.step == "all":
            print("\n❌ 步骤 2 失败，终止测试 / Step 2 failed, aborting")
            return

    if args.step == "place-order" or args.step == "all":
        test_place_order_builder()

    print("\n" + "=" * 60)
    print("测试完成 / Test completed")
    print("=" * 60)


if __name__ == "__main__":
    main()
