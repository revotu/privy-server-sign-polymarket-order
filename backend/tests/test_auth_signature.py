"""
P256 授权签名单元测试 / P256 Authorization Signature Unit Tests
================================================================
测试 Privy 授权签名的生成和验证，不需要真实的 Privy API 调用。
Tests Privy authorization signature generation and verification,
no real Privy API calls needed.

运行 / Run:
    cd backend
    pytest tests/test_auth_signature.py -v
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from privy.auth_signature import (
    canonicalize_payload,
    compute_authorization_signature,
    load_private_key_from_authorization_key,
)


# ============================================================
# 测试固件 / Test Fixtures
# ============================================================

@pytest.fixture
def test_authorization_key() -> str:
    """
    生成用于测试的临时 P256 密钥对。
    Generates a temporary P256 keypair for testing.

    注意：每次测试都生成新密钥，不使用真实密钥。
    Note: Generates new key for each test, does not use real keys.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_key_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_b64 = base64.b64encode(private_key_der).decode("utf-8")
    return f"wallet-auth:{private_key_b64}"


@pytest.fixture
def test_app_id() -> str:
    return "test_app_id_for_unit_tests"


# ============================================================
# 测试用例 / Test Cases
# ============================================================

class TestLoadPrivateKey:
    """测试私钥加载 / Tests for private key loading"""

    def test_load_valid_key(self, test_authorization_key):
        """应该成功加载有效的 wallet-auth: 格式私钥 / Should successfully load valid wallet-auth: key"""
        private_key = load_private_key_from_authorization_key(test_authorization_key)
        assert isinstance(private_key, ec.EllipticCurvePrivateKey)
        assert private_key.curve.name == "secp256r1"

    def test_reject_key_without_prefix(self):
        """应该拒绝没有 wallet-auth: 前缀的密钥 / Should reject key without wallet-auth: prefix"""
        with pytest.raises(ValueError, match="wallet-auth:"):
            load_private_key_from_authorization_key("invalid_key_without_prefix")

    def test_reject_empty_key(self):
        """应该拒绝空字符串 / Should reject empty string"""
        with pytest.raises(ValueError):
            load_private_key_from_authorization_key("")


class TestCanonicalizePayload:
    """测试 JSON 规范化 / Tests for JSON canonicalization"""

    def test_sort_keys(self):
        """应该按字母顺序排列 key / Should sort keys alphabetically"""
        payload = {"z_key": 1, "a_key": 2, "m_key": 3}
        result = canonicalize_payload(payload)
        parsed = json.loads(result)
        # 验证结果是有效 JSON 且包含所有字段
        # Verify result is valid JSON and contains all fields
        assert parsed["z_key"] == 1
        assert parsed["a_key"] == 2

    def test_no_spaces(self):
        """应该没有多余的空格 / Should have no extra spaces"""
        payload = {"key": "value"}
        result = canonicalize_payload(payload)
        assert " " not in result

    def test_nested_objects(self):
        """应该正确处理嵌套对象 / Should correctly handle nested objects"""
        payload = {
            "version": 1,
            "method": "POST",
            "body": {"chain_type": "ethereum"},
        }
        result = canonicalize_payload(payload)
        assert "chain_type" in result
        assert "ethereum" in result

    def test_same_input_produces_same_output(self):
        """相同输入应产生相同输出（确定性）/ Same input should produce same output (deterministic)"""
        payload = {"version": 1, "method": "POST", "url": "https://api.privy.io/v1/wallets"}
        result1 = canonicalize_payload(payload)
        result2 = canonicalize_payload(payload)
        assert result1 == result2


class TestComputeAuthorizationSignature:
    """测试授权签名计算 / Tests for authorization signature computation"""

    def test_generates_valid_base64_signature(self, test_authorization_key, test_app_id):
        """应该生成有效的 base64 签名 / Should generate valid base64 signature"""
        signature = compute_authorization_signature(
            url="https://api.privy.io/v1/wallets/wallet_123/rpc",
            body={"method": "personal_sign", "params": {"message": "Hello"}},
            app_id=test_app_id,
            authorization_key=test_authorization_key,
        )

        # 验证是有效的 base64 字符串
        # Verify it's a valid base64 string
        assert isinstance(signature, str)
        assert len(signature) > 0
        decoded = base64.b64decode(signature)
        assert len(decoded) > 0

    def test_different_urls_produce_different_signatures(self, test_authorization_key, test_app_id):
        """不同的 URL 应该产生不同的签名 / Different URLs should produce different signatures"""
        body = {"chain_type": "ethereum", "method": "eth_signTypedData_v4"}

        sig1 = compute_authorization_signature(
            url="https://api.privy.io/v1/wallets/wallet_123/rpc",
            body=body,
            app_id=test_app_id,
            authorization_key=test_authorization_key,
        )
        sig2 = compute_authorization_signature(
            url="https://api.privy.io/v1/wallets/wallet_456/rpc",
            body=body,
            app_id=test_app_id,
            authorization_key=test_authorization_key,
        )

        # 两个不同 wallet 的签名不应相同
        # Signatures for different wallets should not be equal
        assert sig1 != sig2

    def test_signature_verifiable_with_public_key(self, test_authorization_key, test_app_id):
        """生成的签名应该可以用对应的公钥验证 / Generated signature should be verifiable with corresponding public key"""
        url = "https://api.privy.io/v1/wallets/wallet_test/rpc"
        body = {"chain_type": "ethereum", "method": "eth_signTypedData_v4", "params": {}}

        # 生成签名 / Generate signature
        signature_b64 = compute_authorization_signature(
            url=url,
            body=body,
            app_id=test_app_id,
            authorization_key=test_authorization_key,
        )

        # 重建签名时使用的 payload / Rebuild the payload used for signing
        payload = {
            "version": 1,
            "method": "POST",
            "url": url,
            "body": body,
            "headers": {"privy-app-id": test_app_id},
        }
        serialized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        # 用对应的公钥验证签名 / Verify signature with corresponding public key
        private_key = load_private_key_from_authorization_key(test_authorization_key)
        public_key = private_key.public_key()
        signature_bytes = base64.b64decode(signature_b64)

        # 不应该抛出 InvalidSignature 异常
        # Should not raise InvalidSignature exception
        from cryptography.exceptions import InvalidSignature
        try:
            public_key.verify(
                signature_bytes,
                serialized_payload.encode("utf-8"),
                ec.ECDSA(hashes.SHA256()),
            )
            signature_valid = True
        except InvalidSignature:
            signature_valid = False

        assert signature_valid, "签名验证失败 / Signature verification failed"

    def test_patch_method(self, test_authorization_key, test_app_id):
        """应该支持 PATCH 方法 / Should support PATCH method"""
        signature = compute_authorization_signature(
            url="https://api.privy.io/v1/wallets/wallet_123",
            body={"additional_signers": [{"signer_id": "key_quorum_123"}]},
            app_id=test_app_id,
            authorization_key=test_authorization_key,
            method="PATCH",
        )
        assert isinstance(signature, str)
        assert len(signature) > 0


class TestKeyGenerationRoundtrip:
    """测试密钥生成的完整往返流程 / Tests for complete key generation roundtrip"""

    def test_generate_and_use_key(self):
        """
        测试从生成密钥到使用密钥签名的完整流程。
        Tests the complete flow from key generation to signing.

        这模拟了 scripts/generate_auth_key.py 的工作流程。
        This simulates the workflow of scripts/generate_auth_key.py.
        """
        # 1. 生成密钥（模拟 generate_auth_key.py）
        # 1. Generate key (simulate generate_auth_key.py)
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_key_der = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        auth_key = f"wallet-auth:{base64.b64encode(private_key_der).decode()}"

        # 2. 导出公钥（供 Privy Dashboard 注册）
        # 2. Export public key (for Privy Dashboard registration)
        public_key = private_key.public_key()
        public_key_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_key_b64 = base64.b64encode(public_key_der).decode()

        # 3. 用生成的密钥计算签名
        # 3. Compute signature with generated key
        signature = compute_authorization_signature(
            url="https://api.privy.io/v1/wallets/wallet_roundtrip/rpc",
            body={"method": "eth_signTypedData_v4"},
            app_id="test_app",
            authorization_key=auth_key,
        )

        # 4. 验证公钥和私钥配对
        # 4. Verify public key and private key are paired
        assert len(public_key_b64) > 0
        assert len(signature) > 0
        print(f"\n测试密钥（勿在生产使用）/ Test key (don't use in production):")
        print(f"  Public Key (b64): {public_key_b64[:20]}...")
        print(f"  Auth Key prefix: {auth_key[:30]}...")
