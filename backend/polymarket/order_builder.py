"""
Polymarket 订单构建器 / Polymarket Order Builder
==================================================
构建符合 Polymarket CLOB API 规范的 EIP-712 订单结构。
Builds EIP-712 order structures conforming to Polymarket CLOB API spec.

Polymarket Order 的 EIP-712 结构 / EIP-712 structure:
    - Domain: Polymarket CTF Exchange / version: 1 / chainId: 137 (Polygon mainnet)
    - Type: Order（包含 12 个字段，详见下方类型定义）
    - 合约地址 / Contract: CTF Exchange 或 NegRisk CTF Exchange

字段说明 / Field Description:
    - salt: 随机数，确保每笔订单唯一 / Random number ensuring each order is unique
    - maker: 资金来源地址（用户 EOA）/ Funding source address (user EOA)
    - signer: 签名者地址（用户 EOA，signatureType=0 时与 maker 相同）
              Signer address (user EOA, same as maker when signatureType=0)
    - taker: 对手方地址（零地址 = 公开订单）/ Counterparty address (zero = public order)
    - tokenId: 市场结果 token 的 ID / Market outcome token ID
    - makerAmount: maker 支出金额（USDC 精度 6 位）/ Maker spend amount (USDC 6 decimals)
    - takerAmount: taker 收到金额（结果 token，整数）/ Taker receive amount (outcome token, integer)
    - expiration: 订单过期时间戳（0 = 永不过期）/ Order expiry timestamp (0 = never)
    - nonce: 随机数，用于链上取消 / Nonce for on-chain cancellations
    - feeRateBps: 手续费率（基点），从 CLOB API 动态获取 / Fee rate (bps), fetched from CLOB API
    - side: 0=BUY, 1=SELL
    - signatureType: 0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE

参考 / Reference:
    https://github.com/Polymarket/ctf-exchange/blob/main/src/exchange/libraries/OrderStructs.sol
    https://docs.polymarket.com/developers/CLOB/orders/create-order
"""

import random
import time
from decimal import Decimal
from typing import Literal

from config import settings

# ============================================================
# EIP-712 类型定义 / EIP-712 Type Definitions
# ============================================================

# EIP-712 Domain（必须与 CTF Exchange 合约的 domain 完全匹配）
# EIP-712 Domain (must exactly match CTF Exchange contract's domain)
# 注意：domain name 是 "Polymarket CTF Exchange"，与 CLOB API 认证用的 "ClobAuthDomain" 不同！
# Note: domain name is "Polymarket CTF Exchange", different from "ClobAuthDomain" used for CLOB API auth!
POLYMARKET_EIP712_DOMAIN = {
    # 注意：domain name 必须是 "Polymarket CTF Exchange"（参考 py-order-utils BaseBuilder._get_domain_separator）
    # Note: domain name must be "Polymarket CTF Exchange" (per py-order-utils BaseBuilder._get_domain_separator)
    "name": "Polymarket CTF Exchange",
    "version": "1",
    "chainId": 137,  # Polygon mainnet
}

# EIP-712 类型定义（必须与合约 ABI 完全匹配）
# EIP-712 type definitions (must exactly match contract ABI)
POLYMARKET_EIP712_TYPES = {
    "Order": [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "signer", "type": "address"},
        {"name": "taker", "type": "address"},
        {"name": "tokenId", "type": "uint256"},
        {"name": "makerAmount", "type": "uint256"},
        {"name": "takerAmount", "type": "uint256"},
        {"name": "expiration", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "feeRateBps", "type": "uint256"},
        {"name": "side", "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
    ]
}

# 订单方向 / Order side
SIDE_BUY = 0
SIDE_SELL = 1

# 签名类型 / Signature type
SIG_TYPE_EOA = 0          # 直接 EOA 签名（本 demo 使用）/ Direct EOA signing (used in this demo)
SIG_TYPE_POLY_PROXY = 1   # Polymarket 代理钱包 / Polymarket proxy wallet
SIG_TYPE_GNOSIS_SAFE = 2  # Gnosis Safe 多签 / Gnosis Safe multisig

# 零地址（公开订单的 taker）/ Zero address (taker for public orders)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# USDC 精度（6 位小数）/ USDC precision (6 decimal places)
USDC_DECIMALS = 6


def usdc_to_wei(amount_usdc: float) -> int:
    """
    将 USDC 金额转换为链上精度（6 位小数）。
    Converts USDC amount to on-chain precision (6 decimal places).

    Args:
        amount_usdc: USDC 金额（人类可读）/ USDC amount (human-readable)

    Returns:
        链上精度的整数 / Integer in on-chain precision

    Example:
        >>> usdc_to_wei(1.5)  # 1.5 USDC
        1500000
    """
    return int(Decimal(str(amount_usdc)) * Decimal(10 ** USDC_DECIMALS))


def build_order_message(
    maker_address: str,
    token_id: str,
    side: Literal["BUY", "SELL"],
    price: float,
    size: float,
    fee_rate_bps: int,
    expiration: int = 0,
    nonce: int = 0,
    signer_address: str = None,
    signature_type: int = SIG_TYPE_EOA,
) -> dict:
    """
    构建 Polymarket 订单的 EIP-712 message 部分。
    Builds the EIP-712 message portion of a Polymarket order.

    金额换算逻辑 / Amount conversion logic:
        BUY 订单：用 USDC 买入结果 token
            makerAmount = price * size（USDC 精度）
            takerAmount = size（结果 token 整数）
        SELL 订单：卖出结果 token 换 USDC
            makerAmount = size（结果 token 整数）
            takerAmount = price * size（USDC 精度）

    Args:
        maker_address: 资金来源地址。EOA 方案时是用户 EOA；Safe 方案时是 Safe 地址。
                       Funding source address. EOA address for EOA scheme; Safe address for Safe scheme.
        token_id: 市场结果 token 的 ID（从 CLOB API 市场信息获取）
                  Market outcome token ID (obtained from CLOB API market info)
        side: "BUY" 或 "SELL" / "BUY" or "SELL"
        price: 订单价格（0-1 之间，如 0.6 表示 60 美分）
               Order price (0-1, e.g., 0.6 means 60 cents)
        size: 订单数量（结果 token 数量，最小精度见市场 tick_size）
              Order size (outcome token quantity, min precision see market tick_size)
        fee_rate_bps: 手续费率（基点），必须与 CLOB API 返回的值一致
                      Fee rate (bps), must match value returned by CLOB API
        expiration: Unix 时间戳，0 表示 GTC（永不过期）/ Unix timestamp, 0 = GTC (never expires)
        nonce: 用于链上取消的 nonce，通常为 0 / Nonce for on-chain cancellation, usually 0
        signer_address: 签名者地址。None 时默认等于 maker_address（EOA 方案）。
                        Safe 方案时传入用户 EOA（Safe owner）。
                        Signer address. Defaults to maker_address (EOA scheme) when None.
                        Pass user EOA (Safe owner) for Safe scheme.
        signature_type: 签名类型：0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE
                        Signature type: 0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE

    Returns:
        符合 EIP-712 Order 类型的 message 字典 / EIP-712 Order type message dictionary
    """
    # 随机 salt 确保每笔订单都有唯一签名（与 py-order-utils generate_seed 保持一致，上限 2^32）
    # Random salt ensures each order has a unique signature (matches py-order-utils generate_seed, max 2^32)
    salt = random.randint(1, 2**32)

    # 计算链上金额 / Calculate on-chain amounts
    usdc_amount = price * size

    if side == "BUY":
        # BUY: maker 支出 USDC，taker 支出结果 token
        # BUY: maker spends USDC, taker spends outcome token
        maker_amount = usdc_to_wei(usdc_amount)
        taker_amount = int(size * (10 ** 6))  # outcome tokens also use 6 decimal places on Polymarket
    else:
        # SELL: maker 支出结果 token，taker 支出 USDC
        # SELL: maker spends outcome token, taker spends USDC
        maker_amount = int(size * (10 ** 6))
        taker_amount = usdc_to_wei(usdc_amount)

    # signer 默认等于 maker（EOA 直签），Safe 方案时 signer 是 EOA（Safe 的 owner）
    # signer defaults to maker (EOA direct), for Safe scheme signer is EOA (Safe owner)
    effective_signer = signer_address if signer_address is not None else maker_address

    # 注意：uint256 大整数（salt, tokenId）必须以字符串传给 Privy JSON API，
    # 避免 JavaScript JSON.parse 的 Number 精度截断（> 2^53 时溢出）。
    # Note: Large uint256 values (salt, tokenId) must be passed as strings to Privy JSON API,
    # to avoid JavaScript JSON.parse Number precision truncation (overflow > 2^53).
    return {
        "salt": str(salt),
        # maker = 资金来源（EOA 方案：EOA；Safe 方案：Safe 地址）
        # maker = funding source (EOA scheme: EOA; Safe scheme: Safe address)
        "maker": maker_address,
        # signer = 实际签名者（EOA 方案：EOA；Safe 方案：EOA，即 Safe owner）
        # signer = actual signer (EOA scheme: EOA; Safe scheme: EOA, i.e., Safe owner)
        "signer": effective_signer,
        # 零地址 = 任何人都可以 taker（公开订单）
        # Zero address = anyone can be taker (public order)
        "taker": ZERO_ADDRESS,
        "tokenId": str(int(token_id)),
        "makerAmount": str(maker_amount),
        "takerAmount": str(taker_amount),
        "expiration": str(expiration),
        "nonce": str(nonce),
        "feeRateBps": str(fee_rate_bps),
        "side": SIDE_BUY if side == "BUY" else SIDE_SELL,
        "signatureType": signature_type,
    }


def build_eip712_typed_data(
    order_message: dict,
    neg_risk: bool = False,
) -> dict:
    """
    将订单 message 包装成完整的 EIP-712 结构化数据。
    Wraps order message into complete EIP-712 structured data.

    此结构将传给 Privy API 的 eth_signTypedData_v4 方法。
    This structure is passed to Privy API's eth_signTypedData_v4 method.

    Args:
        order_message: 由 build_order_message() 生成的订单数据
                       Order data generated by build_order_message()
        neg_risk: 是否为多结果市场（使用 NegRisk Exchange 合约）
                  Whether this is a multi-outcome market (uses NegRisk Exchange contract)

    Returns:
        完整的 EIP-712 typed data，可直接传给 Privy sign_typed_data()
        Complete EIP-712 typed data, ready to pass to Privy sign_typed_data()
    """
    # 根据市场类型选择合约地址
    # Select contract address based on market type
    contract_address = (
        settings.polymarket_neg_risk_ctf_exchange_address
        if neg_risk
        else settings.polymarket_ctf_exchange_address
    )

    return {
        # EIP-712 domain（必须与合约部署的 domain 完全匹配）
        # EIP-712 domain (must exactly match the domain deployed with the contract)
        "domain": {
            **POLYMARKET_EIP712_DOMAIN,
            # verifyingContract 指定验证签名的合约地址
            # verifyingContract specifies the contract address that verifies the signature
            "verifyingContract": contract_address,
        },
        # 类型定义 / Type definitions
        "types": POLYMARKET_EIP712_TYPES,
        # 主类型 / Primary type being signed
        "primary_type": "Order",
        # 订单数据 / Order data
        "message": order_message,
    }


def build_signed_order_payload(
    order_message: dict,
    signature: str,
) -> dict:
    """
    将订单数据和签名组装成提交给 CLOB API 的格式。
    Assembles order data and signature into the format for submitting to CLOB API.

    Args:
        order_message: 订单 message 数据 / Order message data
        signature: 由 Privy 生成的 EIP-712 签名（0x 前缀十六进制）
                   EIP-712 signature generated by Privy (0x-prefixed hex)

    Returns:
        符合 Polymarket CLOB API 格式的签名订单 / Signed order in Polymarket CLOB API format
    """
    return {
        # salt 发整数，与 py-order-utils SignedOrder.dict() 保持一致（不转字符串）
        # salt sent as integer, consistent with py-order-utils SignedOrder.dict() (not string)
        "salt": int(order_message["salt"]),
        "maker": order_message["maker"],
        "signer": order_message["signer"],
        "taker": order_message["taker"],
        "tokenId": str(order_message["tokenId"]),
        "makerAmount": str(order_message["makerAmount"]),
        "takerAmount": str(order_message["takerAmount"]),
        "expiration": str(order_message["expiration"]),
        "nonce": str(order_message["nonce"]),
        "feeRateBps": str(order_message["feeRateBps"]),
        # side 必须是字符串 "BUY"/"SELL"，而非整数 0/1（参考 py-order-utils SignedOrder.dict()）
        # side must be string "BUY"/"SELL", not integer 0/1 (per py-order-utils SignedOrder.dict())
        "side": "BUY" if order_message["side"] == SIDE_BUY else "SELL",
        "signatureType": order_message["signatureType"],
        # 签名字段 / Signature field
        "signature": signature,
    }
