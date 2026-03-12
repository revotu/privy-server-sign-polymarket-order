import 'package:privy/privy.dart';

/// Privy 服务封装 / Privy Service Wrapper
///
/// 封装 Privy Flutter SDK 的登录、用户信息获取等操作。
/// Wraps Privy Flutter SDK login, user info retrieval, and other operations.
///
/// 重要说明 / Important Notes:
///   - 登录/获取 JWT 等操作在前端完成
///   - 钱包签名（addSigners, signTypedData 等）通过后端 API 完成
///   - Flutter SDK 不直接支持 addSigners，需要后端中转
///
///   - Login/JWT retrieval operations are done on the frontend
///   - Wallet signing (addSigners, signTypedData etc.) done via backend API
///   - Flutter SDK doesn't directly support addSigners, needs backend relay

class PrivyService {
  /// Privy 单例实例 / Privy singleton instance
  /// 在 main.dart 中初始化后全局可用 / Globally available after init in main.dart
  late final Privy _privy;

  PrivyService(this._privy);

  // ----------------------------------------------------------
  // 用户状态 / User State
  // ----------------------------------------------------------

  /// 当前是否已登录 / Whether currently logged in
  bool get isLoggedIn => _privy.authState is AuthStateAuthenticated;

  /// 获取当前用户 / Get current user
  PrivyUser? get currentUser {
    final state = _privy.authState;
    if (state is AuthStateAuthenticated) {
      return state.user;
    }
    return null;
  }

  /// 获取用户的第一个 embedded Ethereum wallet
  /// Gets user's first embedded Ethereum wallet
  EmbeddedEthereumWallet? get embeddedWallet {
    return currentUser?.embeddedEthereumWallets.firstOrNull;
  }

  /// 获取用户钱包地址 / Get user wallet address
  String? get walletAddress => embeddedWallet?.address;

  /// 获取用户 wallet ID（非地址，是 Privy 内部 ID）
  /// Gets user wallet ID (not address, it's Privy's internal ID)
  ///
  /// 注意：wallet ID 格式如 "wallet_abc123..."，用于 Privy API 调用
  /// Note: wallet ID format like "wallet_abc123...", used for Privy API calls
  String? get walletId => embeddedWallet?.id;

  // ----------------------------------------------------------
  // 认证操作 / Authentication Operations
  // ----------------------------------------------------------

  /// 用邮箱登录 / Login with email
  ///
  /// Privy 会引导用户完成 OTP 验证，首次登录自动创建 embedded wallet。
  /// Privy guides user through OTP verification, auto-creates embedded wallet on first login.
  ///
  /// Args:
  ///   email: 用户邮箱 / User email
  Future<void> loginWithEmail(String email) async {
    await _privy.email.sendCode(email);
    // 注意：此处只发送 OTP 码，验证码由用户输入后调用 loginWithEmailCode
    // Note: This only sends OTP code; call loginWithEmailCode after user inputs code
  }

  /// 验证邮箱 OTP 完成登录 / Verify email OTP to complete login
  ///
  /// Args:
  ///   email: 用户邮箱 / User email
  ///   code: 用户收到的 6 位 OTP 码 / 6-digit OTP code received by user
  Future<PrivyUser?> loginWithEmailCode(String email, String code) async {
    final result = await _privy.email.loginWithCode(
      email,
      code,
    );

    return result.fold(
      onSuccess: (user) => user,
      onFailure: (error) {
        throw Exception('登录失败 / Login failed: ${error.message}');
      },
    );
  }

  /// 退出登录 / Logout
  Future<void> logout() async {
    await _privy.logout();
  }

  // ----------------------------------------------------------
  // JWT 获取 / JWT Retrieval
  // ----------------------------------------------------------

  /// 获取用户的 Privy access token（JWT）
  /// Gets user's Privy access token (JWT)
  ///
  /// 此 token 传给后端用于：
  /// This token is passed to the backend for:
  ///   1. 绑定 Key Quorum signer（addSigner 需要用户授权）
  ///   1. Binding Key Quorum signer (addSigner requires user auth)
  ///   2. 验证请求来自合法用户 / Verifying request comes from legitimate user
  ///
  /// 注意：JWT 会过期，每次使用前应重新获取
  /// Note: JWT expires, should fetch fresh before each use
  Future<String?> getAccessToken() async {
    return await _privy.getAccessToken();
  }

  // ----------------------------------------------------------
  // 钱包操作（需要通过后端）/ Wallet Operations (via backend)
  // ----------------------------------------------------------

  /// 检查钱包是否已经绑定了服务端 signer
  /// Checks if wallet already has server signer bound
  ///
  /// 通过检查 wallet 的 delegated 标志来判断
  /// Determined by checking wallet's delegated flag
  bool get isSignerBound {
    final wallet = embeddedWallet;
    if (wallet == null) return false;
    // Privy Flutter SDK 中通过 delegated 字段判断是否已有 signer
    // In Privy Flutter SDK, delegated field indicates whether signer is bound
    return wallet.delegated ?? false;
  }
}

/// 扩展：为 List 添加 firstOrNull
/// Extension: Add firstOrNull to List
extension ListExtension<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
