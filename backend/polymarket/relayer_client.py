"""
Polymarket Relayer API 客户端 / Polymarket Relayer API Client
=============================================================
封装 Polymarket Relayer (https://relayer-v2.polymarket.com) 的 API 调用。
Encapsulates Polymarket Relayer API calls.

Relayer 功能 / Relayer Functions:
    - deploy_safe:              无 gas 部署 Gnosis Safe / Gasless deploy Gnosis Safe
    - execute_safe_transaction: 无 gas 执行 Safe 交易（如 USDC approve）
                                Gasless execute Safe transaction (e.g., USDC approve)
    - check_deployed:           检查 Safe 是否已部署 / Check if Safe is deployed
    - get_tx_status:            查询交易状态 / Query transaction status

Relayer 流程 / Relayer Flow:
    [部署 Safe / Deploy Safe]
    1. 构建 CreateProxy EIP-712 typed data
    2. 通过 Privy 服务端签名（sign_typed_data）/ Privy server-side signing
    3. POST /submit (type="SAFE-CREATE") → Relayer 无 gas 部署 Safe
    4. GET /transaction?id=<transactionID> 轮询确认

    [执行 Safe 交易 / Execute Safe Transaction (e.g., USDC approve)]
    1. GET /nonce?address=<EOA>&type=SAFE 获取当前 nonce
    2. 用 compute_safe_tx_hash() 计算 SafeTx EIP-712 哈希
    3. 通过 Privy personal_sign 签名（返回 v=27/28）
    4. split_and_pack_sig 将 v 从 27/28 转换为 31/32（Relayer 要求格式）
    5. POST /submit (type="SAFE") → Relayer 无 gas 执行交易
    6. GET /transaction?id=<transactionID> 轮询确认

API 端点 / API Endpoints:
    POST /submit             提交交易（部署或执行）/ Submit transaction (deploy or execute)
    GET  /nonce              获取 Safe nonce / Get Safe nonce
    GET  /deployed           检查部署状态 / Check deployment status
    GET  /transaction        查询交易状态 / Query transaction status

参考 / Reference:
    https://github.com/Polymarket/py-builder-relayer-client
    https://docs.polymarket.com/developers/builders/relayer-client
"""

import json
import time

import httpx
from py_builder_relayer_client.builder.safe import (
    create_struct_hash,
    split_and_pack_sig,  # 直接复用官方库 / Reuse official library directly
)
from py_builder_relayer_client.models import (
    OperationType,
    SignatureParams,
    TransactionRequest,
    TransactionType,
)

from config import settings
from polymarket.builder_auth import build_builder_headers

# ============================================================
# EIP-712 类型定义 / EIP-712 Type Definitions
# ============================================================

# Safe 交易 EIP-712 类型 / Safe transaction EIP-712 types
SAFE_TX_EIP712_TYPES = {
    "SafeTx": [
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "data", "type": "bytes"},
        {"name": "operation", "type": "uint8"},
        {"name": "safeTxGas", "type": "uint256"},
        {"name": "baseGas", "type": "uint256"},
        {"name": "gasPrice", "type": "uint256"},
        {"name": "gasToken", "type": "address"},
        {"name": "refundReceiver", "type": "address"},
        {"name": "nonce", "type": "uint256"},
    ]
}

# Safe 部署授权 EIP-712 类型 / Safe deployment authorization EIP-712 types
CREATE_PROXY_EIP712_TYPES = {
    "CreateProxy": [
        {"name": "paymentToken", "type": "address"},
        {"name": "payment", "type": "uint256"},
        {"name": "paymentReceiver", "type": "address"},
    ]
}

# Polymarket SafeFactory EIP-712 domain name / Polymarket SafeFactory EIP-712 domain name
SAFE_FACTORY_NAME = "Polymarket Contract Proxy Factory"

# 零地址 / Zero address
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Safe 交易操作类型 / Safe transaction operation type
OPERATION_CALL = 0


def compute_safe_tx_hash(
    safe_address: str,
    to: str,
    data: str,
    value: int = 0,
    operation: int = OPERATION_CALL,
    safe_tx_gas: int = 0,
    base_gas: int = 0,
    gas_price: int = 0,
    gas_token: str = ZERO_ADDRESS,
    refund_receiver: str = ZERO_ADDRESS,
    nonce: int = 0,
) -> str:
    """
    计算 Safe 交易的 EIP-712 完整哈希（委托给官方库实现）。
    Computes Safe transaction full EIP-712 hash (delegates to official library).

    使用官方 py_builder_relayer_client 库的 create_struct_hash 实现，
    避免手写重复代码，确保与官方实现一致。
    Uses official py_builder_relayer_client create_struct_hash,
    avoiding hand-written duplication and ensuring consistency.

    Returns:
        EIP-712 哈希（0x 前缀十六进制）/ EIP-712 hash (0x-prefixed hex)
    """
    return create_struct_hash(
        chain_id=settings.polymarket_chain_id,
        safe=safe_address,
        to=to,
        value=str(value),
        data=data,
        operation=OperationType(operation),
        safe_tx_gas=str(safe_tx_gas),
        base_gas=str(base_gas),
        gas_price=str(gas_price),
        gas_token=gas_token,
        refund_receiver=refund_receiver,
        nonce=str(nonce),
    )


class RelayerClient:
    """
    Polymarket Relayer API 客户端。
    Polymarket Relayer API client.

    通过 Polymarket Relayer 无 gas 部署 Safe 和执行 Safe 交易。
    Deploy Safe and execute Safe transactions without gas via Polymarket Relayer.
    """

    def __init__(self, relayer_host: str = None):
        """
        Args:
            relayer_host: Relayer API 地址（默认从 settings 读取）
                          Relayer API host (defaults to settings)
        """
        self.base_url = relayer_host or settings.relayer_host

    def build_safe_create_typed_data(self) -> dict:
        """
        构建 Safe 部署授权的 EIP-712 typed data (CreateProxy 类型)。
        Builds EIP-712 typed data for Safe deployment authorization (CreateProxy type).

        此数据由用户 EOA 通过 Privy 签名，证明授权 Relayer 代为部署 Safe。
        Signed by user EOA via Privy to authorize Relayer to deploy the Safe on their behalf.

        EIP-712 Domain:
            name = "Polymarket Contract Proxy Factory"
            chainId = 137
            verifyingContract = SafeFactory address

        Returns:
            完整的 EIP-712 typed data，可直接传给 Privy sign_typed_data()
            Complete EIP-712 typed data, ready for Privy sign_typed_data()
        """
        return {
            "domain": {
                "name": SAFE_FACTORY_NAME,
                "chainId": settings.polymarket_chain_id,
                "verifyingContract": settings.safe_proxy_factory_address,
            },
            "types": CREATE_PROXY_EIP712_TYPES,
            "primary_type": "CreateProxy",
            "message": {
                "paymentToken": ZERO_ADDRESS,
                "payment": 0,
                "paymentReceiver": ZERO_ADDRESS,
            },
        }

    def build_safe_tx_typed_data(
        self,
        safe_address: str,
        to: str,
        data: str,
        value: int = 0,
        operation: int = OPERATION_CALL,
        nonce: int = 0,
    ) -> dict:
        """
        构建 Safe 交易的 EIP-712 typed data (SafeTx 类型)。
        Builds EIP-712 typed data for a Safe transaction (SafeTx type).

        此数据用于签名 Safe 内部交易（如 USDC approve），通过 Privy 服务端签名。
        Used to sign Safe internal transactions (e.g., USDC approve) via Privy server signing.

        ★ 注意 / Note:
            此方法仅用于构建调试/测试用的 typed data，不再用于实际签名流程。
            实际签名使用 compute_safe_tx_hash() + personal_sign + split_and_pack_sig。
            This method is for debug/testing only; actual signing uses compute_safe_tx_hash() + personal_sign + split_and_pack_sig.

        EIP-712 Domain:
            chainId = 137
            verifyingContract = safe_address（注意：无 name 和 version 字段）
                                (Note: no name and version fields!)

        Args:
            safe_address: Safe 合约地址 / Safe contract address
            to: Safe 内部交易的目标合约 / Target contract for Safe's internal call
            data: 内部调用数据（十六进制字符串）/ Internal call data (hex string)
            value: ETH 金额（通常为 0，无 gas 情况）/ ETH value (usually 0, gasless)
            operation: 0=CALL, 1=DELEGATECALL
            nonce: Safe 交易 nonce（从 get_safe_nonce() 获取）/ Safe tx nonce (from get_safe_nonce())

        Returns:
            完整的 EIP-712 typed data，可直接传给 Privy sign_typed_data()
            Complete EIP-712 typed data, ready for Privy sign_typed_data()
        """
        from web3 import Web3
        return {
            "domain": {
                "chainId": settings.polymarket_chain_id,
                # verifyingContract = Safe 地址（注意：无 name 和 version！）
                # verifyingContract = Safe address (Note: no name and version!)
                "verifyingContract": Web3.to_checksum_address(safe_address),
            },
            "types": SAFE_TX_EIP712_TYPES,
            "primary_type": "SafeTx",
            "message": {
                "to": Web3.to_checksum_address(to),
                "value": value,
                "data": data,
                "operation": operation,
                "safeTxGas": 0,
                "baseGas": 0,
                "gasPrice": 0,
                "gasToken": ZERO_ADDRESS,
                "refundReceiver": ZERO_ADDRESS,
                "nonce": nonce,
            },
        }

    def get_safe_nonce(self, eoa_address: str) -> str:
        """
        从 Relayer API 获取用户 Safe 的当前 nonce。
        Gets user's Safe current nonce from Relayer API.

        此 nonce 每次 Safe 交易后自动递增，必须在构建每笔 Safe 交易前获取。
        This nonce auto-increments after each Safe transaction and must be fetched before each tx.

        Args:
            eoa_address: Safe owner 的 EOA 地址 / EOA address of Safe owner

        Returns:
            nonce 字符串（如 "0", "1", ...）/ nonce string (e.g., "0", "1", ...)
        """
        request_path = "/nonce"
        headers = build_builder_headers(method="GET", path=request_path)
        headers["Content-Type"] = "application/json"

        with httpx.Client() as client:
            response = client.get(
                f"{self.base_url}{request_path}",
                params={"address": eoa_address, "type": "SAFE"},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        return str(data.get("nonce", "0"))

    def check_deployed(self, safe_address: str) -> bool:
        """
        检查指定 Safe 是否已在链上部署。
        Checks if the specified Safe is deployed on-chain.

        Args:
            safe_address: Safe 合约地址 / Safe contract address

        Returns:
            True 如果已部署，False 如果未部署 / True if deployed, False if not
        """
        request_path = "/deployed"
        headers = build_builder_headers(method="GET", path=request_path)
        headers["Content-Type"] = "application/json"

        with httpx.Client() as client:
            response = client.get(
                f"{self.base_url}{request_path}",
                params={"address": safe_address},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        return data.get("deployed", False)

    def deploy_safe(
        self,
        eoa_address: str,
        safe_address: str,
        signature: str,
    ) -> dict:
        """
        通过 Polymarket Relayer 无 gas 部署 Gnosis Safe。
        Deploys Gnosis Safe via Polymarket Relayer without gas.

        流程 / Flow:
            1. 先用 build_safe_create_typed_data() 构建 EIP-712 数据
            2. 用 Privy 服务端签名（sign_typed_data）
            3. 将签名传入此方法提交 Relayer

        Args:
            eoa_address: Safe owner EOA 地址 / EOA address of Safe owner
            safe_address: 要部署的 Safe 地址（由 derive_safe_address 计算）
                          Safe address to deploy (computed by derive_safe_address)
            signature: EOA 对 CreateProxy EIP-712 数据的签名（sign_typed_data 返回值）
                       EOA's signature over CreateProxy EIP-712 data (from sign_typed_data)

        Returns:
            Relayer 响应，含 transactionID / Relayer response with transactionID

        Raises:
            httpx.HTTPStatusError: 如果 Relayer 拒绝 / If Relayer rejects
        """
        request_path = "/submit"

        tx_request = TransactionRequest(
            type=TransactionType.SAFE_CREATE.value,
            from_address=eoa_address,
            to=settings.safe_proxy_factory_address,
            proxy=safe_address,
            data="0x",
            signature=signature,
            signature_params=SignatureParams(
                payment_token=ZERO_ADDRESS,
                payment="0",
                payment_receiver=ZERO_ADDRESS,
            ),
        )
        body_data = tx_request.to_dict()
        body_str = json.dumps(body_data, separators=(",", ":"))

        headers = build_builder_headers(method="POST", path=request_path, body=body_str)
        headers["Content-Type"] = "application/json"

        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}{request_path}",
                content=body_str,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    def execute_safe_transaction(
        self,
        eoa_address: str,
        safe_address: str,
        to: str,
        data: str,
        signature: str,
        nonce: str,
        value: int = 0,
        operation: int = OPERATION_CALL,
        metadata: str = "",
    ) -> dict:
        """
        通过 Polymarket Relayer 无 gas 执行 Safe 交易（如 USDC approve）。
        Executes a Safe transaction without gas via Polymarket Relayer (e.g., USDC approve).

        流程 / Flow:
            1. 先用 get_safe_nonce(eoa_address) 获取当前 nonce
            2. 用 compute_safe_tx_hash() 计算 SafeTx EIP-712 哈希
            3. 用 Privy sign_message() personal_sign 签名（返回 v=27/28）
            4. 用 split_and_pack_sig() 将 v 从 27/28 转换为 31/32
            5. 将 packed 签名和 nonce 传入此方法提交 Relayer

        ★ 签名格式 / Signature Format:
            signature 必须是经 split_and_pack_sig() 转换后的 v=31/32 格式。
            Relayer 预验证签名，仅接受 v=31/32（eth_sign 格式），拒绝 v=27/28。
            signature must be v=31/32 format after split_and_pack_sig() conversion.
            Relayer pre-validates signatures, only accepts v=31/32 (eth_sign format), rejects v=27/28.

        Args:
            eoa_address: Safe owner EOA 地址 / EOA address of Safe owner
            safe_address: Safe 合约地址 / Safe contract address
            to: Safe 内部调用的目标合约 / Target contract for Safe's internal call
            data: 内部调用数据（十六进制）/ Internal call data (hex)
            signature: EOA 对 SafeTx hash 的 personal_sign 签名经 split_and_pack_sig 转换（v=31/32）
                       EOA's personal_sign over SafeTx hash, converted via split_and_pack_sig (v=31/32)
            nonce: Safe 当前 nonce（字符串，从 get_safe_nonce 获取）
                   Safe current nonce (string, from get_safe_nonce)
            value: ETH 金额（通常为 0）/ ETH value (usually 0)
            operation: 0=CALL, 1=DELEGATECALL
            metadata: 可选元数据（通常为空字符串）/ Optional metadata (usually empty string)

        Returns:
            Relayer 响应，含 transactionID / Relayer response with transactionID

        Raises:
            httpx.HTTPStatusError: 如果 Relayer 拒绝 / If Relayer rejects
        """
        request_path = "/submit"

        # 使用官方库 TransactionRequest 构建请求体，确保字段结构正确
        # Use official library TransactionRequest to build request body, ensures correct structure
        tx_request = TransactionRequest(
            type=TransactionType.SAFE.value,
            from_address=eoa_address,
            to=to,
            proxy=safe_address,
            # ★ 关键：必须包含 value 字段，官方库 TransactionRequest 要求此字段
            # ★ Key: value field must be present, required by official library TransactionRequest
            value=str(value),
            data=data,
            nonce=nonce,
            signature=signature,
            signature_params=SignatureParams(
                gas_price="0",
                operation=str(operation),
                safe_txn_gas="0",
                base_gas="0",
                gas_token=ZERO_ADDRESS,
                refund_receiver=ZERO_ADDRESS,
            ),
            metadata=metadata,
        )
        body_data = tx_request.to_dict()
        body_str = json.dumps(body_data, separators=(",", ":"))

        headers = build_builder_headers(method="POST", path=request_path, body=body_str)
        headers["Content-Type"] = "application/json"

        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}{request_path}",
                content=body_str,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    def get_tx_status(self, transaction_id: str) -> dict:
        """
        查询 Relayer 交易状态（通过 transactionID）。
        Queries Relayer transaction status (by transactionID).

        Args:
            transaction_id: 交易 ID（来自 deploy_safe/execute_safe_transaction 的响应）
                            Transaction ID (from deploy_safe/execute_safe_transaction response)

        Returns:
            包含 state 等字段的字典 / Dict with state and other fields
            state 可能的值 / Possible state values:
                STATE_NEW, STATE_EXECUTED, STATE_MINED, STATE_CONFIRMED, STATE_FAILED, STATE_INVALID
        """
        request_path = "/transaction"
        headers = build_builder_headers(method="GET", path=request_path)
        headers["Content-Type"] = "application/json"

        with httpx.Client() as client:
            response = client.get(
                f"{self.base_url}{request_path}",
                params={"id": transaction_id},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            # Relayer 返回列表，取第一个元素 / Relayer returns a list, take first element
            return data[0] if isinstance(data, list) and data else data

    def wait_for_tx(
        self,
        transaction_id: str,
        timeout_seconds: int = 120,
        poll_interval: int = 3,
    ) -> dict:
        """
        轮询等待 Relayer 交易确认。
        Polls until Relayer transaction is confirmed.

        Args:
            transaction_id: 交易 ID / Transaction ID
            timeout_seconds: 超时时间（秒）/ Timeout in seconds
            poll_interval: 轮询间隔（秒）/ Poll interval in seconds

        Returns:
            已确认的交易状态 / Confirmed transaction status

        Raises:
            TimeoutError: 超过 timeout_seconds 仍未确认
                          If not confirmed within timeout_seconds
            RuntimeError: 交易失败 / Transaction failed
        """
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status_data = self.get_tx_status(transaction_id)
            state = status_data.get("state", "").upper()
            if state in ("STATE_CONFIRMED", "STATE_MINED"):
                return status_data
            if state in ("STATE_FAILED", "STATE_INVALID"):
                raise RuntimeError(f"交易失败 / Transaction failed: {status_data}")
            time.sleep(poll_interval)

        raise TimeoutError(
            f"交易在 {timeout_seconds} 秒内未确认 / "
            f"Transaction not confirmed within {timeout_seconds} seconds: {transaction_id}"
        )


# 全局单例 / Global singleton
relayer_client = RelayerClient()
