# Privy 服务端签名 × Polymarket 无弹窗下单

**Privy Server-Side Signing × Polymarket No-Popup Order Demo**

> 一个完整的参考实现，演示如何通过 Privy 服务端授权密钥（Authorization Key）实现 Polymarket 下单时用户无需弹窗确认签名。
>
> A complete reference implementation demonstrating how to use Privy server-side authorization keys to place Polymarket orders without user popup confirmations.

本项目包含两套下单方案 / This project includes two order schemes:
- **EOA 方案**（`main` 分支）：maker=EOA，signatureType=0，已跑通全链路
- **Builder/Safe 方案**（`feature/builder-safe` 分支）：maker=Safe，signatureType=2，需要 Builder API 凭据

---

## 整体架构 / Architecture

### EOA 方案 / EOA Scheme (main branch)

```
┌─────────────────────────────────────────────────────────────┐
│                 EOA 方案流程 / EOA Scheme Flow                │
├─────────────────────────────────────────────────────────────┤
│  [一次性初始化]  generate_auth_key.py → P256 密钥对           │
│  [用户首次登录]  Flutter → /api/bind-signer → Key Quorum 绑定 │
│  [每次下单]     Flutter → /api/place-order                    │
│                 后端构建 EIP-712（maker=EOA, signatureType=0） │
│                 Privy TEE 签名（P256 授权，无弹窗）            │
│                 提交 SignedOrder 到 Polymarket CLOB            │
└─────────────────────────────────────────────────────────────┘
```

### Builder/Safe 方案 / Builder/Safe Scheme (feature/builder-safe branch)

```
┌─────────────────────────────────────────────────────────────┐
│            Builder/Safe 方案流程 / Builder/Safe Flow          │
├─────────────────────────────────────────────────────────────┤
│  [一次性 onboarding]                                          │
│  Flutter → /api/get-safe-address → 计算 Safe 地址（CREATE2）  │
│  Flutter → /api/setup-safe                                    │
│     → 派生 Safe 地址                                          │
│     → 构建部署 tx → Privy 签名 → Relayer 无 gas 部署 Safe     │
│     → 构建 USDC approve → Privy 签名 → Relayer 无 gas 授权    │
│       (依次授权 CTF Exchange / NegRisk CTF Exchange /          │
│        NegRisk Adapter，共 3 次)                               │
│                                                              │
│  [每次下单]     Flutter → /api/place-order-builder            │
│                 构建 EIP-712（maker=Safe, signer=EOA,          │
│                              signatureType=2）                 │
│                 Privy TEE 签名（P256 授权，无弹窗）            │
│                 提交 SignedOrder（L2 头 + POLY_BUILDER_* 头）   │
└─────────────────────────────────────────────────────────────┘
```

### 两套方案核心差异 / Key Differences

| 维度 | EOA 方案（main） | Builder/Safe 方案（feature/builder-safe） |
|------|----------------|------------------------------------------|
| maker | 用户 EOA | Gnosis Safe 地址 |
| signer | 用户 EOA | 用户 EOA（Safe owner） |
| signatureType | 0（EOA） | 2（POLY_GNOSIS_SAFE） |
| 额外请求头 | L2 头 | L2 头 + POLY_BUILDER_* 头 |
| Safe 部署 | 无需 | 首次 onboarding（Relayer 无 gas） |
| USDC 授权 | 无需 | 首次 onboarding（Relayer 无 gas） |

## 项目结构 / Project Structure

```
privy-server-sign-polymarket-order/
├── README.md                    # 本文件 / This file
├── .env.example                 # 环境变量模板 / Env vars template
├── .gitignore                   # 排除敏感文件 / Exclude sensitive files
│
├── scripts/
│   ├── generate_auth_key.py     # 生成 P256 密钥对 / Generate P256 keypair
│   ├── test_builder_flow.py     # Builder/Safe 方案端到端测试 / Builder/Safe E2E test
│   └── debug_safe_exec.py       # ★ 调试脚本（含 CLOB + Relayer 验证）/ Debug script
│
├── backend/                     # Python FastAPI 后端 / Python FastAPI backend
│   ├── requirements.txt
│   ├── main.py                  # FastAPI 入口 / FastAPI entry
│   ├── config.py                # 配置加载（含 Builder/Safe 配置项）/ Config loading
│   ├── privy/
│   │   ├── auth_signature.py    # ★ P256 授权签名实现 / P256 auth signature
│   │   └── client.py            # Privy REST API 封装 / Privy REST API wrapper
│   ├── polymarket/
│   │   ├── order_builder.py     # EIP-712 订单构建（支持 EOA + Safe）/ EIP-712 order building
│   │   ├── clob_auth.py         # CLOB API 认证 / CLOB API auth
│   │   ├── clob_client.py       # CLOB API 客户端（支持 Builder 头）/ CLOB API client
│   │   ├── safe_wallet.py       # ★ Gnosis Safe 地址派生 / Safe address derivation
│   │   ├── relayer_client.py    # ★ Polymarket Relayer API 客户端 / Relayer API client
│   │   └── builder_auth.py      # ★ Builder API 认证头生成 / Builder API auth headers
│   ├── routers/
│   │   ├── signer.py            # POST /api/bind-signer
│   │   └── order.py             # 下单相关端点（EOA + Builder）/ Order endpoints
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
# Privy 配置（必填）/ Privy config (required)
PRIVY_APP_ID=clxxxxxxxxxxxxxxxxxxxxxxxx
PRIVY_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PRIVY_AUTHORIZATION_KEY=wallet-auth:MIGHAgEAMBMGByqGSM49AgEGCC...
PRIVY_KEY_QUORUM_ID=key_quorum_xxxxxxxxxxxxxxxx

# Builder/Safe 方案额外配置（feature/builder-safe 分支需要）
# Builder/Safe scheme extra config (required for feature/builder-safe branch)
POLYMARKET_BUILDER_API_KEY=your_builder_api_key
POLYMARKET_BUILDER_SECRET=your_builder_secret
POLYMARKET_BUILDER_PASSPHRASE=your_builder_passphrase
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

# EOA 方案下单 / EOA scheme order placement
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

## Builder/Safe 方案使用指南 / Builder/Safe Scheme Guide

> 以下内容适用于 `feature/builder-safe` 分支。
> The following applies to the `feature/builder-safe` branch.

### 前置条件 / Prerequisites

1. **Builder API 凭据**：在 [Polymarket Builder Profile](https://docs.polymarket.com/developers/builders/builder-profile) 申请注册
2. 在 `.env` 中配置 `POLYMARKET_BUILDER_API_KEY`、`POLYMARKET_BUILDER_SECRET`、`POLYMARKET_BUILDER_PASSPHRASE`

### 测试步骤 / Test Steps

```bash
# 切换到 Builder/Safe 分支 / Switch to Builder/Safe branch
git checkout feature/builder-safe

# 步骤 1：纯计算派生 Safe 地址（无需链上，无需 Builder 凭据）
# Step 1: Purely compute Safe address (no chain op, no Builder credentials)
export TEST_WALLET_ADDRESS=0xYourEOAAddress
python scripts/test_builder_flow.py --step derive-safe

# 步骤 2：首次 onboarding（部署 Safe + 授权 USDC 给 3 个合约）
# Step 2: First-time onboarding (deploy Safe + approve USDC for 3 contracts)
export TEST_WALLET_ID=your_privy_wallet_id
python scripts/test_builder_flow.py --step deploy-safe

# 步骤 3：Builder 方案下单
# Step 3: Place order via Builder scheme
export TEST_CLOB_API_KEY=your_clob_api_key
export TEST_CLOB_API_SECRET=your_clob_api_secret
export TEST_CLOB_API_PASSPHRASE=your_clob_api_passphrase
export TEST_CONDITION_ID=0xYourConditionId
python scripts/test_builder_flow.py --step place-order
```

### API 端点（Builder/Safe 分支新增）/ API Endpoints (new in Builder/Safe branch)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/get-safe-address` | POST | 计算用户 Safe 地址（CREATE2，纯本地，无链上操作） |
| `/api/setup-safe` | POST | 首次 onboarding：Relayer 无 gas 部署 Safe + 授权 USDC 给 3 个合约 |
| `/api/place-order-builder` | POST | Builder 方案下单（maker=Safe，signatureType=2） |

```bash
# 计算 Safe 地址 / Compute Safe address
curl -X POST http://localhost:8000/api/get-safe-address \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0xYourEOAAddress"}'

# Builder 方案下单 / Builder scheme order
curl -X POST http://localhost:8000/api/place-order-builder \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_id": "wallet_your_wallet_id",
    "wallet_address": "0xYourEOAAddress",
    "safe_address": "0xYourSafeAddress",
    "condition_id": "0x...",
    "side": "BUY",
    "price": 0.5,
    "size": 1.0,
    "clob_api_key": "...",
    "clob_api_secret": "...",
    "clob_api_passphrase": "...",
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
- py-builder-relayer-client（Relayer API 客户端、Safe 地址派生、签名工具）
- py-builder-signing-sdk（Builder API HMAC 认证头生成）

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
- [Polymarket Builder Profile](https://docs.polymarket.com/developers/builders/builder-profile)
- [py-order-utils](https://github.com/Polymarket/python-order-utils)
- [Gnosis Safe Contracts v1.3.0](https://github.com/safe-global/safe-contracts/tree/v1.3.0)
- [safe-eth-py](https://github.com/safe-global/safe-eth-py)
