#!/usr/bin/env python3
"""
Privy 测试用户创建工具 / Privy Test User Creation Tool
=========================================================
通过 Privy admin API 创建测试用户，同时创建 embedded wallet 并预绑定 Key Quorum signer。
Creates a test user via Privy admin API with embedded wallet and Key Quorum signer pre-bound.

与 openclaw 的测试用户创建方式完全相同：
Identical to how openclaw creates test users:
    - 邮箱格式：test.user+{timestamp}@example.com
    - 同时创建 embedded Ethereum wallet
    - 创建时直接绑定 Key Quorum（省去生产环境的 bind-signer 步骤）

用途 / Purpose:
    快速创建可用于测试服务端签名（sign_typed_data）的测试用户，
    无需走 OTP 流程，无需 Flutter App。
    Quickly create test users for testing server-side signing (sign_typed_data),
    no OTP flow needed, no Flutter App required.

使用方法 / Usage:
    python scripts/create_test_user.py

输出 / Output:
    打印并保存 user_did, wallet_id, wallet_address 到 scripts/test_user_info.json
    Prints and saves user_did, wallet_id, wallet_address to scripts/test_user_info.json

注意 / Note:
    此脚本创建的是真实 Privy 用户（非沙盒），与 Flutter App 登录的用户架构完全相同。
    This creates real Privy users (not sandbox), architecturally identical to Flutter App users.
    区别仅在于 signer 在创建时预绑定，而非通过 bind-signer 接口绑定。
    Difference: signer is pre-bound at creation, vs bound via bind-signer endpoint.
"""

import json
import os
import sys
import time

# 将 backend 加入 Python 路径 / Add backend to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import httpx
from config import settings
from privy.auth_signature import compute_authorization_signature


def create_test_user_with_wallet(email: str) -> dict:
    """
    通过 Privy admin API 创建测试用户，同时创建 embedded wallet 并绑定 Key Quorum。
    Creates a test user via Privy admin API with embedded wallet and Key Quorum bound.

    API 端点 / API Endpoint: POST https://api.privy.io/v1/users
    鉴权 / Auth: Basic(app_id:app_secret) + privy-authorization-signature(P256)

    关键：在 wallets[].additional_signers 中指定 Key Quorum ID，
    这样创建完成后服务端就能直接代签，无需走 bind-signer 流程。
    Key: specify Key Quorum ID in wallets[].additional_signers,
    so the server can sign immediately after creation, no bind-signer needed.

    Args:
        email: 测试用户邮箱（格式：test.user+{timestamp}@example.com）
               Test user email (format: test.user+{timestamp}@example.com)

    Returns:
        Privy API 响应，包含 user id 和 linked_accounts（含 wallet）
        Privy API response with user id and linked_accounts (including wallet)
    """
    url = f"{settings.privy_api_base_url}/users"

    body = {
        # 绑定邮箱作为登录方式 / Bind email as login method
        "linked_accounts": [
            {
                "type": "email",
                "address": email,
            }
        ],
        # 同时创建 embedded Ethereum wallet / Also create embedded Ethereum wallet
        "wallets": [
            {
                "chain_type": "ethereum",
                # ★ 关键：创建时直接绑定 Key Quorum 为 signer
                # ★ Key: directly bind Key Quorum as signer at creation time
                # 这样服务端 P256 私钥可以立即代替用户签名（无弹窗！）
                # This allows server P256 key to immediately sign for the user (no popup!)
                "additional_signers": [
                    {
                        "signer_id": settings.privy_key_quorum_id,
                    }
                ],
            }
        ],
    }

    # 计算 P256 授权签名 / Compute P256 authorization signature
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
        # 授权签名让 Privy 知道这是来自授权方的合法请求
        # Authorization signature tells Privy this is a legitimate authorized request
        "privy-authorization-signature": auth_signature,
    }

    resp = httpx.post(
        url,
        json=body,
        auth=(settings.privy_app_id, settings.privy_app_secret),
        headers=headers,
    )

    if resp.status_code not in (200, 201):
        print(f"❌ 创建用户失败 / Failed to create user: {resp.status_code}")
        print(f"   响应 / Response: {resp.text}")
        sys.exit(1)

    return resp.json()


def get_wallet_from_user(user_data: dict) -> dict | None:
    """
    从用户数据中提取 wallet 信息。
    Extracts wallet information from user data.

    有时 wallet 在 linked_accounts 中，有时在 wallets 字段中。
    Sometimes wallet is in linked_accounts, sometimes in wallets field.
    """
    # 先检查 linked_accounts / Check linked_accounts first
    linked_accounts = user_data.get("linked_accounts", [])
    for account in linked_accounts:
        if account.get("type") == "wallet" and account.get("chain_type") == "ethereum":
            return account

    # 再检查顶级 wallets 字段 / Then check top-level wallets field
    wallets = user_data.get("wallets", [])
    if wallets:
        return wallets[0]

    return None


def main():
    print("=" * 65)
    print("Privy 测试用户创建工具 / Privy Test User Creation Tool")
    print("=" * 65)
    print(f"App ID: {settings.privy_app_id}")
    print(f"Key Quorum ID: {settings.privy_key_quorum_id}")
    print("=" * 65)
    print()

    # 生成唯一邮箱（与 openclaw 的格式一致）
    # Generate unique email (same format as openclaw)
    timestamp = int(time.time())
    email = f"test.user+{timestamp}@example.com"

    print(f"创建测试用户 / Creating test user: {email}")
    print("（同时创建 embedded wallet + 绑定 Key Quorum signer）")
    print("（Creating embedded wallet + binding Key Quorum signer simultaneously）")
    print()

    # 调用 Privy API 创建用户 / Call Privy API to create user
    user_data = create_test_user_with_wallet(email)

    # 提取用户信息 / Extract user info
    user_did = user_data.get("id", "")  # 格式：did:privy:xxxx

    print(f"✅ 用户创建成功 / User created successfully!")
    print(f"   User DID: {user_did}")
    print()

    # 提取 wallet 信息 / Extract wallet info
    wallet = get_wallet_from_user(user_data)

    if not wallet:
        print("⚠️  响应中未找到 wallet，请检查 Privy Dashboard")
        print("⚠️  No wallet found in response, check Privy Dashboard")
        print()
        print("完整响应 / Full response:")
        print(json.dumps(user_data, indent=2))
        sys.exit(1)

    wallet_id = wallet.get("id", "")
    wallet_address = wallet.get("address", "")
    delegated = wallet.get("delegated", False)

    print(f"✅ Wallet 创建成功 / Wallet created successfully!")
    print(f"   Wallet ID:      {wallet_id}")
    print(f"   Wallet Address: {wallet_address}")
    print(f"   Delegated (signer bound): {delegated}")
    print()

    # 保存到文件 / Save to file
    test_info = {
        "email": email,
        "user_did": user_did,
        "wallet_id": wallet_id,
        "wallet_address": wallet_address,
        "delegated": delegated,
        "key_quorum_id": settings.privy_key_quorum_id,
        "created_at": timestamp,
        "note": (
            "signer pre-bound at creation via additional_signers. "
            "Server can sign immediately without bind-signer step."
        ),
    }

    output_file = os.path.join(os.path.dirname(__file__), "test_user_info.json")
    with open(output_file, "w") as f:
        json.dump(test_info, f, indent=2)

    print(f"✅ 信息已保存到 / Saved to: scripts/test_user_info.json")
    print()

    # 打印测试命令 / Print test commands
    print("=" * 65)
    print("下一步：测试服务端代签 / Next: Test server-side signing")
    print("=" * 65)
    print()
    print("运行签名测试脚本 / Run signing test script:")
    print(f"  python scripts/test_signing.py")
    print()
    print("或直接 curl 测试后端 / Or test backend directly with curl:")
    print(f"""
  curl -X POST http://localhost:8000/api/place-order \\
    -H "Content-Type: application/json" \\
    -d '{{
      "wallet_id": "{wallet_id}",
      "wallet_address": "{wallet_address}",
      "condition_id": "0x...",
      "side": "BUY",
      "price": 0.01,
      "size": 1.0,
      "clob_api_key": "your_clob_api_key",
      "clob_api_secret": "your_clob_api_secret",
      "clob_api_passphrase": "your_clob_api_passphrase"
    }}'
""")


if __name__ == "__main__":
    main()
