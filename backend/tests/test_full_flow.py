"""
完整流程集成测试 / Full Flow Integration Tests
================================================
测试 Privy 服务端签名 → Polymarket 下单的完整流程。
Tests the complete flow: Privy server-side signing → Polymarket order placement.

⚠️  注意 / WARNING:
    集成测试需要真实的环境变量配置（.env 文件）和真实的 API 调用！
    Integration tests require real environment variable config (.env) and real API calls!

    - test_auth_signature_flow: 真实 Privy API 调用（需要配置 .env）
    - test_order_builder: 纯本地测试，不需要 API 调用
    - test_full_order_flow: 真实 Privy + Polymarket API 调用（需要配置 .env + 钱包余额）

运行所有测试 / Run all tests:
    cd backend && pytest tests/test_full_flow.py -v

仅运行本地测试（不需要 API）/ Run only local tests (no API needed):
    cd backend && pytest tests/test_full_flow.py -v -m "not integration"

运行集成测试 / Run integration tests:
    cd backend && pytest tests/test_full_flow.py -v -m integration
"""

import pytest

from polymarket.order_builder import (
    SIDE_BUY,
    SIDE_SELL,
    SIG_TYPE_EOA,
    ZERO_ADDRESS,
    build_eip712_typed_data,
    build_order_message,
    build_signed_order_payload,
    usdc_to_wei,
)


# ============================================================
# 测试固件 / Test Fixtures
# ============================================================

# 测试用钱包地址（非真实）/ Test wallet address (not real)
TEST_WALLET_ADDRESS = "0x1234567890123456789012345678901234567890"

# 测试用 token ID（Polymarket 真实市场的 token ID，用于演示）
# Test token ID (real Polymarket market token ID, for demo purposes)
TEST_TOKEN_ID = "71321045679252212594626385532706912750332728571942532289631379312455583992563"

# 测试用 condition ID / Test condition ID
TEST_CONDITION_ID = "0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee3a7386ad423d9dd9b"


# ============================================================
# 本地单元测试（不需要 API）/ Local Unit Tests (no API needed)
# ============================================================

class TestUsdcToWei:
    """测试 USDC 金额转换 / Tests for USDC amount conversion"""

    def test_convert_1_usdc(self):
        """1 USDC 应该等于 1_000_000 / 1 USDC should equal 1_000_000"""
        assert usdc_to_wei(1.0) == 1_000_000

    def test_convert_fractional(self):
        """小数 USDC 应该正确转换 / Fractional USDC should convert correctly"""
        assert usdc_to_wei(0.5) == 500_000
        assert usdc_to_wei(1.5) == 1_500_000
        assert usdc_to_wei(100.0) == 100_000_000

    def test_precision_handling(self):
        """应该正确处理小数精度问题 / Should correctly handle decimal precision issues"""
        # 使用 Decimal 避免浮点精度问题 / Use Decimal to avoid float precision issues
        assert usdc_to_wei(0.1) == 100_000
        assert usdc_to_wei(0.01) == 10_000


class TestBuildOrderMessage:
    """测试订单消息构建 / Tests for order message building"""

    def test_buy_order_structure(self):
        """BUY 订单应该有正确的结构 / BUY order should have correct structure"""
        msg = build_order_message(
            maker_address=TEST_WALLET_ADDRESS,
            token_id=TEST_TOKEN_ID,
            side="BUY",
            price=0.6,
            size=10.0,
            fee_rate_bps=100,
        )

        assert msg["maker"] == TEST_WALLET_ADDRESS
        assert msg["signer"] == TEST_WALLET_ADDRESS  # EOA 直签时相同 / Same for EOA direct signing
        assert msg["taker"] == ZERO_ADDRESS  # 公开订单 / Public order
        assert msg["tokenId"] == int(TEST_TOKEN_ID)
        assert msg["side"] == SIDE_BUY
        assert msg["signatureType"] == SIG_TYPE_EOA
        assert msg["feeRateBps"] == 100
        assert msg["expiration"] == 0  # GTC / Never expires
        assert msg["nonce"] == 0
        assert "salt" in msg  # 随机 salt 存在 / Random salt present

    def test_sell_order_structure(self):
        """SELL 订单应该有正确的结构 / SELL order should have correct structure"""
        msg = build_order_message(
            maker_address=TEST_WALLET_ADDRESS,
            token_id=TEST_TOKEN_ID,
            side="SELL",
            price=0.6,
            size=10.0,
            fee_rate_bps=100,
        )

        assert msg["side"] == SIDE_SELL

    def test_buy_order_amounts(self):
        """BUY 订单金额应该正确计算 / BUY order amounts should be correctly calculated"""
        # BUY 0.6 USDC/token × 10 tokens = 6 USDC
        msg = build_order_message(
            maker_address=TEST_WALLET_ADDRESS,
            token_id=TEST_TOKEN_ID,
            side="BUY",
            price=0.6,
            size=10.0,
            fee_rate_bps=100,
        )

        # makerAmount = 0.6 * 10 = 6 USDC = 6_000_000 (6 decimals)
        assert msg["makerAmount"] == 6_000_000
        # takerAmount = 10 tokens = 10_000_000 (6 decimals on Polymarket)
        assert msg["takerAmount"] == 10_000_000

    def test_sell_order_amounts(self):
        """SELL 订单金额应该与 BUY 相反 / SELL order amounts should be inverse of BUY"""
        msg = build_order_message(
            maker_address=TEST_WALLET_ADDRESS,
            token_id=TEST_TOKEN_ID,
            side="SELL",
            price=0.6,
            size=10.0,
            fee_rate_bps=100,
        )

        # SELL: makerAmount = tokens, takerAmount = USDC
        assert msg["makerAmount"] == 10_000_000   # 10 tokens
        assert msg["takerAmount"] == 6_000_000    # 6 USDC

    def test_salt_is_unique(self):
        """不同订单应该有不同的 salt / Different orders should have different salts"""
        msg1 = build_order_message(
            maker_address=TEST_WALLET_ADDRESS,
            token_id=TEST_TOKEN_ID,
            side="BUY",
            price=0.6,
            size=10.0,
            fee_rate_bps=100,
        )
        msg2 = build_order_message(
            maker_address=TEST_WALLET_ADDRESS,
            token_id=TEST_TOKEN_ID,
            side="BUY",
            price=0.6,
            size=10.0,
            fee_rate_bps=100,
        )

        # salt 应该是随机的，两次生成应该不同（极低概率相同）
        # salt should be random, two generations should differ (extremely low chance of collision)
        assert msg1["salt"] != msg2["salt"]


class TestBuildEip712TypedData:
    """测试 EIP-712 结构化数据构建 / Tests for EIP-712 structured data building"""

    def test_standard_market_domain(self):
        """标准市场应该使用 CTF Exchange 合约地址 / Standard market should use CTF Exchange address"""
        msg = build_order_message(TEST_WALLET_ADDRESS, TEST_TOKEN_ID, "BUY", 0.6, 10.0, 100)
        typed_data = build_eip712_typed_data(msg, neg_risk=False)

        assert typed_data["domain"]["name"] == "ClobAuthDomain"
        assert typed_data["domain"]["version"] == "1"
        assert typed_data["domain"]["chainId"] == 137
        # 标准市场使用 CTF Exchange 地址 / Standard market uses CTF Exchange address
        assert typed_data["domain"]["verifyingContract"] == "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

    def test_neg_risk_market_domain(self):
        """多结果市场应该使用 NegRisk Exchange 合约地址 / Multi-outcome market should use NegRisk Exchange address"""
        msg = build_order_message(TEST_WALLET_ADDRESS, TEST_TOKEN_ID, "BUY", 0.6, 10.0, 100)
        typed_data = build_eip712_typed_data(msg, neg_risk=True)

        # NegRisk 市场使用不同的合约地址 / NegRisk markets use different contract address
        assert typed_data["domain"]["verifyingContract"] == "0xC5d563A36AE78145C45a50134d48A1215220f80a"

    def test_typed_data_structure(self):
        """EIP-712 结构应该包含所有必要字段 / EIP-712 structure should contain all required fields"""
        msg = build_order_message(TEST_WALLET_ADDRESS, TEST_TOKEN_ID, "BUY", 0.6, 10.0, 100)
        typed_data = build_eip712_typed_data(msg)

        assert "domain" in typed_data
        assert "types" in typed_data
        assert "primaryType" in typed_data
        assert "message" in typed_data
        assert typed_data["primaryType"] == "Order"

    def test_order_types_fields(self):
        """Order 类型应该包含所有 12 个必要字段 / Order type should contain all 12 required fields"""
        msg = build_order_message(TEST_WALLET_ADDRESS, TEST_TOKEN_ID, "BUY", 0.6, 10.0, 100)
        typed_data = build_eip712_typed_data(msg)

        order_fields = {f["name"] for f in typed_data["types"]["Order"]}
        required_fields = {
            "salt", "maker", "signer", "taker", "tokenId",
            "makerAmount", "takerAmount", "expiration", "nonce",
            "feeRateBps", "side", "signatureType"
        }
        assert required_fields.issubset(order_fields)


class TestBuildSignedOrderPayload:
    """测试 SignedOrder payload 构建 / Tests for SignedOrder payload building"""

    def test_signed_order_structure(self):
        """SignedOrder 应该包含所有字段（包括签名）/ SignedOrder should contain all fields (including signature)"""
        msg = build_order_message(TEST_WALLET_ADDRESS, TEST_TOKEN_ID, "BUY", 0.6, 10.0, 100)
        fake_signature = "0x" + "a" * 130  # 模拟签名 / Mock signature

        signed_order = build_signed_order_payload(msg, fake_signature)

        # 验证所有字段存在 / Verify all fields present
        required_keys = [
            "salt", "maker", "signer", "taker", "tokenId",
            "makerAmount", "takerAmount", "expiration", "nonce",
            "feeRateBps", "side", "signatureType", "signature"
        ]
        for key in required_keys:
            assert key in signed_order, f"缺少字段 / Missing field: {key}"

    def test_amounts_are_strings(self):
        """金额字段应该是字符串（CLOB API 要求）/ Amount fields should be strings (CLOB API requires)"""
        msg = build_order_message(TEST_WALLET_ADDRESS, TEST_TOKEN_ID, "BUY", 0.6, 10.0, 100)
        signed_order = build_signed_order_payload(msg, "0xabc")

        # CLOB API 要求金额为字符串格式 / CLOB API requires amounts as strings
        assert isinstance(signed_order["salt"], str)
        assert isinstance(signed_order["makerAmount"], str)
        assert isinstance(signed_order["takerAmount"], str)
        assert isinstance(signed_order["tokenId"], str)


# ============================================================
# 集成测试（需要真实 API）/ Integration Tests (require real API)
# ============================================================

@pytest.mark.integration
class TestPrivySigningIntegration:
    """
    Privy 签名集成测试 / Privy Signing Integration Tests

    需要在 .env 中配置真实的 Privy 凭据才能运行。
    Requires real Privy credentials configured in .env to run.

    运行 / Run:
        pytest tests/test_full_flow.py -v -m integration
    """

    def test_sign_simple_message(self):
        """
        测试通过 Privy 服务端对简单消息签名（需要真实 wallet ID）。
        Tests simple message signing via Privy server side (requires real wallet ID).

        替换 wallet_id 为你的真实 Privy wallet ID 后运行。
        Replace wallet_id with your real Privy wallet ID before running.
        """
        pytest.skip(
            "需要真实的 Privy wallet ID / "
            "Requires real Privy wallet ID. "
            "Replace 'your_wallet_id_here' with a real wallet ID and remove this skip."
        )

        from privy.client import privy_client

        # TODO: 替换为真实的 wallet ID / Replace with real wallet ID
        wallet_id = "your_wallet_id_here"

        typed_data = {
            "domain": {"name": "Test", "version": "1", "chainId": 137},
            "types": {
                "Message": [{"name": "content", "type": "string"}]
            },
            "primaryType": "Message",
            "message": {"content": "Hello from Privy server-side signing!"},
        }

        signature = privy_client.sign_typed_data(wallet_id, typed_data)

        assert signature.startswith("0x")
        assert len(signature) >= 130  # ECDSA 签名长度 / ECDSA signature length
        print(f"\n✅ 签名成功 / Signing successful: {signature[:20]}...")


@pytest.mark.integration
class TestPolymarketOrderIntegration:
    """
    Polymarket 完整下单集成测试 / Polymarket Full Order Integration Test

    ⚠️  此测试会在真实 Polygon 主网提交真实订单！
    ⚠️  This test submits REAL orders on Polygon mainnet!

    运行前请确认 / Before running, confirm:
        1. .env 中配置了所有必要的凭据 / All credentials configured in .env
        2. 用户 wallet 已绑定 Key Quorum signer / User wallet has Key Quorum signer bound
        3. 用户 wallet 中有足够的 USDC.e 余额 / User wallet has sufficient USDC.e balance

    运行 / Run:
        pytest tests/test_full_flow.py -v -m integration -k "test_place_real_order"
    """

    def test_place_real_order(self):
        """
        在 Polymarket 上提交真实订单（完整端到端测试）。
        Submits a real order on Polymarket (complete end-to-end test).

        填入真实参数后取消 skip 即可运行。
        Fill in real parameters and remove skip to run.
        """
        pytest.skip(
            "需要真实参数和 USDC 余额 / "
            "Requires real parameters and USDC balance. "
            "Fill in real values and remove this skip to run the full e2e test."
        )

        from privy.client import privy_client
        from polymarket.clob_client import ClobApiClient

        # TODO: 填入真实参数 / Fill in real parameters
        WALLET_ID = "your_privy_wallet_id"
        WALLET_ADDRESS = "0xYourWalletAddress"
        CONDITION_ID = "0xYourConditionId"
        CLOB_API_KEY = "your_clob_api_key"
        CLOB_API_SECRET = "your_clob_api_secret"
        CLOB_API_PASSPHRASE = "your_clob_api_passphrase"

        clob = ClobApiClient(CLOB_API_KEY, CLOB_API_SECRET, CLOB_API_PASSPHRASE)

        # 获取市场信息 / Get market info
        market = clob.get_market(CONDITION_ID)
        token_id = market["tokens"][0]["token_id"]
        neg_risk = market.get("neg_risk", False)

        # 获取手续费率 / Get fee rate
        fee_rate_bps = clob.get_fee_rate(token_id)

        # 构建订单（小额测试单）/ Build order (small test order)
        order_msg = build_order_message(
            maker_address=WALLET_ADDRESS,
            token_id=token_id,
            side="BUY",
            price=0.01,   # 极低价格，不太可能成交 / Very low price, unlikely to fill
            size=1.0,
            fee_rate_bps=fee_rate_bps,
        )

        typed_data = build_eip712_typed_data(order_msg, neg_risk=neg_risk)

        # Privy 服务端签名（★ 无弹窗！）/ Privy server-side signing (★ no popup!)
        signature = privy_client.sign_typed_data(WALLET_ID, typed_data)

        assert signature.startswith("0x")
        print(f"\n✅ 签名成功 / Signing successful: {signature[:20]}...")

        # 提交订单 / Submit order
        signed_order = build_signed_order_payload(order_msg, signature)
        result = clob.submit_order(signed_order, order_type="GTC")

        print(f"✅ 下单结果 / Order result: {result}")
        assert result.get("success") or result.get("orderID")
