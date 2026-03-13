import 'package:flutter/material.dart';
import 'package:privy_flutter/privy_flutter.dart';

import 'config.dart';
import 'screens/home_screen.dart';
import 'services/backend_service.dart';
import 'services/privy_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Privy.init() 是工厂方法，不能直接 Privy(...)
  // Privy.init() is the factory method, cannot use Privy(...) directly
  final privy = Privy.init(
    config: PrivyConfig(
      appId: AppConfig.privyAppId,
      appClientId: AppConfig.privyAppClientId,
    ),
  );

  // awaitReady() 已废弃，用 getAuthState() 代替
  // awaitReady() is deprecated, use getAuthState() instead
  await privy.getAuthState();

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
        privyService: PrivyService(privy),
        backendService: BackendService(),
      ),
    );
  }
}
