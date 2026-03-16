"""
调试 Builder/Safe 方案 / Debug Builder/Safe Scheme
===================================================
1. 测试 place-order-builder（不需要 USDC 余额，只验证签名和 Builder 头格式）
2. 测试 SAFE 执行（USDC approve），验证 Relayer 接受签名格式

签名方案说明 / Signing Scheme:
    - Safe 交易签名使用 personal_sign（Privy sign_message，传 hex 去掉 0x 前缀）
      Safe tx signing uses personal_sign (Privy sign_message, pass hex without 0x prefix)
    - personal_sign 返回 v=27/28，经 split_and_pack_sig 转换为 v=31/32
      personal_sign returns v=27/28; split_and_pack_sig converts to v=31/32
    - Relayer 仅接受 v=31/32（eth_sign 格式），拒绝 v=27/28
      Relayer only accepts v=31/32 (eth_sign format), rejects v=27/28
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import httpx
from eth_account import Account
from eth_utils import keccak
from config import settings
from polymarket.clob_auth import build_clob_auth_typed_data, derive_api_credentials
from polymarket.clob_client import ClobApiClient
from polymarket.order_builder import (
    SIG_TYPE_GNOSIS_SAFE,
    build_eip712_typed_data,
    build_order_message,
    build_signed_order_payload,
)
from polymarket.relayer_client import (
    compute_safe_tx_hash,
    relayer_client,
    split_and_pack_sig,
)
from polymarket.safe_wallet import build_safe_approve_usdc_tx_data, derive_safe_address
from polymarket.builder_auth import build_builder_headers
from privy.client import PrivyWalletClient, privy_client

# ============================================================
# 测试用户信息 / Test user info
# ============================================================
test_info_path = os.path.join(os.path.dirname(__file__), "test_user_info.json")
with open(test_info_path) as f:
    test_info = json.load(f)

WALLET_ID = test_info["wallet_id"]
EOA_ADDRESS = test_info["wallet_address"]
SAFE_ADDRESS = derive_safe_address(EOA_ADDRESS)

print(f"EOA:  {EOA_ADDRESS}")
print(f"Safe: {SAFE_ADDRESS}")
print()


def derive_clob_credentials():
    """Re-derive CLOB credentials."""
    print("=== Deriving CLOB credentials ===")
    timestamp = str(int(time.time()))
    clob_auth = build_clob_auth_typed_data(wallet_address=EOA_ADDRESS, timestamp=timestamp)
    sig = privy_client.sign_typed_data(wallet_id=WALLET_ID, typed_data=clob_auth)
    creds = derive_api_credentials(
        wallet_address=EOA_ADDRESS,
        auth_signature=sig,
        timestamp=timestamp,
    )
    print(f"  api_key: {creds['api_key'][:8]}...")
    return creds


def test_place_order_builder(clob_creds):
    """Test Builder order placement (maker=Safe, signer=EOA, signatureType=2)."""
    print("\n=== Test: place-order-builder ===")

    clob = ClobApiClient(
        api_key=clob_creds["api_key"],
        api_secret=clob_creds["api_secret"],
        api_passphrase=clob_creds["api_passphrase"],
    )

    # Get an active market
    condition_id = "0xd65891729ce093cc12236856837eba1a0872fc7998fd4294c21346f7db68079c"
    try:
        market = clob.get_market(condition_id)
        tokens = market.get("tokens", [])
        if not tokens:
            print("  No tokens in market")
            return
        token_id = tokens[0]["token_id"]
        neg_risk = market.get("neg_risk", False)
        fee_rate_bps = clob.get_fee_rate(token_id)
        print(f"  Market: neg_risk={neg_risk}, fee={fee_rate_bps}bps")
    except Exception as e:
        print(f"  Market error: {e}")
        return

    # Build order: maker=Safe, signer=EOA, signatureType=2
    order_message = build_order_message(
        maker_address=SAFE_ADDRESS,
        signer_address=EOA_ADDRESS,
        token_id=token_id,
        side="BUY",
        price=0.038,
        size=30,
        fee_rate_bps=fee_rate_bps,
        signature_type=SIG_TYPE_GNOSIS_SAFE,
    )
    print(f"  maker: {order_message['maker']}")
    print(f"  signer: {order_message['signer']}")
    print(f"  signatureType: {order_message['signatureType']}")

    typed_data = build_eip712_typed_data(order_message, neg_risk=neg_risk)

    # Sign via Privy
    signature = privy_client.sign_typed_data(wallet_id=WALLET_ID, typed_data=typed_data)
    print(f"  Signature: {signature[:20]}...")

    signed_order = build_signed_order_payload(order_message, signature)

    # Build builder headers
    body_str = json.dumps(
        {"order": signed_order, "owner": clob_creds["api_key"], "orderType": "GTC", "postOnly": False},
        separators=(",", ":"),
    )
    builder_hdrs = build_builder_headers("POST", "/order", body_str)

    # Submit
    try:
        from polymarket.clob_auth import build_l2_headers
        body_str2 = json.dumps(
            {"order": signed_order, "owner": clob_creds["api_key"], "orderType": "GTC", "postOnly": False},
            separators=(",", ":"),
        )
        headers2 = build_l2_headers(
            api_key=clob_creds["api_key"],
            api_secret=clob_creds["api_secret"],
            api_passphrase=clob_creds["api_passphrase"],
            method="POST",
            request_path="/order",
            body=body_str2,
            wallet_address=EOA_ADDRESS,
        )
        headers2.update(builder_hdrs)
        with httpx.Client() as client:
            resp = client.post(
                "https://clob.polymarket.com/order",
                content=body_str2,
                headers=headers2,
            )
        print(f"  CLOB status: {resp.status_code}")
        print(f"  CLOB response: {resp.text}")
        if resp.is_success:
            result = resp.json()
            if result.get("success"):
                print("  ✅ Order placed!")
            else:
                err = result.get("errorMsg", "")
                print(f"  error={err}")
                if "balance" in err.lower() or "allowance" in err.lower():
                    print("  ✅ Signature + Builder headers correct (not enough balance/allowance as expected)")
    except Exception as e:
        print(f"  Error: {e}")


def debug_safe_execution():
    """Debug SAFE execution - test personal_sign (without 0x) + split_and_pack_sig (v=31/32)."""
    print("\n=== Debug: SAFE execution (USDC approve) ===")

    deployed = relayer_client.check_deployed(SAFE_ADDRESS)
    print(f"  Safe deployed: {deployed}")

    nonce_str = relayer_client.get_safe_nonce(EOA_ADDRESS)
    nonce = int(nonce_str)
    print(f"  Current nonce: {nonce_str}")

    approve_tx = build_safe_approve_usdc_tx_data()
    print(f"  to: {approve_tx['to']}")
    print(f"  data: {approve_tx['data'][:20]}...")

    # ---- Correct Approach: personal_sign (without 0x) + split_and_pack_sig (v=31/32) ----
    print("\n--- Correct Approach: personal_sign (no 0x) + split_and_pack_sig (v=31/32) ---")

    safe_tx_hash = compute_safe_tx_hash(
        safe_address=SAFE_ADDRESS,
        to=approve_tx["to"],
        data=approve_tx["data"],
        nonce=nonce,
    )
    print(f"  safeTxHash: {safe_tx_hash}")

    # sign_message strips "0x" prefix internally before calling Privy personal_sign
    raw_sig = privy_client.sign_message(wallet_id=WALLET_ID, message_hash=safe_tx_hash)
    print(f"  raw_sig (personal_sign): {raw_sig[:20]}... (v={int(raw_sig[-2:], 16)})")

    # Verify raw_sig recovers to EOA via standard personal_sign prefix
    from eth_account.messages import defunct_hash_message
    sig_bytes = bytes.fromhex(raw_sig[2:])
    v_raw = sig_bytes[64]
    msg_hash = defunct_hash_message(bytes.fromhex(safe_tx_hash[2:]))
    try:
        recovered_raw = Account._recover_hash(
            msg_hash,
            vrs=(v_raw, int.from_bytes(sig_bytes[:32], 'big'), int.from_bytes(sig_bytes[32:64], 'big')),
        )
        print(f"  Recovered (personal_sign): {recovered_raw}")
        print(f"  Matches EOA: {recovered_raw.lower() == EOA_ADDRESS.lower()}")
        if recovered_raw.lower() != EOA_ADDRESS.lower():
            print("  ⚠️  Recovery mismatch! Aborting.")
            return
    except Exception as e:
        print(f"  Recovery error: {e}")
        return

    packed_sig = split_and_pack_sig(raw_sig)
    print(f"  packed_sig (split_and_pack): {packed_sig[:20]}... (v={int(packed_sig[-2:], 16)})")

    print("\n  Submitting to Relayer...")
    try:
        result = relayer_client.execute_safe_transaction(
            eoa_address=EOA_ADDRESS,
            safe_address=SAFE_ADDRESS,
            to=approve_tx["to"],
            data=approve_tx["data"],
            signature=packed_sig,
            nonce=nonce_str,
        )
        tx_id = result.get("transactionID", "")
        tx_hash = result.get("transactionHash", "")
        print(f"  ✅ Accepted! transactionID={tx_id}")
        print(f"  transactionHash={tx_hash}")

        if tx_id:
            print("\n  Waiting for confirmation...")
            try:
                status = relayer_client.wait_for_tx(tx_id, timeout_seconds=120)
                print(f"  ✅ Confirmed! state={status.get('state')}")
            except RuntimeError as e:
                print(f"  ⚠️  Failed on-chain: {e}")
            except TimeoutError as e:
                print(f"  ⚠️  Timeout: {e}")
    except httpx.HTTPStatusError as e:
        print(f"  ❌ HTTP error: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"  ❌ Error: {e}")


def approve_neg_risk_exchange():
    """Approve USDC for Neg Risk CTF Exchange (needed for neg_risk=True markets)."""
    print("\n=== Approve USDC for Neg Risk CTF Exchange ===")

    nonce_str = relayer_client.get_safe_nonce(EOA_ADDRESS)
    nonce = int(nonce_str)
    print(f"  Current nonce: {nonce_str}")

    approve_tx = build_safe_approve_usdc_tx_data(
        spender_address=settings.polymarket_neg_risk_ctf_exchange_address,
    )
    print(f"  Approving spender: {settings.polymarket_neg_risk_ctf_exchange_address}")

    safe_tx_hash = compute_safe_tx_hash(
        safe_address=SAFE_ADDRESS,
        to=approve_tx["to"],
        data=approve_tx["data"],
        nonce=nonce,
    )
    raw_sig = privy_client.sign_message(wallet_id=WALLET_ID, message_hash=safe_tx_hash)
    packed_sig = split_and_pack_sig(raw_sig)
    print(f"  Signature (v={int(packed_sig[-2:], 16)}): {packed_sig[:20]}...")

    try:
        result = relayer_client.execute_safe_transaction(
            eoa_address=EOA_ADDRESS,
            safe_address=SAFE_ADDRESS,
            to=approve_tx["to"],
            data=approve_tx["data"],
            signature=packed_sig,
            nonce=nonce_str,
        )
        tx_id = result.get("transactionID", "")
        print(f"  ✅ Accepted! transactionID={tx_id}")
        if tx_id:
            print("  Waiting for confirmation...")
            status = relayer_client.wait_for_tx(tx_id, timeout_seconds=120)
            print(f"  ✅ Confirmed! state={status.get('state')}")
    except httpx.HTTPStatusError as e:
        print(f"  ❌ HTTP error: {e.response.status_code} {e.response.text}")
    except Exception as e:
        print(f"  ❌ Error: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["order", "safe", "approve-neg-risk", "all"], default="all")
    args = parser.parse_args()

    if args.step in ("order", "all"):
        creds = derive_clob_credentials()
        test_place_order_builder(creds)

    if args.step in ("safe", "all"):
        debug_safe_execution()

    if args.step == "approve-neg-risk":
        approve_neg_risk_exchange()
