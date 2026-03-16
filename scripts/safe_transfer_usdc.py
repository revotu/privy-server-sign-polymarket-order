"""
Safe 无 gas USDC 转账脚本 / Safe Gasless USDC Transfer Script
============================================================
通过 Polymarket Relayer 从 Gnosis Safe 转移 USDC.e 到任意地址（无需 ETH gas）。
Transfer USDC.e from Gnosis Safe to any address via Polymarket Relayer (no ETH gas needed).

签名方案 / Signing Scheme:
    Safe 主动发起的链上操作（如 transfer、approve）必须使用 personal_sign：
    Safe-initiated on-chain operations (e.g., transfer, approve) must use personal_sign:
        1. 计算 SafeTx EIP-712 哈希（compute_safe_tx_hash）
           Compute SafeTx EIP-712 hash (compute_safe_tx_hash)
        2. Privy sign_message 签名（personal_sign，传 hex 去掉 0x 前缀，返回 v=27/28）
           Privy sign_message (personal_sign, pass hex without 0x prefix, returns v=27/28)
        3. split_and_pack_sig 将 v 从 27/28 转换为 31/32（Relayer 要求）
           split_and_pack_sig converts v from 27/28 to 31/32 (Relayer requirement)
        4. 提交 Relayer /submit（type="SAFE"）
           Submit to Relayer /submit (type="SAFE")

    注意：下单签名使用 sign_typed_data（EIP-712 order），与此处不同。
    Note: Order signing uses sign_typed_data (EIP-712 order), different from here.

使用方法 / Usage:
    python scripts/safe_transfer_usdc.py \\
        --wallet-id <privy_wallet_id> \\
        --eoa <eoa_address> \\
        --recipient <recipient_address> \\
        --amount <usdc_amount_in_human_units>

    示例 / Example:
        python scripts/safe_transfer_usdc.py \\
            --wallet-id y7eruc2xt996pwpg4xyy4uya \\
            --eoa 0xcf0C4f62C2Bb98BD14Cf841e22c9E7D5a639112B \\
            --recipient 0x5964aa28089c39f4b58ba49ceb71eed53bbf3b3f \\
            --amount 1.92

环境变量依赖 / Required env vars:
    PRIVY_APP_ID, PRIVY_APP_SECRET, PRIVY_AUTHORIZATION_KEY, PRIVY_KEY_QUORUM_ID
    POLYMARKET_BUILDER_API_KEY, POLYMARKET_BUILDER_SECRET, POLYMARKET_BUILDER_PASSPHRASE
    SAFE_PROXY_FACTORY_ADDRESS, USDC_ADDRESS, RELAYER_HOST
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from eth_abi import encode as abi_encode
from web3 import Web3

from config import settings
from polymarket.relayer_client import compute_safe_tx_hash, relayer_client, split_and_pack_sig
from polymarket.safe_wallet import derive_safe_address
from privy.client import privy_client

# ERC-20 transfer(address,uint256) 4-byte 函数选择器
# ERC-20 transfer(address,uint256) 4-byte function selector
TRANSFER_SELECTOR = bytes.fromhex("a9059cbb")

# USDC.e 精度（6 位小数）/ USDC.e decimals (6)
USDC_DECIMALS = 6


def build_usdc_transfer_data(recipient: str, amount_human: float) -> str:
    """
    构建 USDC.transfer(recipient, amount) 的 calldata。
    Builds calldata for USDC.transfer(recipient, amount).

    Args:
        recipient: 收款地址 / Recipient address
        amount_human: 转账金额（以 USDC 为单位，如 1.92）/ Transfer amount in USDC units (e.g., 1.92)

    Returns:
        十六进制 calldata 字符串（含 0x 前缀）/ Hex calldata string (with 0x prefix)
    """
    amount_raw = int(amount_human * (10 ** USDC_DECIMALS))
    encoded = abi_encode(
        ["address", "uint256"],
        [Web3.to_checksum_address(recipient), amount_raw],
    )
    return "0x" + (TRANSFER_SELECTOR + encoded).hex()


def transfer_usdc(
    wallet_id: str,
    eoa_address: str,
    recipient: str,
    amount_human: float,
    usdc_address: str = None,
    dry_run: bool = False,
) -> dict:
    """
    从用户 Safe 向指定地址转移 USDC.e（通过 Polymarket Relayer，无需 ETH gas）。
    Transfer USDC.e from user's Safe to specified address via Polymarket Relayer (no ETH gas).

    Args:
        wallet_id: Privy 钱包 ID（Safe owner 的 EOA）/ Privy wallet ID (EOA of Safe owner)
        eoa_address: Safe owner 的 EOA 地址 / EOA address of Safe owner
        recipient: 收款地址 / Recipient address
        amount_human: 转账金额（USDC 单位）/ Transfer amount (USDC units)
        usdc_address: USDC.e 合约地址（默认从 settings 读取）/ USDC.e contract address
        dry_run: 仅打印信息，不实际提交 / Print info only, do not submit

    Returns:
        Relayer 最终交易状态 / Relayer final transaction status
    """
    if usdc_address is None:
        usdc_address = settings.usdc_address

    safe_address = derive_safe_address(eoa_address)
    amount_raw = int(amount_human * (10 ** USDC_DECIMALS))

    print(f"EOA 地址   / EOA Address:    {eoa_address}")
    print(f"Safe 地址  / Safe Address:   {safe_address}")
    print(f"收款地址   / Recipient:      {recipient}")
    print(f"转账金额   / Amount:         {amount_human} USDC ({amount_raw} raw)")
    print(f"USDC 合约  / USDC Contract:  {usdc_address}")
    print()

    # 1. 构建 transfer calldata
    transfer_data = build_usdc_transfer_data(recipient, amount_human)
    print(f"Transfer calldata: {transfer_data}")

    # 2. 获取 Safe 当前 nonce
    safe_nonce = relayer_client.get_safe_nonce(eoa_address)
    print(f"Safe nonce: {safe_nonce}")

    # 3. 计算 SafeTx EIP-712 哈希
    safe_tx_hash = compute_safe_tx_hash(
        safe_address=safe_address,
        to=usdc_address,
        data=transfer_data,
        value=0,
        nonce=int(safe_nonce),
    )
    print(f"SafeTx hash: {safe_tx_hash}")

    if dry_run:
        print("\n[DRY RUN] 不提交交易 / Not submitting transaction")
        return {"dry_run": True, "safe_tx_hash": safe_tx_hash}

    # 4. Privy personal_sign 签名（传入 hex 去掉 0x 前缀）
    #    Privy personal_sign (pass hex without 0x prefix)
    hash_without_prefix = safe_tx_hash[2:] if safe_tx_hash.startswith("0x") else safe_tx_hash
    raw_sig = privy_client.sign_message(wallet_id=wallet_id, message_hash=hash_without_prefix)
    print(f"Raw signature (v=27/28): {raw_sig[:20]}...")

    # 5. 转换签名格式：v=27/28 → v=31/32（Relayer 要求）
    #    Convert signature: v=27/28 → v=31/32 (Relayer requirement)
    packed_sig = split_and_pack_sig(raw_sig)
    print(f"Packed signature (v=31/32): {packed_sig[:20]}...")

    # 6. 提交 Relayer
    print("\n提交 Relayer / Submitting to Relayer...")
    result = relayer_client.execute_safe_transaction(
        eoa_address=eoa_address,
        safe_address=safe_address,
        to=usdc_address,
        data=transfer_data,
        signature=packed_sig,
        nonce=safe_nonce,
        value=0,
    )
    tx_id = result.get("transactionID", result.get("id", ""))
    tx_hash = result.get("transactionHash", "")
    print(f"Transaction ID:   {tx_id}")
    print(f"Transaction Hash: {tx_hash}")
    print(f"Initial state:    {result.get('state', '')}")

    # 7. 等待链上确认
    print("\n等待链上确认 / Waiting for on-chain confirmation...")
    final_status = relayer_client.wait_for_tx(tx_id, timeout_seconds=120)
    print(f"最终状态 / Final state: {final_status.get('state', '')}")
    return final_status


def main():
    parser = argparse.ArgumentParser(
        description="从 Gnosis Safe 无 gas 转移 USDC.e / Transfer USDC.e from Safe without gas"
    )
    parser.add_argument("--wallet-id", required=True, help="Privy wallet ID (EOA)")
    parser.add_argument("--eoa", required=True, help="EOA address (Safe owner)")
    parser.add_argument("--recipient", required=True, help="Recipient address")
    parser.add_argument(
        "--amount", type=float, required=True, help="Amount in USDC (e.g., 1.92)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只计算哈希，不提交 / Only compute hash, do not submit",
    )
    args = parser.parse_args()

    transfer_usdc(
        wallet_id=args.wallet_id,
        eoa_address=args.eoa,
        recipient=args.recipient,
        amount_human=args.amount,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
