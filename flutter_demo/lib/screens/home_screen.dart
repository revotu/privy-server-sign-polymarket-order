import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config.dart';
import '../models/order_request.dart';
import '../services/backend_service.dart';
import '../services/privy_service.dart';

/// 主界面 / Home Screen
///
/// 演示完整的 Privy 服务端签名 × Polymarket 下单流程。
/// Demonstrates the complete Privy server-side signing × Polymarket order flow.
///
/// 界面分三个步骤 / UI divided into three steps:
///   步骤 1: 用 Privy 登录，获取 embedded wallet
///   Step 1: Login with Privy, get embedded wallet
///
///   步骤 2: 绑定服务端 Key Quorum（一次性）
///   Step 2: Bind server Key Quorum (one-time)
///
///   步骤 3: 填写订单参数并下单（无弹窗！）
///   Step 3: Fill order params and place order (no popup!)
class HomeScreen extends StatefulWidget {
  final PrivyService privyService;
  final BackendService backendService;

  const HomeScreen({
    super.key,
    required this.privyService,
    required this.backendService,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  // ----------------------------------------------------------
  // 状态变量 / State Variables
  // ----------------------------------------------------------

  bool _isLoading = false;
  String _statusMessage = '';
  String _logOutput = '';

  // 登录相关 / Login related
  bool _showOtpField = false;
  final _emailController = TextEditingController(text: '');
  final _otpController = TextEditingController(text: '');

  // signer 绑定状态 / Signer binding status
  bool _signerBound = false;

  // CLOB 凭据状态 / CLOB credentials status
  bool _clobCredentialsDerived = false;
  String _clobApiKey = '';
  String _clobApiSecret = '';
  String _clobApiPassphrase = '';

  // 下单参数 / Order parameters
  final _conditionIdController = TextEditingController(
    text: AppConfig.demoConditionId,
  );
  String _selectedSide = 'BUY';
  final _priceController = TextEditingController(text: '0.01');
  final _sizeController = TextEditingController(text: '1.0');

  // 下单结果 / Order result
  String _lastOrderId = '';

  // ----------------------------------------------------------
  // 生命周期 / Lifecycle
  // ----------------------------------------------------------

  @override
  void initState() {
    super.initState();
    _loadPersistedState();
    _addLog('App 已启动 / App started');
    _addLog('后端地址 / Backend URL: ${AppConfig.backendBaseUrl}');
  }

  @override
  void dispose() {
    _emailController.dispose();
    _otpController.dispose();
    _conditionIdController.dispose();
    _priceController.dispose();
    _sizeController.dispose();
    super.dispose();
  }

  // ----------------------------------------------------------
  // 持久化状态 / Persisted State
  // ----------------------------------------------------------

  Future<void> _loadPersistedState() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _signerBound = prefs.getBool('signer_bound') ?? false;
      _clobApiKey = prefs.getString('clob_api_key') ?? '';
      _clobApiSecret = prefs.getString('clob_api_secret') ?? '';
      _clobApiPassphrase = prefs.getString('clob_api_passphrase') ?? '';
      _clobCredentialsDerived = _clobApiKey.isNotEmpty;
    });
  }

  Future<void> _saveSignerBound(bool bound) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('signer_bound', bound);
  }

  Future<void> _saveClobCredentials(ClobCredentials creds) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('clob_api_key', creds.apiKey);
    await prefs.setString('clob_api_secret', creds.apiSecret);
    await prefs.setString('clob_api_passphrase', creds.apiPassphrase);
  }

  // ----------------------------------------------------------
  // 日志 / Logging
  // ----------------------------------------------------------

  void _addLog(String message) {
    final timestamp = DateTime.now().toIso8601String().substring(11, 19);
    setState(() {
      _logOutput = '[$timestamp] $message\n$_logOutput';
    });
  }

  void _setStatus(String message, {bool isError = false}) {
    setState(() {
      _statusMessage = message;
    });
    _addLog(isError ? '❌ $message' : '✅ $message');
  }

  // ----------------------------------------------------------
  // 步骤 1: 登录 / Step 1: Login
  // ----------------------------------------------------------

  Future<void> _sendOtp() async {
    if (_emailController.text.isEmpty) {
      _setStatus('请输入邮箱地址 / Please enter email address', isError: true);
      return;
    }

    setState(() => _isLoading = true);
    _addLog('发送 OTP 到 ${_emailController.text} / Sending OTP to ${_emailController.text}');

    try {
      await widget.privyService.loginWithEmail(_emailController.text);
      setState(() => _showOtpField = true);
      _setStatus('OTP 已发送，请查收邮件 / OTP sent, please check email');
    } catch (e) {
      _setStatus('发送 OTP 失败 / Failed to send OTP: $e', isError: true);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _verifyOtp() async {
    if (_otpController.text.isEmpty) {
      _setStatus('请输入 OTP 码 / Please enter OTP code', isError: true);
      return;
    }

    setState(() => _isLoading = true);
    _addLog('验证 OTP 中 / Verifying OTP...');

    try {
      await widget.privyService.loginWithEmailCode(
        _emailController.text,
        _otpController.text,
      );
      _setStatus(
        '登录成功！钱包地址 / Logged in! Wallet: ${widget.privyService.walletAddress ?? "N/A"}',
      );
      setState(() => _showOtpField = false);
    } catch (e) {
      _setStatus('OTP 验证失败 / OTP verification failed: $e', isError: true);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _logout() async {
    await widget.privyService.logout();
    setState(() {
      _signerBound = false;
      _clobCredentialsDerived = false;
    });
    _addLog('已退出登录 / Logged out');
  }

  // ----------------------------------------------------------
  // 步骤 2: 绑定 Signer / Step 2: Bind Signer
  // ----------------------------------------------------------

  Future<void> _bindSigner() async {
    final walletId = widget.privyService.walletId;
    if (walletId == null) {
      _setStatus('无法获取 wallet ID，请重新登录 / Cannot get wallet ID, please re-login', isError: true);
      return;
    }

    setState(() => _isLoading = true);
    _addLog('绑定 Key Quorum signer 中 / Binding Key Quorum signer...');
    _addLog('Wallet ID: $walletId');

    try {
      // 获取用户 JWT（用于授权 wallet 修改）
      // Get user JWT (for authorizing wallet modification)
      final jwt = await widget.privyService.getAccessToken();
      if (jwt == null) {
        throw Exception('无法获取 JWT / Cannot get JWT');
      }

      _addLog('已获取用户 JWT / Got user JWT (${jwt.substring(0, 20)}...)');

      // 调用后端绑定 signer / Call backend to bind signer
      // 后端会用用户 JWT 调用 Privy API PATCH /wallets/{id}
      // Backend uses user JWT to call Privy API PATCH /wallets/{id}
      final success = await widget.backendService.bindSigner(
        walletId: walletId,
        userJwt: jwt,
      );

      if (success) {
        setState(() => _signerBound = true);
        await _saveSignerBound(true);
        _setStatus(
          'Key Quorum signer 绑定成功！后续下单无需弹窗 / '
          'Key Quorum signer bound! Future orders need no popup',
        );
      } else {
        _setStatus('绑定失败，请重试 / Binding failed, please retry', isError: true);
      }
    } catch (e) {
      _setStatus('绑定 signer 失败 / Failed to bind signer: $e', isError: true);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // ----------------------------------------------------------
  // CLOB 凭据派生 / CLOB Credentials Derivation
  // ----------------------------------------------------------

  Future<void> _deriveClobCredentials() async {
    final walletId = widget.privyService.walletId;
    final walletAddress = widget.privyService.walletAddress;

    if (walletId == null || walletAddress == null) {
      _setStatus('无法获取 wallet 信息 / Cannot get wallet info', isError: true);
      return;
    }

    setState(() => _isLoading = true);
    _addLog('派生 CLOB API 凭据中 / Deriving CLOB API credentials...');

    try {
      final jwt = await widget.privyService.getAccessToken();
      if (jwt == null) throw Exception('无法获取 JWT / Cannot get JWT');

      // 后端用 Privy 服务端签名（无弹窗！）派生 CLOB 凭据
      // Backend derives CLOB credentials via Privy server-side signing (no popup!)
      final creds = await widget.backendService.deriveClobCredentials(
        walletId: walletId,
        walletAddress: walletAddress,
        userJwt: jwt,
      );

      setState(() {
        _clobApiKey = creds.apiKey;
        _clobApiSecret = creds.apiSecret;
        _clobApiPassphrase = creds.apiPassphrase;
        _clobCredentialsDerived = true;
      });
      await _saveClobCredentials(creds);

      _setStatus(
        'CLOB API 凭据派生成功！/ CLOB credentials derived! Key: ${creds.apiKey.substring(0, 8)}...',
      );
    } catch (e) {
      _setStatus('派生 CLOB 凭据失败 / Failed to derive CLOB credentials: $e', isError: true);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // ----------------------------------------------------------
  // 步骤 3: 下单 / Step 3: Place Order
  // ----------------------------------------------------------

  Future<void> _placeOrder() async {
    final walletId = widget.privyService.walletId;
    final walletAddress = widget.privyService.walletAddress;

    if (walletId == null || walletAddress == null) {
      _setStatus('请先登录 / Please login first', isError: true);
      return;
    }

    if (!_signerBound) {
      _setStatus('请先绑定 signer / Please bind signer first', isError: true);
      return;
    }

    if (!_clobCredentialsDerived) {
      _setStatus('请先派生 CLOB 凭据 / Please derive CLOB credentials first', isError: true);
      return;
    }

    final price = double.tryParse(_priceController.text);
    final size = double.tryParse(_sizeController.text);

    if (price == null || size == null || price <= 0 || size <= 0) {
      _setStatus('价格和数量必须大于 0 / Price and size must be > 0', isError: true);
      return;
    }

    setState(() => _isLoading = true);
    _addLog('提交订单中 / Placing order...');
    _addLog('  市场 / Market: ${_conditionIdController.text.substring(0, 10)}...');
    _addLog('  方向 / Side: $_selectedSide');
    _addLog('  价格 / Price: $price');
    _addLog('  数量 / Size: $size');

    try {
      // ★ 核心调用：服务端代签下单，全程无弹窗！
      // ★ Core call: server-side signing, completely no popup!
      final response = await widget.backendService.placeOrder(
        PlaceOrderRequest(
          walletId: walletId,
          walletAddress: walletAddress,
          conditionId: _conditionIdController.text.trim(),
          side: _selectedSide,
          price: price,
          size: size,
          clobApiKey: _clobApiKey,
          clobApiSecret: _clobApiSecret,
          clobApiPassphrase: _clobApiPassphrase,
        ),
      );

      if (response.success || response.orderId.isNotEmpty) {
        setState(() => _lastOrderId = response.orderId);
        _setStatus(
          '下单成功！/ Order placed! ID: ${response.orderId.isNotEmpty ? response.orderId : "pending"}',
        );
        _addLog('  状态 / Status: ${response.status}');
      } else {
        _setStatus(
          '下单失败 / Order failed: ${response.errorMessage.isNotEmpty ? response.errorMessage : "Unknown error"}',
          isError: true,
        );
      }
    } catch (e) {
      _setStatus('下单失败 / Order placement failed: $e', isError: true);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // ----------------------------------------------------------
  // UI 构建 / UI Build
  // ----------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final isLoggedIn = widget.privyService.isLoggedIn;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Privy × Polymarket 无弹窗下单 Demo'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          if (isLoggedIn)
            IconButton(
              icon: const Icon(Icons.logout),
              onPressed: _logout,
              tooltip: '退出登录 / Logout',
            ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // 状态消息 / Status message
                  if (_statusMessage.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.all(12),
                      margin: const EdgeInsets.only(bottom: 16),
                      decoration: BoxDecoration(
                        color: _statusMessage.contains('失败') || _statusMessage.contains('failed')
                            ? Colors.red[50]
                            : Colors.green[50],
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(
                          color: _statusMessage.contains('失败') || _statusMessage.contains('failed')
                              ? Colors.red
                              : Colors.green,
                        ),
                      ),
                      child: Text(_statusMessage, style: const TextStyle(fontSize: 14)),
                    ),

                  // --------------------------------------------------
                  // 步骤 1: 登录 / Step 1: Login
                  // --------------------------------------------------
                  _buildStepCard(
                    step: 1,
                    title: '登录 / Login',
                    subtitle: isLoggedIn
                        ? '已登录 / Logged in: ${widget.privyService.walletAddress ?? "N/A"}'
                        : '用邮箱登录获取 embedded wallet / Login with email to get embedded wallet',
                    isCompleted: isLoggedIn,
                    child: isLoggedIn
                        ? _buildLoggedInInfo()
                        : _buildLoginForm(),
                  ),

                  const SizedBox(height: 12),

                  // --------------------------------------------------
                  // 步骤 2: 绑定 Signer / Step 2: Bind Signer
                  // --------------------------------------------------
                  _buildStepCard(
                    step: 2,
                    title: '绑定 Key Quorum Signer / Bind Key Quorum Signer',
                    subtitle: _signerBound
                        ? '已绑定！后端可代替用户签名 / Bound! Backend can sign on behalf of user'
                        : '一次性操作：授权后端代签 / One-time: authorize backend to sign',
                    isCompleted: _signerBound,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Text(
                          '绑定后，服务端 P256 密钥可代替用户签名，无需弹窗确认。\n'
                          'After binding, server P256 key can sign for user, no popup needed.',
                          style: TextStyle(fontSize: 12, color: Colors.grey),
                        ),
                        const SizedBox(height: 8),
                        ElevatedButton(
                          onPressed: (isLoggedIn && !_signerBound) ? _bindSigner : null,
                          child: Text(
                            _signerBound
                                ? '✅ 已绑定 / Already Bound'
                                : '绑定 Signer / Bind Signer',
                          ),
                        ),
                        const SizedBox(height: 8),
                        ElevatedButton(
                          onPressed: (isLoggedIn && _signerBound && !_clobCredentialsDerived)
                              ? _deriveClobCredentials
                              : null,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.orange[700],
                            foregroundColor: Colors.white,
                          ),
                          child: Text(
                            _clobCredentialsDerived
                                ? '✅ CLOB 凭据已派生 / CLOB Credentials Derived'
                                : '派生 CLOB API 凭据 / Derive CLOB Credentials',
                          ),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 12),

                  // --------------------------------------------------
                  // 步骤 3: 下单 / Step 3: Place Order
                  // --------------------------------------------------
                  _buildStepCard(
                    step: 3,
                    title: '服务端代签下单（无弹窗！）/ Server-Side Order (No Popup!)',
                    subtitle: '填写订单参数，服务端全程代签 / Fill order params, server handles all signing',
                    isCompleted: _lastOrderId.isNotEmpty,
                    child: _buildOrderForm(),
                  ),

                  const SizedBox(height: 12),

                  // --------------------------------------------------
                  // 日志输出 / Log Output
                  // --------------------------------------------------
                  ExpansionTile(
                    title: const Text('调试日志 / Debug Log'),
                    children: [
                      Container(
                        height: 200,
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: Colors.black87,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: SingleChildScrollView(
                          child: Text(
                            _logOutput,
                            style: const TextStyle(
                              color: Colors.green,
                              fontSize: 11,
                              fontFamily: 'monospace',
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
    );
  }

  // ----------------------------------------------------------
  // UI 组件 / UI Components
  // ----------------------------------------------------------

  Widget _buildStepCard({
    required int step,
    required String title,
    required String subtitle,
    required bool isCompleted,
    required Widget child,
  }) {
    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: isCompleted ? Colors.green : Colors.blue,
                  radius: 14,
                  child: isCompleted
                      ? const Icon(Icons.check, size: 16, color: Colors.white)
                      : Text('$step', style: const TextStyle(color: Colors.white, fontSize: 12)),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
                      Text(subtitle, style: const TextStyle(fontSize: 12, color: Colors.grey)),
                    ],
                  ),
                ),
              ],
            ),
            const Divider(height: 16),
            child,
          ],
        ),
      ),
    );
  }

  Widget _buildLoggedInInfo() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '钱包地址 / Wallet Address:\n${widget.privyService.walletAddress ?? "N/A"}',
          style: const TextStyle(fontSize: 12),
        ),
        const SizedBox(height: 4),
        Text(
          'Wallet ID: ${widget.privyService.walletId ?? "N/A"}',
          style: const TextStyle(fontSize: 12, color: Colors.grey),
        ),
      ],
    );
  }

  Widget _buildLoginForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _emailController,
          decoration: const InputDecoration(
            labelText: '邮箱 / Email',
            hintText: 'your@email.com',
            border: OutlineInputBorder(),
            isDense: true,
          ),
          keyboardType: TextInputType.emailAddress,
        ),
        const SizedBox(height: 8),
        if (!_showOtpField)
          ElevatedButton(
            onPressed: _sendOtp,
            child: const Text('发送 OTP / Send OTP'),
          )
        else ...[
          TextField(
            controller: _otpController,
            decoration: const InputDecoration(
              labelText: 'OTP 验证码 / OTP Code',
              hintText: '123456',
              border: OutlineInputBorder(),
              isDense: true,
            ),
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 8),
          ElevatedButton(
            onPressed: _verifyOtp,
            child: const Text('验证并登录 / Verify & Login'),
          ),
          TextButton(
            onPressed: () => setState(() => _showOtpField = false),
            child: const Text('重新发送 / Resend'),
          ),
        ],
      ],
    );
  }

  Widget _buildOrderForm() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        TextField(
          controller: _conditionIdController,
          decoration: const InputDecoration(
            labelText: '市场 Condition ID / Market Condition ID',
            border: OutlineInputBorder(),
            isDense: true,
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                value: _selectedSide,
                decoration: const InputDecoration(
                  labelText: '方向 / Side',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
                items: const [
                  DropdownMenuItem(value: 'BUY', child: Text('BUY 买入')),
                  DropdownMenuItem(value: 'SELL', child: Text('SELL 卖出')),
                ],
                onChanged: (v) => setState(() => _selectedSide = v!),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _priceController,
                decoration: const InputDecoration(
                  labelText: '价格 / Price (0-1)',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: _sizeController,
                decoration: const InputDecoration(
                  labelText: '数量 / Size',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ElevatedButton(
          onPressed: (widget.privyService.isLoggedIn && _signerBound && _clobCredentialsDerived)
              ? _placeOrder
              : null,
          style: ElevatedButton.styleFrom(
            backgroundColor: Colors.purple[700],
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(vertical: 12),
          ),
          child: const Text(
            '★ 服务端代签下单（无弹窗！）\n★ Server-Side Order (No Popup!)',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13),
          ),
        ),
        if (_lastOrderId.isNotEmpty) ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.green[50],
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              '最近订单 ID / Last Order ID:\n$_lastOrderId',
              style: const TextStyle(fontSize: 12),
            ),
          ),
        ],
      ],
    );
  }
}
