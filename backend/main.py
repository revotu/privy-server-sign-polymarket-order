"""
FastAPI 应用入口 / FastAPI Application Entry Point
===================================================
Privy 服务端签名 × Polymarket 无弹窗下单 Demo 后端
Privy Server-Side Signing × Polymarket No-Popup Order Demo Backend

启动命令 / Start Command:
    cd backend
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

访问文档 / Access Docs:
    Swagger UI: http://localhost:8000/docs
    ReDoc:      http://localhost:8000/redoc

API 概览 / API Overview:
    POST /api/bind-signer              - 绑定 Key Quorum 到用户 wallet（一次性）
    GET  /api/markets/{condition_id}   - 获取市场信息
    POST /api/derive-clob-credentials  - 派生 CLOB API 凭据（首次）
    POST /api/place-order              - 服务端代签下单（核心功能，无弹窗）
    GET  /api/signer-status/{id}       - 查询 signer 状态（调试用）
    GET  /health                       - 健康检查
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import order, signer


# ============================================================
# 生命周期管理 / Lifecycle Management
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的初始化/清理逻辑 / Initialization/cleanup on app start and shutdown"""
    # 启动时验证必要的配置
    # Validate required configuration on startup
    print("=" * 60)
    print("Privy Server-Side Signing × Polymarket Demo")
    print("=" * 60)
    print(f"Privy App ID: {settings.privy_app_id[:8]}...")
    print(f"Key Quorum ID: {settings.privy_key_quorum_id}")
    print(f"CLOB Host: {settings.polymarket_clob_host}")
    print(f"Chain ID: {settings.polymarket_chain_id} (Polygon)")
    print("=" * 60)
    print("文档 / Docs: http://localhost:8000/docs")
    print("=" * 60)

    yield

    # 关闭时的清理（如有需要）/ Cleanup on shutdown (if needed)
    print("服务器关闭 / Server shutting down")


# ============================================================
# FastAPI 应用实例 / FastAPI Application Instance
# ============================================================

app = FastAPI(
    title="Privy Server-Side Signing × Polymarket Demo",
    description="""
## 概述 / Overview

这是一个演示如何通过 Privy 服务端授权密钥实现 Polymarket 下单无弹窗签名的参考实现。
This is a reference implementation demonstrating Polymarket order signing without user popups
via Privy server-side authorization keys.

## 架构 / Architecture

```
Flutter App → FastAPI 后端 → Privy API (TEE 签名) → Polymarket CLOB
Flutter App → FastAPI Backend → Privy API (TEE signing) → Polymarket CLOB
```

## 前提条件 / Prerequisites

1. 生成 P256 密钥对：`python scripts/generate_auth_key.py`
2. 在 Privy Dashboard 注册 Key Quorum
3. 配置 `.env` 文件
4. 用户首次登录后调用 `/api/bind-signer`
5. 调用 `/api/derive-clob-credentials` 获取 CLOB API 凭据

完成后即可调用 `/api/place-order` 实现无弹窗下单。
""",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ============================================================
# 中间件 / Middleware
# ============================================================

# CORS 配置（允许 Flutter Web / 本地开发访问）
# CORS configuration (allow Flutter Web / local dev access)
app.add_middleware(
    CORSMiddleware,
    # 生产环境应限制为你的域名 / Production: restrict to your domain
    allow_origins=["*"] if settings.debug else ["https://your-production-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 路由注册 / Route Registration
# ============================================================

# Signer 管理路由 / Signer management routes
# 包含 POST /api/bind-signer, GET /api/signer-status/{wallet_id}
app.include_router(signer.router)

# 订单路由 / Order routes
# 包含 GET /api/markets/{id}, POST /api/derive-clob-credentials, POST /api/place-order
app.include_router(order.router)


# ============================================================
# 基础路由 / Base Routes
# ============================================================

@app.get("/health", tags=["system"])
async def health_check():
    """
    健康检查端点 / Health check endpoint.
    用于监控系统和部署验证 / Used for monitoring and deployment verification.
    """
    return {
        "status": "healthy",
        "privy_app_id": settings.privy_app_id[:8] + "...",
        "chain_id": settings.polymarket_chain_id,
        "clob_host": settings.polymarket_clob_host,
    }


@app.get("/", tags=["system"])
async def root():
    """根路由，返回 API 信息 / Root route, returns API info."""
    return {
        "name": "Privy Server-Side Signing × Polymarket Demo",
        "version": "1.0.0",
        "docs": "/docs",
        "description": "服务端代签 Polymarket 订单，用户无需弹窗确认 / Server-side signing for Polymarket, no user popup needed",
    }


# ============================================================
# 直接运行支持 / Direct Run Support
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
