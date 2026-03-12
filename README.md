# Privy 服务端签名 × Polymarket 无弹窗下单

**Privy Server-Side Signing × Polymarket No-Popup Order Demo**

> 一个完整的参考实现，演示如何通过 Privy 服务端授权密钥（Authorization Key）实现 Polymarket 下单时用户无需弹窗确认签名。
>
> A complete reference implementation demonstrating how to use Privy server-side authorization keys to place Polymarket orders without user popup confirmations.

---

## 整体架构 / Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     整体流程 / Overall Flow                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [一次性初始化 / One-time Init]                               │
│  python scripts/generate_auth_key.py                         │
│     → 生成 P256 密钥对                                        │
│     → 公钥注册到 Privy Dashboard 为 Key Quorum               │
│     → 私钥存入 .env                                           │
│                                                              │
│  [用户首次登录 / First Login]                                 │
│  Flutter → Privy 登录 → 获取 JWT                             │
│  Flutter → 后端 /api/bind-signer                             │
│  后端 → Privy PATCH /wallets/{id}（用用户 JWT 授权）           │
│     → Key Quorum 成为 wallet 的 signer                       │
│                                                              │
│  [每次下单 / Each Order]                                      │
│  Flutter → 后端 /api/place-order                             │
│  后端 → 构建 EIP-712 订单结构                                  │
│  后端 → Privy POST /wallets/{id}/rpc（用 P256 私钥授权）       │
│       → Privy TEE 用用户私钥签名 EIP-712（无弹窗！）           │
│  后端 → 提交 SignedOrder 到 Polymarket CLOB API               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构 / Project Structure

```
privy-server-sign-polymarket-order/
├── README.md                    # 本文件 / This file
├── .env.example                 # 环境变量模板 / Env vars template
├── .gitignore                   # 排除敏感文件 / Exclude sensitive files
│
├── scripts/
│   └── generate_auth_key.py     # 生成 P256 密钥对 / Generate P256 keypair
│
├── backend/                     # Python FastAPI 后端 / Python FastAPI backend
│   ├── requirements.txt
│   ├── main.py                  # FastAPI 入口 / FastAPI entry
│   ├── config.py                # 配置加载 / Config loading
│   ├── privy/
│   │   ├── auth_signature.py    # ★ P256 授权签名实现 / P256 auth signature
│   │   └── client.py            # Privy REST API 封装 / Privy REST API wrapper
│   ├── polymarket/
│   │   ├── order_builder.py     # EIP-712 订单构建 / EIP-712 order building
│   │   ├── clob_auth.py         # CLOB API 认证 / CLOB API auth
│   │   └── clob_client.py       # CLOB API 客户端 / CLOB API client
│   ├── routers/
│   │   ├── signer.py            # POST /api/bind-signer
│   │   └── order.py             # POST /api/place-order
│   └── tests/
│       ├── test_auth_signature.py  # P256 签名单元测试
│       └── test_full_flow.py       # 完整流程测试
│
└── flutter_demo/                # Flutter 前端 Demo / Flutter frontend demo
    ├── pubspec.yaml
    └── lib/
        ├── main.dart
        ├── config.dart
        ├── models/order_request.dart
        ├── services/
        │   ├── privy_service.dart    # Privy SDK 封装
        │   └── backend_service.dart # 后端 API 调用
        └── screens/home_screen.dart  # 完整 UI
```

---

## 快速开始 / Quick Start

### 第一步：生成 P256 授权密钥（一次性）/ Step 1: Generate P256 Auth Key (one-time)

```bash
# 安装依赖 / Install dependency
pip install cryptography

# 生成密钥对 / Generate keypair
python scripts/generate_auth_key.py
```

输出示例 / Example output:
```
【步骤 1】将以下私钥填入 .env 文件:
  PRIVY_AUTHORIZATION_KEY=wallet-auth:MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0w...

【步骤 2】将以下公钥注册到 Privy Dashboard:
  PUBLIC KEY for Privy Dashboard:
  MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
```

### 第二步：在 Privy Dashboard 注册 Key Quorum（一次性）/ Step 2: Register Key Quorum (one-time)

1. 前往 [https://dashboard.privy.io](https://dashboard.privy.io) → 你的 App → Wallets → **Authorization keys**
2. 点击 **New key** → 选择 **"Register key quorum instead"**
3. 粘贴上面输出的公钥
4. 设置 **Authorization threshold = 1**
5. 保存生成的 **Key Quorum ID**（格式如 `key_quorum_abc123...`）

### 第三步：配置 .env / Step 3: Configure .env

```bash
# 复制模板 / Copy template
cp .env.example .env

# 编辑 .env，填入真实值 / Edit .env with real values
```

`.env` 内容示例 / Example `.env` content:
```bash
PRIVY_APP_ID=clxxxxxxxxxxxxxxxxxxxxxxxx
PRIVY_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PRIVY_AUTHORIZATION_KEY=wallet-auth:MIGHAgEAMBMGByqGSM49AgEGCC...
PRIVY_KEY_QUORUM_ID=key_quorum_xxxxxxxxxxxxxxxx
```

### 第四步：启动后端 / Step 4: Start Backend

```bash
cd backend

# 创建虚拟环境（推荐）/ Create virtual env (recommended)
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 安装依赖 / Install dependencies
pip install -r requirements.txt

# 启动服务 / Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

访问 API 文档 / Access API docs: **http://localhost:8000/docs**

### 第五步：运行单元测试 / Step 5: Run Unit Tests

```bash
cd backend

# P256 签名单元测试（不需要真实 API）/ P256 signing unit tests (no real API needed)
pytest tests/test_auth_signature.py -v

# 本地订单构建测试 / Local order building tests
pytest tests/test_full_flow.py -v -m "not integration"
```

预期输出 / Expected output:
```
tests/test_auth_signature.py::TestLoadPrivateKey::test_load_valid_key PASSED
tests/test_auth_signature.py::TestCanonicalizePayload::test_sort_keys PASSED
...
tests/test_auth_signature.py::TestComputeAuthorizationSignature::test_signature_verifiable_with_public_key PASSED
```

### 第六步：运行 Flutter Demo / Step 6: Run Flutter Demo

```bash
cd flutter_demo

# 编辑配置文件，填入 Privy App ID
# Edit config file, fill in Privy App ID
# lib/config.dart → static const String privyAppId = 'YOUR_PRIVY_APP_ID';

# 安装依赖 / Install dependencies
flutter pub get

# 运行 / Run
flutter run
```

### 第七步：完整端到端测试 / Step 7: Full End-to-End Test

在 Flutter 界面中 / In Flutter UI:
1. **步骤 1**：输入邮箱 → 发送 OTP → 验证登录
2. **步骤 2**：点击"绑定 Signer"（需要用户 JWT 授权，一次性）→ 派生 CLOB 凭据
3. **步骤 3**：填写市场 ID、价格、数量 → 点击**"服务端代签下单"**

或者用 curl 测试后端 / Or test backend with curl:

```bash
# 健康检查 / Health check
curl http://localhost:8000/health

# 获取市场信息（无需认证）/ Get market info (no auth needed)
curl "http://localhost:8000/api/markets/0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee3a7386ad423d9dd9b"

# 绑定 signer（需要真实 wallet_id 和 user_jwt）/ Bind signer (needs real wallet_id and user_jwt)
curl -X POST http://localhost:8000/api/bind-signer \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "wallet_your_wallet_id",
    "user_jwt": "eyJhbGciOiJFUzI1NiJ9..."
  }'

# 下单（需要所有凭据配置好）/ Place order (needs all credentials configured)
curl -X POST http://localhost:8000/api/place-order \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "wallet_your_wallet_id",
    "wallet_address": "0xYourWalletAddress",
    "condition_id": "0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee3a7386ad423d9dd9b",
    "side": "BUY",
    "price": 0.01,
    "size": 1.0,
    "clob_api_key": "your_clob_api_key",
    "clob_api_secret": "your_clob_api_secret",
    "clob_api_passphrase": "your_clob_api_passphrase",
    "order_type": "GTC"
  }'
```

---

## 核心技术说明 / Core Technical Notes

### Privy 授权签名原理 / Privy Authorization Signature Mechanism

每个发送给 Privy wallet API 的请求（签名、发交易等）都需要附带 `privy-authorization-signature` 请求头，证明请求方有权执行该操作。

Every request sent to Privy wallet API (signing, transactions, etc.) requires a `privy-authorization-signature` header proving the requester is authorized.

```python
# 签名 payload 结构 / Signature payload structure
payload = {
    "version": 1,
    "method": "POST",
    "url": "https://api.privy.io/v1/wallets/{wallet_id}/rpc",
    "body": { ... },  # 请求体 / request body
    "headers": {"privy-app-id": "your_app_id"},
}

# 用 P256 私钥对规范化后的 JSON 做 ECDSA SHA-256 签名
# Sign canonicalized JSON with P256 private key using ECDSA SHA-256
signature = ecdsa_sign(
    key=your_p256_private_key,
    data=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    algorithm="SHA256",
)
header_value = base64.b64encode(signature)
```

### 添加 Signer 的授权 / Authorization for Adding Signers

修改 wallet 配置（如添加 signer）需要 **wallet owner** 授权。用户钱包的 owner 是用户本人，因此需要用户的 JWT：

Modifying wallet config (like adding signers) requires **wallet owner** authorization. The owner of user wallet is the user themselves, so user JWT is required:

```
PATCH /v1/wallets/{wallet_id}
Header: privy-authorization-jwt: <user_jwt>
Body: {"additional_signers": [{"signer_id": "key_quorum_id"}]}
```

### 代签订单的授权 / Authorization for Signing Orders

添加 Key Quorum signer 之后，服务端可以直接用 P256 私钥授权签名请求：

After Key Quorum signer is added, server can directly use P256 private key to authorize signing requests:

```
POST /v1/wallets/{wallet_id}/rpc
Header: privy-authorization-signature: <p256_signature>
Body: {"method": "eth_signTypedData_v4", "params": {"typed_data": {...}}}
```

**全程不需要用户参与 → 无弹窗！/ No user involvement needed → No popup!**

---

## 安全注意事项 / Security Notes

| 内容 / Item | 处理方式 / Handling |
|------------|-------------------|
| P256 私钥 / P256 private key | 只通过环境变量注入，不入库 / Inject via env vars only, never in code |
| Privy App Secret | 只在服务端使用，绝不发给前端 / Server-side only, never to frontend |
| CLOB API Secret | 存储在服务端，Demo 仅演示目的返回给前端 / Stored server-side; demo returns to frontend for illustration only |
| 用户 JWT | 用后即弃，不长期存储 / Use once, not stored long-term |
| .env 文件 | 在 .gitignore 中排除 / Excluded in .gitignore |

---

## 依赖版本 / Dependencies

### 后端 / Backend
- Python >= 3.11
- FastAPI 0.115.6
- cryptography 44.0.0（P256 签名）
- py-order-utils 0.3.0（Polymarket 订单构建）
- py-clob-client 0.18.0（CLOB API 交互）
- eth-account 0.13.4（EIP-712 支持）

### 前端 / Frontend
- Flutter >= 3.16.0
- privy ^1.0.0（Privy Flutter SDK）
- http ^1.2.0

---

## 参考文档 / References

- [Privy Server-Side Signing](https://docs.privy.io/controls/authorization-keys/using-owners/sign/signing-on-the-server)
- [Privy Direct Implementation](https://docs.privy.io/controls/authorization-keys/using-owners/sign/direct-implementation)
- [Privy Add Signers](https://docs.privy.io/wallets/using-wallets/signers/add-signers)
- [Privy Python SDK](https://docs.privy.io/basics/python/setup)
- [Privy Flutter SDK](https://docs.privy.io/sdks/flutter/setup)
- [Polymarket CLOB API](https://docs.polymarket.com/developers/CLOB/overview)
- [Polymarket CLOB Authentication](https://docs.polymarket.com/developers/CLOB/authentication)
- [py-order-utils](https://github.com/Polymarket/python-order-utils)
