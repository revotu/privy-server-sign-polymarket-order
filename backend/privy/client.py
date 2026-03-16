"""
Privy REST API 客户端 / Privy REST API Client
===============================================
封装 Privy REST API 的两个核心操作：
Encapsulates the two core Privy REST API operations:

1. add_signer_to_wallet: 将服务端 Key Quorum 绑定到用户钱包（一次性，需用户 JWT）
   Bind server Key Quorum to user wallet (one-time, requires user JWT)

2. sign_typed_data: 使用服务端授权密钥对 EIP-712 数据签名（每次下单，无需用户参与）
   Sign EIP-712 data using server authorization key (per order, no user needed)

API 端点 / API Endpoints:
    - PATCH https://api.privy.io/v1/wallets/{wallet_id}  （添加 signer）
    - POST  https://api.privy.io/v1/wallets/{wallet_id}/rpc  （签名/交易）

参考 / Reference:
    https://docs.privy.io/wallets/using-wallets/signers/add-signers
    https://docs.privy.io/wallets/using-wallets/ethereum/sign-typed-data
"""

import httpx

from config import settings
from privy.auth_signature import compute_authorization_signature


class PrivyWalletClient:
    """
    Privy wallet 操作客户端。
    Privy wallet operations client.

    所有需要服务端授权密钥签名的操作都通过此类完成。
    All operations requiring server authorization key signatures go through this class.
    """

    def __init__(self):
        # 构建 HTTP Basic Auth（app_id:app_secret）
        # Build HTTP Basic Auth (app_id:app_secret)
        self._auth = (settings.privy_app_id, settings.privy_app_secret)

        # 每个请求都需要的基础 headers
        # Base headers required for every request
        self._base_headers = {
            "Content-Type": "application/json",
            "privy-app-id": settings.privy_app_id,
        }

    def _get_wallet_rpc_url(self, wallet_id: str) -> str:
        """构建 wallet RPC 端点 URL / Build wallet RPC endpoint URL"""
        return f"{settings.privy_api_base_url}/wallets/{wallet_id}/rpc"

    def _get_wallet_url(self, wallet_id: str) -> str:
        """构建 wallet 资源 URL / Build wallet resource URL"""
        return f"{settings.privy_api_base_url}/wallets/{wallet_id}"

    def authenticate_wallet(self, user_jwt: str) -> str:
        """
        用用户 JWT 换取 Privy authorization_key（短期授权令牌）。
        Exchange user JWT for a Privy authorization_key (short-lived authorization token).

        流程说明 / Flow:
            Privy 默认禁止直接用 user JWT 执行 wallet 写操作（如添加 signer）。
            需先调用此接口，将 user JWT 换成 authorization_key，再用 authorization_key
            作为 privy-authorization-jwt 头执行写操作。
            By default Privy disables using user JWT directly for wallet write operations (e.g., add signer).
            Must first call this endpoint to exchange user JWT for authorization_key, then use
            authorization_key as privy-authorization-jwt header for write operations.

        ⚠️  前置条件 / Prerequisite:
            此接口需要 Privy 为你的 App 开通权限，默认关闭。
            未开通时返回：{"error": "Invalid JWT token provided", "code": "invalid_data"}
            联系 Privy 支持申请开通后才能使用。
            This endpoint requires Privy to enable access for your app (disabled by default).
            Without access, returns: {"error": "Invalid JWT token provided", "code": "invalid_data"}
            Contact Privy support to request access.

        Args:
            user_jwt: 用户的 Privy access token（从 Flutter SDK 获取）
                      User's Privy access token (obtained from Flutter SDK)

        Returns:
            authorization_key 字符串，用作后续请求的 privy-authorization-jwt 头
            authorization_key string, used as privy-authorization-jwt header in subsequent requests

        Raises:
            httpx.HTTPStatusError: 如果认证失败（含未开通权限的情况）/ If authentication fails
        """
        url = f"{settings.privy_api_base_url}/wallets/authenticate"

        body = {"user_jwt": user_jwt}

        with httpx.Client() as client:
            response = client.post(
                url,
                json=body,
                auth=self._auth,
                headers=self._base_headers,
            )
            response.raise_for_status()
            data = response.json()

        return data["authorization_key"]

    def add_signer_to_wallet(
        self,
        wallet_id: str,
        key_quorum_id: str,
        user_jwt: str,
    ) -> dict:
        """
        将服务端 Key Quorum 添加为用户钱包的 signer（一次性操作）。
        Adds server Key Quorum as a signer on the user's wallet (one-time operation).

        流程说明 / Flow:
            1. 调用 authenticate_wallet(user_jwt) 换取 authorization_key
               Call authenticate_wallet(user_jwt) to get authorization_key
            2. 以 authorization_key 作为 privy-authorization-jwt 头发送 PATCH 请求
               Send PATCH request with authorization_key as privy-authorization-jwt header

        添加成功后，服务端即可用 P256 授权密钥代替用户签名（无弹窗）。
        After success, the server can sign on behalf of the user with P256 auth key (no popup).

        Args:
            wallet_id: Privy wallet ID（格式如 wallet_123abc...）
                       Privy wallet ID (format: wallet_123abc...)
            key_quorum_id: Key Quorum ID（从 Privy Dashboard 注册公钥后获得）
                           Key Quorum ID (obtained after registering public key in Privy Dashboard)
            user_jwt: 用户的 Privy access token（从 Flutter SDK 获取）
                      User's Privy access token (obtained from Flutter SDK)

        Returns:
            Privy API 响应（更新后的 wallet 对象）/ Privy API response (updated wallet object)

        Raises:
            httpx.HTTPStatusError: 如果 API 请求失败 / If API request fails
        """
        # Step 1: user_jwt → authorization_key（通过 /v1/wallets/authenticate）
        # Step 1: user_jwt → authorization_key (via /v1/wallets/authenticate)
        authorization_key = self.authenticate_wallet(user_jwt)

        url = self._get_wallet_url(wallet_id)

        # 请求体：添加 Key Quorum 作为 signer，不附加 policy（即无限制）
        # Request body: add Key Quorum as signer, no policy (unrestricted)
        body = {
            "additional_signers": [
                {
                    "signer_id": key_quorum_id,
                    # policy_ids 为空表示不限制该 signer 的操作
                    # Empty policy_ids means no restrictions on this signer's operations
                    "policy_ids": [],
                }
            ]
        }

        # Step 2: 用 authorization_key 而非原始 user_jwt 作为授权头
        # Step 2: use authorization_key (not raw user_jwt) as the authorization header
        headers = {
            **self._base_headers,
            "privy-authorization-jwt": authorization_key,
        }

        with httpx.Client() as client:
            response = client.patch(
                url,
                json=body,
                auth=self._auth,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    def sign_typed_data(
        self,
        wallet_id: str,
        typed_data: dict,
    ) -> str:
        """
        使用服务端授权密钥对 EIP-712 结构化数据签名（无需用户参与，无弹窗）。
        Signs EIP-712 structured data using server authorization key (no user needed, no popup).

        前提条件 / Prerequisites:
            用户钱包必须已经通过 add_signer_to_wallet 绑定了服务端 Key Quorum。
            The user wallet must have the server Key Quorum bound via add_signer_to_wallet.

        签名流程 / Signing Flow:
            1. 构建包含 EIP-712 数据的 RPC 请求体
            2. 用服务端 P256 私钥计算请求的授权签名
            3. 发送请求到 Privy API，Privy 在 TEE 中用用户私钥签名
            4. 返回 EIP-712 签名结果

            1. Build RPC request body with EIP-712 data
            2. Compute request authorization signature with server P256 private key
            3. Send request to Privy API, Privy signs with user private key in TEE
            4. Return EIP-712 signature result

        Args:
            wallet_id: Privy wallet ID
            typed_data: 完整的 EIP-712 类型数据，包含 domain, types, primaryType, message
                        Full EIP-712 typed data with domain, types, primaryType, message

        Returns:
            十六进制格式的 EIP-712 签名字符串（0x 前缀）
            Hex-format EIP-712 signature string (0x prefix)

        Raises:
            httpx.HTTPStatusError: 如果签名失败 / If signing fails
        """
        url = self._get_wallet_rpc_url(wallet_id)

        # 构建 Privy wallet RPC 请求体（eth_signTypedData_v4）
        # Build Privy wallet RPC request body (eth_signTypedData_v4)
        body = {
            # chain_type 标识这是 Ethereum 兼容链操作
            # chain_type identifies this as an Ethereum-compatible chain operation
            "chain_type": "ethereum",
            # 使用 eth_signTypedData_v4 进行 EIP-712 签名
            # Use eth_signTypedData_v4 for EIP-712 signing
            "method": "eth_signTypedData_v4",
            "params": {
                # typed_data 包含完整的 EIP-712 结构：domain + types + primaryType + message
                # typed_data contains full EIP-712 structure: domain + types + primaryType + message
                "typed_data": typed_data,
            },
        }

        # 用服务端 P256 私钥计算授权签名
        # 注意：此时签名方是服务端授权密钥（Key Quorum），而非用户
        # Compute authorization signature with server P256 private key
        # Note: The signer here is the server authorization key (Key Quorum), not the user
        authorization_signature = compute_authorization_signature(
            url=url,
            body=body,
            app_id=settings.privy_app_id,
            authorization_key=settings.privy_authorization_key,
            method="POST",
        )

        headers = {
            **self._base_headers,
            # 关键：服务端授权签名，让 Privy 验证我们有权代替用户签名
            # Key: server authorization signature, letting Privy verify we can sign on behalf of user
            "privy-authorization-signature": authorization_signature,
        }

        with httpx.Client() as client:
            response = client.post(
                url,
                json=body,
                auth=self._auth,
                headers=headers,
            )
            if not response.is_success:
                raise httpx.HTTPStatusError(
                    f"Privy sign_typed_data failed {response.status_code}: {response.text}",
                    request=response.request,
                    response=response,
                )
            result = response.json()

        # Privy 返回格式：{"method": "eth_signTypedData_v4", "data": {"signature": "0x...", "encoding": "hex"}}
        # Privy response format: {"method": "eth_signTypedData_v4", "data": {"signature": "0x...", "encoding": "hex"}}
        return result["data"]["signature"]

    def sign_message(
        self,
        wallet_id: str,
        message_hash: str,
    ) -> str:
        """
        使用 personal_sign 对消息哈希签名（用于 Safe execTransaction 签名）。
        Signs a message hash using personal_sign (used for Safe execTransaction signing).

        与 sign_typed_data 不同，此方法使用 personal_sign（添加 "\x19Ethereum Signed Message:\n32" 前缀）。
        Unlike sign_typed_data, this uses personal_sign (adds "\x19Ethereum Signed Message:\n32" prefix).

        在 Gnosis Safe 中，v=31/32 的签名（从 personal_sign 的 v=27/28 加 4 得到）
        对应 eth_sign 类型验证，Safe 会以此类型恢复签名者地址。
        In Gnosis Safe, v=31/32 signatures (personal_sign v=27/28 + 4) correspond
        to eth_sign type verification, which Safe uses to recover the signer address.

        Args:
            wallet_id: Privy wallet ID
            message_hash: 消息哈希（十六进制字符串，0x 前缀）/ Message hash (hex string, 0x-prefixed)

        Returns:
            十六进制格式的签名（0x 前缀）/ Hex-format signature (0x-prefixed)
        """
        url = self._get_wallet_rpc_url(wallet_id)

        body = {
            "chain_type": "ethereum",
            "method": "personal_sign",
            "params": {
                # ★ 关键：必须去掉 "0x" 前缀！Privy 收到带 "0x" 的 hex 时恢复地址错误。
                # ★ Key: must strip "0x" prefix! Privy recovers wrong address when "0x" is included.
                "message": message_hash[2:] if message_hash.startswith("0x") else message_hash,
                "encoding": "hex",
            },
        }

        authorization_signature = compute_authorization_signature(
            url=url,
            body=body,
            app_id=settings.privy_app_id,
            authorization_key=settings.privy_authorization_key,
            method="POST",
        )

        headers = {
            **self._base_headers,
            "privy-authorization-signature": authorization_signature,
        }

        with httpx.Client() as client:
            response = client.post(
                url,
                json=body,
                auth=self._auth,
                headers=headers,
            )
            if not response.is_success:
                raise httpx.HTTPStatusError(
                    f"Privy sign_message failed {response.status_code}: {response.text}",
                    request=response.request,
                    response=response,
                )
            result = response.json()

        # Privy 返回格式：{"method": "personal_sign", "data": {"signature": "0x...", "encoding": "hex"}}
        return result["data"]["signature"]

    def get_user_wallets(self, user_did: str) -> list[dict]:
        """
        获取用户的所有 wallet 信息。
        Gets all wallet information for a user.

        Args:
            user_did: 用户的 Privy DID（格式如 did:privy:...）
                      User's Privy DID (format: did:privy:...)

        Returns:
            用户的 linked_accounts 列表中的 wallet 条目
            Wallet entries from user's linked_accounts list
        """
        url = f"{settings.privy_api_base_url}/users/{user_did}"

        with httpx.Client() as client:
            response = client.get(
                url,
                auth=self._auth,
                headers=self._base_headers,
            )
            response.raise_for_status()
            user_data = response.json()

        # 从 linked_accounts 中过滤出 wallet 类型
        # Filter wallet type from linked_accounts
        linked_accounts = user_data.get("linked_accounts", [])
        wallets = [
            account
            for account in linked_accounts
            if account.get("type") == "wallet"
        ]
        return wallets

    def verify_user_token(self, user_jwt: str) -> dict:
        """
        验证用户的 Privy access token 并返回用户信息。
        Verifies user's Privy access token and returns user info.

        在处理用户请求前验证 JWT 有效性，防止伪造请求。
        Validates JWT validity before processing user requests, preventing forged requests.

        Args:
            user_jwt: 用户的 Privy access token / User's Privy access token

        Returns:
            包含 userId 等信息的字典 / Dictionary with userId and other info
        """
        url = f"{settings.privy_api_base_url}/users/me"

        with httpx.Client() as client:
            response = client.get(
                url,
                auth=self._auth,
                headers={
                    **self._base_headers,
                    "Authorization": f"Bearer {user_jwt}",
                },
            )
            response.raise_for_status()
            return response.json()


# 模块级单例，方便在路由中直接导入使用
# Module-level singleton for easy import in routes
privy_client = PrivyWalletClient()
