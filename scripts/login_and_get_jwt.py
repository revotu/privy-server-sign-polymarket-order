#!/usr/bin/env python3
"""
Privy 测试用户登录工具 / Privy Test User Login Tool
======================================================
通过邮箱 OTP 登录 Privy，获取真实用户的 wallet ID 和 JWT。
Login to Privy via email OTP to get real user's wallet ID and JWT.

用途 / Purpose:
    在不运行 Flutter App 的情况下，获取真实用户 JWT，
    用于测试 /api/bind-signer 接口。
    Get real user JWT without running Flutter App,
    for testing /api/bind-signer endpoint.

使用方法 / Usage:
    python scripts/login_and_get_jwt.py

流程 / Flow:
    1. 输入邮箱 → 收到 Privy OTP 验证码
    2. 输入验证码 → 获得用户 JWT 和 wallet 信息
    3. 将信息用于 bind-signer 测试

注意 / Note:
    此脚本调用的是 Privy 真实认证 API，产生的是真实用户，
    与 Flutter App 登录的用户完全等价。
    This script calls real Privy auth API, creates a real user
    equivalent to logging in via Flutter App.
"""

import json
import os
import sys

# 将 backend 加入 Python 路径 / Add backend to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import httpx

# 加载配置 / Load config
from config import settings


# ----------------------------------------------------------
# Privy 认证 API 常量 / Privy Auth API Constants
# ----------------------------------------------------------
# 注意：认证相关接口用 auth.privy.io，wallet 操作用 api.privy.io
# Note: Auth endpoints use auth.privy.io, wallet ops use api.privy.io
PRIVY_AUTH_BASE = "https://auth.privy.io/api/v1"


def send_otp(email: str) -> None:
    """
    向指定邮箱发送 Privy OTP 验证码。
    Sends a Privy OTP code to the specified email.

    Args:
        email: 用户邮箱地址 / User email address
    """
    url = f"{PRIVY_AUTH_BASE}/passwordless/init"
    payload = {
        "email": email,
        # 告诉 Privy 用邮箱 OTP 方式 / Tell Privy to use email OTP method
        "type": "email",
    }
    headers = {
        "Content-Type": "application/json",
        "privy-app-id": settings.privy_app_id,
        # origin 是 Privy 认证流程必须的 / origin is required by Privy auth flow
        "origin": "http://localhost:3000",
    }

    resp = httpx.post(url, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        print(f"❌ 发送 OTP 失败 / Failed to send OTP: {resp.status_code} {resp.text}")
        sys.exit(1)

    print(f"✅ OTP 已发送到 {email}，请查收邮件 / OTP sent to {email}, check your inbox")


def verify_otp(email: str, code: str) -> dict:
    """
    验证 OTP 完成登录，返回包含 token 和用户信息的字典。
    Verifies OTP to complete login, returns dict with token and user info.

    Args:
        email: 用户邮箱 / User email
        code: 6 位 OTP 验证码 / 6-digit OTP code

    Returns:
        包含 token、user 信息的字典 / Dict with token and user info
    """
    url = f"{PRIVY_AUTH_BASE}/passwordless/authenticate"
    payload = {
        "email": email,
        "code": code,
        # 如果是新用户，自动创建 / Auto-create if new user
        "type": "email",
    }
    headers = {
        "Content-Type": "application/json",
        "privy-app-id": settings.privy_app_id,
        "origin": "http://localhost:3000",
    }

    resp = httpx.post(url, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        print(f"❌ OTP 验证失败 / OTP verification failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    return resp.json()


def get_user_wallets(user_did: str) -> list:
    """
    用服务端凭据获取用户的 wallet 列表。
    Gets user's wallet list using server credentials.

    Args:
        user_did: 用户的 Privy DID（格式：did:privy:xxxx）
                  User's Privy DID (format: did:privy:xxxx)

    Returns:
        wallet 列表 / List of wallets
    """
    url = f"{settings.privy_api_base_url}/users/{user_did}"
    headers = {
        "privy-app-id": settings.privy_app_id,
    }

    resp = httpx.get(
        url,
        auth=(settings.privy_app_id, settings.privy_app_secret),
        headers=headers,
    )

    if resp.status_code != 200:
        print(f"⚠️  获取用户信息失败 / Failed to get user info: {resp.status_code} {resp.text}")
        return []

    user_data = resp.json()
    linked_accounts = user_data.get("linked_accounts", [])

    # 过滤出 ethereum wallet / Filter for ethereum wallets
    wallets = [
        acct for acct in linked_accounts
        if acct.get("type") == "wallet"
        and acct.get("chain_type") == "ethereum"
    ]
    return wallets


def main():
    print("=" * 65)
    print("Privy 测试用户登录工具 / Privy Test User Login Tool")
    print("=" * 65)
    print(f"App ID: {settings.privy_app_id}")
    print("=" * 65)
    print()
    print("此工具会产生一个真实 Privy 用户（与 Flutter App 登录等价）")
    print("This tool creates a real Privy user (equivalent to Flutter App login)")
    print()

    # 步骤 1：输入邮箱 / Step 1: Enter email
    email = input("请输入测试邮箱 / Enter test email: ").strip()
    if not email or "@" not in email:
        print("❌ 邮箱格式不正确 / Invalid email format")
        sys.exit(1)

    print()

    # 步骤 2：发送 OTP / Step 2: Send OTP
    send_otp(email)
    print()

    # 步骤 3：输入 OTP / Step 3: Enter OTP
    code = input("请输入收到的 OTP 验证码 / Enter the OTP code received: ").strip()
    if not code:
        print("❌ 验证码不能为空 / OTP code cannot be empty")
        sys.exit(1)

    print()
    print("验证中 / Verifying...")

    # 步骤 4：验证 OTP / Step 4: Verify OTP
    auth_result = verify_otp(email, code)

    # 提取关键信息 / Extract key info
    access_token = auth_result.get("token", "")
    user = auth_result.get("user", {})
    user_did = user.get("id", "")  # 格式：did:privy:xxxx / Format: did:privy:xxxx

    print(f"✅ 登录成功 / Login successful!")
    print()

    # 步骤 5：获取 wallet 信息 / Step 5: Get wallet info
    # embedded wallet 可能需要一点时间创建
    # embedded wallet might take a moment to create
    linked_accounts = user.get("linked_accounts", [])
    wallets = [
        acct for acct in linked_accounts
        if acct.get("type") == "wallet"
    ]

    # 如果登录响应里没有 wallet，用服务端 API 再查一次
    # If login response has no wallet, query again via server API
    if not wallets and user_did:
        print("查询 wallet 信息中 / Querying wallet info...")
        wallets = get_user_wallets(user_did)

    # ----------------------------------------------------------
    # 输出所有需要的信息 / Output all needed info
    # ----------------------------------------------------------
    print("=" * 65)
    print("✅ 以下是测试所需的所有信息 / All info needed for testing:")
    print("=" * 65)
    print()
    print(f"【用户 JWT / User JWT】（用于 bind-signer）")
    print(f"{access_token}")
    print()
    print(f"【用户 DID / User DID】")
    print(f"{user_did}")
    print()

    if wallets:
        wallet = wallets[0]
        wallet_id = wallet.get("id", "N/A")       # 格式：wallet_xxxx
        wallet_address = wallet.get("address", "N/A")  # 0x 地址

        print(f"【Wallet ID】（用于所有 API 调用）")
        print(f"{wallet_id}")
        print()
        print(f"【Wallet Address】（用于订单 maker/signer）")
        print(f"{wallet_address}")
        print()
        print(f"【delegated / signer 绑定状态】")
        print(f"{wallet.get('delegated', False)}")
        print()

        # 保存到文件供后续使用 / Save to file for later use
        test_info = {
            "email": email,
            "user_did": user_did,
            "user_jwt": access_token,
            "wallet_id": wallet_id,
            "wallet_address": wallet_address,
            "delegated": wallet.get("delegated", False),
        }

        output_file = os.path.join(os.path.dirname(__file__), "test_user_info.json")
        with open(output_file, "w") as f:
            json.dump(test_info, f, indent=2)

        print(f"✅ 信息已保存到 / Saved to: scripts/test_user_info.json")
        print()
        print("⚠️  注意 / NOTE:")
        print("   test_user_info.json 已加入 .gitignore，不会提交到 git")
        print("   test_user_info.json is in .gitignore, will not be committed")
    else:
        print("⚠️  暂时未找到 wallet，可能正在创建中。")
        print("   请稍等片刻后在 Privy Dashboard 查看用户的 wallet ID。")
        print("   No wallet found yet, may still be creating.")
        print("   Check user's wallet ID in Privy Dashboard after a moment.")
        print()
        # 即使没有 wallet，也保存 JWT / Save JWT even without wallet
        test_info = {
            "email": email,
            "user_did": user_did,
            "user_jwt": access_token,
            "wallet_id": "",
            "wallet_address": "",
        }
        output_file = os.path.join(os.path.dirname(__file__), "test_user_info.json")
        with open(output_file, "w") as f:
            json.dump(test_info, f, indent=2)

    print("=" * 65)
    print()
    print("下一步 / Next Steps:")
    print("  1. 用以上 wallet_id 和 user_jwt 调用 /api/bind-signer")
    print("  2. 绑定成功后调用 /api/place-order 测试无弹窗下单")
    print()
    print("curl 示例 / curl example:")
    if wallets:
        wallet_id = wallets[0].get("id", "WALLET_ID")
        print(f"""
  curl -X POST http://localhost:8000/api/bind-signer \\
    -H "Content-Type: application/json" \\
    -d '{{
      "wallet_id": "{wallet_id}",
      "user_jwt": "{access_token[:40]}..."
    }}'
""")


if __name__ == "__main__":
    main()
