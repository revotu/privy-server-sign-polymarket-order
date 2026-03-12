import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config.dart';
import '../models/order_request.dart';

/// 后端 API 服务 / Backend API Service
///
/// 封装所有与 FastAPI 后端的 HTTP 通信。
/// Encapsulates all HTTP communication with the FastAPI backend.
///
/// 所有涉及签名的操作都通过后端完成（服务端用 P256 私钥授权 Privy API）。
/// All signing operations are done via the backend (server uses P256 key to authorize Privy API).
class BackendService {
  final String _baseUrl;

  BackendService({String? baseUrl}) : _baseUrl = baseUrl ?? AppConfig.backendBaseUrl;

  // ----------------------------------------------------------
  // 通用 HTTP 方法 / Common HTTP Methods
  // ----------------------------------------------------------

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
      };

  /// 发送 POST 请求 / Send POST request
  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, dynamic> body,
  ) async {
    final uri = Uri.parse('$_baseUrl$path');
    final response = await http.post(
      uri,
      headers: _headers,
      body: jsonEncode(body),
    );

    final data = jsonDecode(response.body) as Map<String, dynamic>;

    if (response.statusCode != 200) {
      final detail = data['detail'] ?? '未知错误 / Unknown error';
      throw BackendException(
        statusCode: response.statusCode,
        message: detail.toString(),
      );
    }

    return data;
  }

  /// 发送 GET 请求 / Send GET request
  Future<Map<String, dynamic>> _get(String path) async {
    final uri = Uri.parse('$_baseUrl$path');
    final response = await http.get(uri, headers: _headers);

    final data = jsonDecode(response.body) as Map<String, dynamic>;

    if (response.statusCode != 200) {
      final detail = data['detail'] ?? '未知错误 / Unknown error';
      throw BackendException(
        statusCode: response.statusCode,
        message: detail.toString(),
      );
    }

    return data;
  }

  // ----------------------------------------------------------
  // Signer 管理 / Signer Management
  // ----------------------------------------------------------

  /// 将服务端 Key Quorum 绑定到用户钱包（一次性操作）。
  /// Binds server Key Quorum to user wallet (one-time operation).
  ///
  /// 调用此接口后，服务端可以用 P256 私钥代替用户签名（无弹窗）。
  /// After calling this, the server can sign on behalf of the user with P256 key (no popup).
  ///
  /// Args:
  ///   walletId: 用户的 Privy wallet ID（从 PrivyService.walletId 获取）
  ///             User's Privy wallet ID (from PrivyService.walletId)
  ///   userJwt: 用户的 Privy access token（从 PrivyService.getAccessToken() 获取）
  ///            User's Privy access token (from PrivyService.getAccessToken())
  ///
  /// Returns:
  ///   是否成功绑定 / Whether binding was successful
  Future<bool> bindSigner({
    required String walletId,
    required String userJwt,
  }) async {
    final response = await _post('/api/bind-signer', {
      'wallet_id': walletId,
      'user_jwt': userJwt,
    });

    return response['success'] as bool? ?? false;
  }

  // ----------------------------------------------------------
  // 市场信息 / Market Information
  // ----------------------------------------------------------

  /// 获取 Polymarket 市场信息。
  /// Gets Polymarket market information.
  ///
  /// Args:
  ///   conditionId: 市场条件 ID / Market condition ID
  ///
  /// Returns:
  ///   市场信息，包含 token_id, tick_size 等 / Market info with token_id, tick_size etc.
  Future<MarketInfo> getMarket(String conditionId) async {
    final data = await _get('/api/markets/$conditionId');
    return MarketInfo.fromJson(data);
  }

  // ----------------------------------------------------------
  // CLOB API 凭据 / CLOB API Credentials
  // ----------------------------------------------------------

  /// 派生用户的 Polymarket CLOB API 凭据（首次使用时调用一次）。
  /// Derives user's Polymarket CLOB API credentials (call once on first use).
  ///
  /// 流程：后端用 Privy 服务端签名派生 CLOB 凭据（无弹窗）。
  /// Flow: backend derives CLOB credentials via Privy server-side signing (no popup).
  ///
  /// 注意：返回的凭据应安全存储，不要每次都重新派生。
  /// Note: Returned credentials should be stored securely, not re-derived every time.
  ///
  /// Args:
  ///   walletId: 用户的 Privy wallet ID / User's Privy wallet ID
  ///   walletAddress: 用户的钱包地址 / User's wallet address
  ///   userJwt: 用户的 Privy access token / User's Privy access token
  ///
  /// Returns:
  ///   CLOB API 凭据 / CLOB API credentials
  Future<ClobCredentials> deriveClobCredentials({
    required String walletId,
    required String walletAddress,
    required String userJwt,
  }) async {
    final response = await _post('/api/derive-clob-credentials', {
      'wallet_id': walletId,
      'wallet_address': walletAddress,
      'user_jwt': userJwt,
    });

    // ⚠️ 生产环境注意：凭据应存储在服务端，不应通过 API 返回 secret 给前端
    // ⚠️ Production note: credentials should be stored server-side, not returned to frontend
    // 此处为 Demo，简化了架构 / This is simplified for demo purposes
    return ClobCredentials(
      apiKey: response['api_key'] as String? ?? '',
      apiSecret: response['api_secret'] as String? ?? '',
      apiPassphrase: response['api_passphrase'] as String? ?? '',
    );
  }

  // ----------------------------------------------------------
  // 下单（核心功能）/ Place Order (Core Feature)
  // ----------------------------------------------------------

  /// ★ 核心功能：服务端代签并提交 Polymarket 订单（全程无弹窗）。
  /// ★ Core Feature: Server-side signing and submission of Polymarket order (no popup).
  ///
  /// 前端只需传入参数，服务端负责：
  /// Frontend only passes parameters; server handles:
  ///   1. 获取市场信息和手续费率 / Fetching market info and fee rate
  ///   2. 构建 EIP-712 订单结构 / Building EIP-712 order structure
  ///   3. 调用 Privy API 用 P256 密钥授权签名（无弹窗！）/ Privy API signing with P256 key (no popup!)
  ///   4. 提交签名订单到 Polymarket CLOB / Submitting signed order to Polymarket CLOB
  ///
  /// 前提条件 / Prerequisites:
  ///   - 用户已通过 bindSigner 绑定 Key Quorum / User has Key Quorum bound via bindSigner
  ///   - 用户已通过 deriveClobCredentials 获取 CLOB 凭据 / User has CLOB credentials via deriveClobCredentials
  ///   - 用户钱包有足够的 USDC.e 余额 / User wallet has sufficient USDC.e balance
  ///
  /// Args:
  ///   request: 下单请求参数 / Order placement request parameters
  ///
  /// Returns:
  ///   下单结果，包含 orderId 等 / Order result with orderId etc.
  Future<PlaceOrderResponse> placeOrder(PlaceOrderRequest request) async {
    final response = await _post('/api/place-order', request.toJson());
    return PlaceOrderResponse.fromJson(response);
  }

  // ----------------------------------------------------------
  // 健康检查 / Health Check
  // ----------------------------------------------------------

  /// 检查后端服务是否正常运行。
  /// Checks if backend service is running.
  Future<bool> checkHealth() async {
    try {
      final data = await _get('/health');
      return data['status'] == 'healthy';
    } catch (_) {
      return false;
    }
  }
}

// ----------------------------------------------------------
// 自定义异常 / Custom Exception
// ----------------------------------------------------------

/// 后端 API 异常 / Backend API exception
class BackendException implements Exception {
  final int statusCode;
  final String message;

  const BackendException({required this.statusCode, required this.message});

  @override
  String toString() => 'BackendException($statusCode): $message';
}
