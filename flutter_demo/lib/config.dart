/// 前端配置 / Frontend Configuration
///
/// 存放前端所需的公开配置信息（不含任何 secret）。
/// Contains public configuration for the frontend (no secrets).
///
/// ⚠️ 注意 / NOTE:
///   - PRIVY_APP_ID 是公开值，可以放在前端代码中
///   - PRIVY_APP_ID is a public value, safe to include in frontend code
///   - PRIVY_APP_SECRET 等 secret 绝对不能出现在前端！
///   - PRIVY_APP_SECRET and other secrets must NEVER appear in frontend!

class AppConfig {
  AppConfig._(); // 防止实例化 / Prevent instantiation

  // ----------------------------------------------------------
  // Privy 配置 / Privy Configuration
  // ----------------------------------------------------------

  /// Privy App ID（公开值，从 https://dashboard.privy.io 获取）
  /// Privy App ID (public value, get from https://dashboard.privy.io)
  static const String privyAppId = 'cmkff26ru00zcjo0cwcfy3def';

  /// Privy App Client ID（从 Dashboard > App Settings > Clients 创建并获取）
  /// Privy App Client ID (create and get from Dashboard > App Settings > Clients)
  ///
  /// ⚠️ 需要在 Privy Dashboard 手动创建一个 Flutter Client 才能获取此 ID
  /// ⚠️ Must manually create a Flutter Client in Privy Dashboard to get this ID
  static const String privyAppClientId = 'client-WY6V7jxg3DV5raFGn7TS6h6paDDHTeA69xqppVeA5C6Ds';

  // ----------------------------------------------------------
  // 后端 API 配置 / Backend API Configuration
  // ----------------------------------------------------------

  /// FastAPI 后端地址 / FastAPI backend URL
  ///
  /// 本地开发：http://localhost:8000
  /// Local development: http://localhost:8000
  ///
  /// Android 模拟器连接宿主机：http://10.0.2.2:8000
  /// Android emulator to host: http://10.0.2.2:8000
  ///
  /// iOS 模拟器连接宿主机：http://localhost:8000
  /// iOS simulator to host: http://localhost:8000
  static const String backendBaseUrl = 'http://localhost:8000';

  // ----------------------------------------------------------
  // Polymarket 配置 / Polymarket Configuration
  // ----------------------------------------------------------

  /// Polygon 主网链 ID / Polygon mainnet chain ID
  static const int polygonChainId = 137;

  /// 用于演示的示例市场 condition ID（可替换为真实市场）
  /// Example market condition ID for demo (replace with real market)
  ///
  /// 示例：Will Dogecoin hit $1 before 2025?
  /// Example: Will Dogecoin hit $1 before 2025?
  /// 使用 /sampling-markets 中的活跃市场（Cap on gambling loss deductions）
  /// Uses an active market from /sampling-markets
  static const String demoConditionId =
      '0x5a8c5193008f76941e75598a31ef2915125ef0a8a7cfcb7369e8c451511c4452';
}
