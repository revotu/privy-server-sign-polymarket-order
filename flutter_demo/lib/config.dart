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
  ///
  /// 替换为你的真实 App ID / Replace with your real App ID
  static const String privyAppId = 'YOUR_PRIVY_APP_ID_HERE';

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
  static const String demoConditionId =
      '0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee3a7386ad423d9dd9b';
}
