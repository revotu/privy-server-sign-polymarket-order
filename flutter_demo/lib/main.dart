/// Privy 服务端签名 × Polymarket 无弹窗下单 Flutter Demo
///
/// 演示完整流程 / Demonstrates complete flow:
///   1. 用 Privy 邮箱登录，获取 embedded Ethereum wallet
///   2. 将服务端 Key Quorum 绑定为 wallet signer（一次性）
///   3. 下单时服务端用 P256 授权密钥代替用户签名（无弹窗！）
///
///   1. Login with Privy email, get embedded Ethereum wallet
///   2. Bind server Key Quorum as wallet signer (one-time)
///   3. Server uses P256 auth key to sign orders on behalf of user (no popup!)
///
/// 运行 / Run:
///   flutter pub get
///   flutter run
///
/// 注意 / Note:
///   运行前需在 config.dart 中填入真实的 PRIVY_APP_ID
///   Before running, fill in real PRIVY_APP_ID in config.dart

import 'package:flutter/material.dart';
import 'package:privy/privy.dart';

import 'config.dart';
import 'screens/home_screen.dart';
import 'services/backend_service.dart';
import 'services/privy_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 初始化 Privy SDK / Initialize Privy SDK
  // App ID 是公开值，可以硬编码在前端 / App ID is public, safe to hardcode in frontend
  final privy = Privy(
    config: PrivyConfig(
      appId: AppConfig.privyAppId,
      // 登录方法：只启用邮箱登录（可根据需要添加其他方式）
      // Login methods: only enable email (can add others as needed)
      loginMethods: [LoginMethod.email],
    ),
  );

  // 等待 Privy SDK 初始化完成 / Wait for Privy SDK initialization
  await privy.awaitReady();

  runApp(PrivyPolymarketApp(privy: privy));
}

class PrivyPolymarketApp extends StatelessWidget {
  final Privy privy;

  const PrivyPolymarketApp({super.key, required this.privy});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Privy × Polymarket Demo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepPurple,
          brightness: Brightness.light,
        ),
        useMaterial3: true,
      ),
      home: HomeScreen(
        // 注入 Privy 服务 / Inject Privy service
        privyService: PrivyService(privy),
        // 注入后端 API 服务 / Inject backend API service
        backendService: BackendService(),
      ),
    );
  }
}
