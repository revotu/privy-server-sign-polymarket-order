"""
Gnosis Safe 地址派生 / Gnosis Safe Address Derivation
=====================================================
使用 Polymarket SafeFactory CREATE2 确定性算法计算 Safe 地址。
Computes Safe address using Polymarket SafeFactory CREATE2 deterministic algorithm.

Polymarket 使用专属的 SafeFactory，与标准 Gnosis GnosisSafeProxyFactory 不同：
Polymarket uses a proprietary SafeFactory, different from standard Gnosis GnosisSafeProxyFactory:

CREATE2 公式 / CREATE2 formula:
    salt = keccak256(abi.encode(ownerAddress))   # ABI-padded 32 bytes (NOT encodePacked)
    address = CREATE2(SafeFactory, salt, SAFE_INIT_CODE_HASH)
    CREATE2 = keccak256(0xff ++ factory ++ salt ++ initCodeHash)[-20:]

参考 / Reference:
    https://github.com/Polymarket/builder-relayer-client/blob/main/src/builder/derive.ts
    https://github.com/Polymarket/builder-relayer-client/blob/main/src/constants/index.ts
"""

from eth_abi import encode as abi_encode
from web3 import Web3
from py_builder_relayer_client.builder.derive import derive

from config import settings

# ============================================================
# ERC-20 常量 / ERC-20 Constants
# ============================================================

# ERC-20 approve(address,uint256) 4-byte 函数选择器
# ERC-20 approve(address,uint256) 4-byte function selector
APPROVE_SELECTOR = bytes.fromhex("095ea7b3")

# 零地址 / Zero address
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def derive_safe_address(eoa_address: str) -> str:
    """
    使用 CREATE2 确定性算法计算用户的 Gnosis Safe 地址（纯本地计算，无 RPC 调用）。
    Computes user's Gnosis Safe address using CREATE2 deterministic algorithm (pure local, no RPC).

    算法与 Polymarket builder-relayer-client 的 deriveSafe() 完全一致：
    Algorithm is identical to Polymarket builder-relayer-client's deriveSafe():
        salt = keccak256(abi.encode(ownerAddress))
        address = keccak256(0xff ++ factory ++ salt ++ SAFE_INIT_CODE_HASH)[-20:]

    注意：使用 abi.encode（32 字节左补零），不是 encodePacked（20 字节紧凑编码）。
    Note: Uses abi.encode (32-byte left-padded), NOT encodePacked (20-byte tight packing).

    Args:
        eoa_address: Safe owner 的 EOA 地址 / EOA address of Safe owner

    Returns:
        Checksum-encoded Safe 地址 / Checksum-encoded Safe address

    Example:
        >>> derive_safe_address("0xcf0C4f62C2Bb98BD14Cf841e22c9E7D5a639112B")
        "0x..."
    """
    return derive(eoa_address, settings.safe_proxy_factory_address)


def build_safe_approve_usdc_tx_data(
    spender_address: str = None,
    usdc_address: str = None,
) -> dict:
    """
    构建 USDC approve 交易数据（Safe 授权指定合约花费 USDC.e）。
    Builds USDC approve transaction data (Safe approves specified contract to spend USDC.e).

    此 calldata 用于 Safe execTransaction 的内部调用：
    This calldata is used as the inner call for Safe execTransaction:
        USDC.approve(spender, MAX_UINT256)

    Args:
        spender_address: 被授权的合约地址（默认为 CTF Exchange）
                         Spender contract address (defaults to CTF Exchange)
        usdc_address: USDC.e 合约地址（默认使用 config 值）
                      USDC.e contract address (defaults to config value)

    Returns:
        包含 to, data, value 的字典 / Dict with to, data, value fields
    """
    if spender_address is None:
        spender_address = settings.polymarket_ctf_exchange_address
    if usdc_address is None:
        usdc_address = settings.usdc_address

    max_uint256 = (2 ** 256) - 1
    encoded = abi_encode(
        ["address", "uint256"],
        [Web3.to_checksum_address(spender_address), max_uint256],
    )

    return {
        "to": usdc_address,
        "data": "0x" + (APPROVE_SELECTOR + encoded).hex(),
        "value": "0",
    }
