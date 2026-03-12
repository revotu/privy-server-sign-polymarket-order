# Flutter Demo - Privy × Polymarket 无弹窗下单

## 简介 / Overview

演示 Flutter 前端如何配合后端，实现 Polymarket 下单时用户无需弹窗确认签名。

Demonstrates how Flutter frontend works with backend to enable Polymarket order placement without user popup confirmations.

## 前提条件 / Prerequisites

- Flutter SDK >= 3.16.0
- 后端服务已启动（`cd backend && uvicorn main:app --reload`）
- 已配置 `config.dart` 中的 `privyAppId`

## 运行步骤 / Steps

```bash
cd flutter_demo
flutter pub get
flutter run
```

## 配置 / Configuration

编辑 `lib/config.dart` / Edit `lib/config.dart`:

```dart
static const String privyAppId = 'YOUR_REAL_PRIVY_APP_ID';
static const String backendBaseUrl = 'http://localhost:8000';
```

## 界面说明 / UI Description

**步骤 1 / Step 1**: 用邮箱登录 Privy，自动创建 embedded wallet

**步骤 2 / Step 2**: 点击"绑定 Signer"，授权后端代替你签名（一次性），然后派生 CLOB 凭据

**步骤 3 / Step 3**: 填写订单参数，点击下单，后端全程代签，无弹窗！
