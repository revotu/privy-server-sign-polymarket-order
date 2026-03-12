/// 订单相关数据模型 / Order-related data models

/// 下单请求模型 / Order placement request model
class PlaceOrderRequest {
  /// 用户的 Privy wallet ID / User's Privy wallet ID
  final String walletId;

  /// 用户的钱包地址（EOA）/ User's wallet address (EOA)
  final String walletAddress;

  /// 市场条件 ID / Market condition ID
  final String conditionId;

  /// 订单方向：BUY 或 SELL / Order side: BUY or SELL
  final String side;

  /// 订单价格（0-1）/ Order price (0-1)
  final double price;

  /// 订单数量 / Order size
  final double size;

  /// CLOB API Key
  final String clobApiKey;

  /// CLOB API Secret
  final String clobApiSecret;

  /// CLOB API Passphrase
  final String clobApiPassphrase;

  /// 是否为多结果市场 / Whether it's a multi-outcome market
  final bool negRisk;

  /// 订单类型：GTC, GTD, FOK, FAK / Order type: GTC, GTD, FOK, FAK
  final String orderType;

  const PlaceOrderRequest({
    required this.walletId,
    required this.walletAddress,
    required this.conditionId,
    required this.side,
    required this.price,
    required this.size,
    required this.clobApiKey,
    required this.clobApiSecret,
    required this.clobApiPassphrase,
    this.negRisk = false,
    this.orderType = 'GTC',
  });

  Map<String, dynamic> toJson() => {
        'wallet_id': walletId,
        'wallet_address': walletAddress,
        'condition_id': conditionId,
        'side': side,
        'price': price,
        'size': size,
        'clob_api_key': clobApiKey,
        'clob_api_secret': clobApiSecret,
        'clob_api_passphrase': clobApiPassphrase,
        'neg_risk': negRisk,
        'order_type': orderType,
      };
}

/// 下单响应模型 / Order placement response model
class PlaceOrderResponse {
  /// 是否成功 / Whether successful
  final bool success;

  /// Polymarket 订单 ID / Polymarket order ID
  final String orderId;

  /// 订单状态 / Order status
  final String status;

  /// 错误信息 / Error message
  final String errorMessage;

  const PlaceOrderResponse({
    required this.success,
    required this.orderId,
    required this.status,
    required this.errorMessage,
  });

  factory PlaceOrderResponse.fromJson(Map<String, dynamic> json) {
    return PlaceOrderResponse(
      success: json['success'] as bool? ?? false,
      orderId: json['order_id'] as String? ?? '',
      status: json['status'] as String? ?? '',
      errorMessage: json['error_message'] as String? ?? '',
    );
  }
}

/// 市场信息模型 / Market info model
class MarketInfo {
  final String conditionId;
  final String question;
  final List<MarketToken> tokens;
  final double minimumTickSize;
  final double minimumOrderSize;
  final bool negRisk;
  final bool active;

  const MarketInfo({
    required this.conditionId,
    required this.question,
    required this.tokens,
    required this.minimumTickSize,
    required this.minimumOrderSize,
    required this.negRisk,
    required this.active,
  });

  factory MarketInfo.fromJson(Map<String, dynamic> json) {
    return MarketInfo(
      conditionId: json['condition_id'] as String? ?? '',
      question: json['question'] as String? ?? '',
      tokens: (json['tokens'] as List<dynamic>?)
              ?.map((t) => MarketToken.fromJson(t as Map<String, dynamic>))
              .toList() ??
          [],
      minimumTickSize:
          double.tryParse(json['minimum_tick_size']?.toString() ?? '0') ?? 0.0,
      minimumOrderSize:
          double.tryParse(json['minimum_order_size']?.toString() ?? '0') ?? 0.0,
      negRisk: json['neg_risk'] as bool? ?? false,
      active: json['active'] as bool? ?? false,
    );
  }
}

/// 市场 Token 模型 / Market token model
class MarketToken {
  final String tokenId;
  final String outcome; // "YES" 或 "NO" / "YES" or "NO"

  const MarketToken({required this.tokenId, required this.outcome});

  factory MarketToken.fromJson(Map<String, dynamic> json) {
    return MarketToken(
      tokenId: json['token_id'] as String? ?? '',
      outcome: json['outcome'] as String? ?? '',
    );
  }
}

/// CLOB API 凭据模型 / CLOB API credentials model
class ClobCredentials {
  final String apiKey;
  final String apiSecret;
  final String apiPassphrase;

  const ClobCredentials({
    required this.apiKey,
    required this.apiSecret,
    required this.apiPassphrase,
  });

  Map<String, dynamic> toJson() => {
        'api_key': apiKey,
        'api_secret': apiSecret,
        'api_passphrase': apiPassphrase,
      };
}
