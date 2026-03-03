"""
Provider balance endpoints — Moonshot/Kimi, OpenRouter, local models.
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter

from config import MOONSHOT_KIMI_KEY, OPEN_ROUTER_KEY

router = APIRouter(tags=["Providers"])
logger = logging.getLogger("aria.api.providers")


async def _fetch_kimi_balance() -> dict:
    """Fetch Moonshot/Kimi balance with 5s timeout."""
    if not MOONSHOT_KIMI_KEY:
        return {"provider": "Moonshot/Kimi", "status": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"Authorization": f"Bearer {MOONSHOT_KIMI_KEY}"}
            resp = await client.get("https://api.moonshot.ai/v1/users/me/balance", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "provider": "Moonshot/Kimi",
                    "available": data.get("data", {}).get("available_balance", 0),
                    "voucher": data.get("data", {}).get("voucher_balance", 0),
                    "cash": data.get("data", {}).get("cash_balance", 0),
                    "currency": data.get("data", {}).get("currency", "USD"),
                    "status": "ok",
                }
            return {"provider": "Moonshot/Kimi", "status": "error", "code": resp.status_code}
    except Exception as e:
        logger.warning("Moonshot/Kimi health check failed: %s", e)
        return {"provider": "Moonshot/Kimi", "status": "error", "error": str(e)[:100]}


async def _fetch_openrouter_balance() -> dict:
    """Fetch OpenRouter balance with 5s timeout."""
    if not OPEN_ROUTER_KEY:
        return {"provider": "OpenRouter", "status": "free_tier", "note": "Using free models only"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            headers = {"Authorization": f"Bearer {OPEN_ROUTER_KEY}"}
            resp = await client.get("https://openrouter.ai/api/v1/auth/key", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                limit_val = data.get("data", {}).get("limit")
                usage_val = data.get("data", {}).get("usage") or 0
                remaining = (limit_val - usage_val) if limit_val is not None else (-usage_val if usage_val > 0 else 0)
                return {
                    "provider": "OpenRouter",
                    "limit": limit_val,
                    "usage": usage_val,
                    "remaining": remaining,
                    "is_free_tier": limit_val is None,
                    "currency": "USD",
                    "status": "ok",
                }
            return {"provider": "OpenRouter", "status": "error", "code": resp.status_code}
    except Exception as e:
        logger.warning("OpenRouter health check failed: %s", e)
        return {"provider": "OpenRouter", "status": "error", "error": str(e)[:100]}


@router.get("/providers/balances")
async def api_provider_balances():
    # Fetch all provider balances in parallel (5s timeout each)
    kimi_result, openrouter_result = await asyncio.gather(
        _fetch_kimi_balance(),
        _fetch_openrouter_balance(),
        return_exceptions=True,
    )

    balances = {}
    # NOTE: "kimi" here is a PROVIDER label (Moonshot/Kimi), not a model name.
    # This dict key identifies the billing provider, not a specific model.
    balances["kimi"] = kimi_result if isinstance(kimi_result, dict) else {
        "provider": "Moonshot/Kimi", "status": "error", "error": str(kimi_result)[:100]
    }
    balances["openrouter"] = openrouter_result if isinstance(openrouter_result, dict) else {
        "provider": "OpenRouter", "status": "error", "error": str(openrouter_result)[:100]
    }
    balances["local"] = {
        "provider": "Local (MLX/Ollama)",
        "status": "free",
        "note": "No cost - runs on local hardware",
    }
    return balances
