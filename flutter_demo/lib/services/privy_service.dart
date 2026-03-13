import 'package:privy_flutter/privy_flutter.dart';

/// Privy 服务封装 / Privy Service Wrapper
class PrivyService {
  final Privy _privy;

  // 登录后缓存的用户对象 / Cached user object after login
  PrivyUser? _cachedUser;

  PrivyService(this._privy);

  // ----------------------------------------------------------
  // 用户状态 / User State
  // ----------------------------------------------------------

  bool get isLoggedIn => _privy.currentAuthState.isAuthenticated;

  EmbeddedEthereumWallet? get embeddedWallet =>
      _cachedUser?.embeddedEthereumWallets.firstOrNull;

  String? get walletAddress => embeddedWallet?.address;

  String? get walletId => embeddedWallet?.id;

  // ----------------------------------------------------------
  // 认证操作 / Authentication Operations
  // ----------------------------------------------------------

  /// 发送邮箱 OTP / Send email OTP
  Future<void> loginWithEmail(String email) async {
    final result = await _privy.email.sendCode(email);
    PrivyException? err;
    result.fold(
      onSuccess: (_) {},
      onFailure: (e) { err = e; },
    );
    if (err != null) {
      throw Exception('发送 OTP 失败 / Failed to send OTP: ${err!.message}');
    }
  }

  /// 验证 OTP 完成登录 / Verify OTP to complete login
  Future<PrivyUser?> loginWithEmailCode(String email, String code) async {
    final result = await _privy.email.loginWithCode(
      code: code,
      email: email,
    );

    PrivyUser? user;
    PrivyException? err;
    result.fold(
      onSuccess: (u) { user = u; },
      onFailure: (e) { err = e; },
    );

    if (err != null) {
      throw Exception('登录失败 / Login failed: ${err!.message}');
    }

    // 用 final 局部变量承接，Dart null safety 才能做类型提升
    // Use final local variable so Dart null safety can promote the type
    final loggedInUser = user;
    if (loggedInUser == null) return null;

    _cachedUser = loggedInUser;

    // 确保有 embedded wallet / Ensure embedded wallet exists
    if (loggedInUser.embeddedEthereumWallets.isEmpty) {
      await loggedInUser.createEthereumWallet();
      _cachedUser = await _privy.getUser();
    }

    return _cachedUser;
  }

  /// 退出登录 / Logout
  Future<void> logout() async {
    await _privy.logout();
    _cachedUser = null;
  }

  // ----------------------------------------------------------
  // JWT 获取 / JWT Retrieval
  // ----------------------------------------------------------

  /// 获取用户 access token（JWT）/ Get user access token (JWT)
  Future<String?> getAccessToken() async {
    final user = _cachedUser ?? await _privy.getUser();
    if (user == null) return null;

    final result = await user.getAccessToken();
    String? token;
    PrivyException? err;
    result.fold(
      onSuccess: (t) { token = t; },
      onFailure: (e) { err = e; },
    );

    if (err != null) {
      throw Exception('获取 JWT 失败 / Failed to get JWT: ${err!.message}');
    }
    return token;
  }
}

extension ListExtension<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
