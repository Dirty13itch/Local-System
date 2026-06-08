"""Content-aware LLM routing via Semantic Router.

Provides two capabilities:
1. Pre-routing: classify prompts via Semantic Router to preemptively
   route refusal-sensitive content to the uncensored local model.
2. Refusal fallback: retry with uncensored model when a cloud model
   returns a content policy refusal.

Usage in chat router::

    from .content_router import classify_content, is_refusal_error, SOVEREIGN_ROUTES

    route = await classify_content(last_user_message, client)
    if should_route_sovereign(route):
        body.model = "uncensored"

    # After getting response, check for refusal:
    if is_refusal_error(status_code, response_data):
        # retry with model="uncensored"
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("gateway.content_router")

# Semantic Router on DEV
SEMANTIC_ROUTER_URL = "http://localhost:8060/classify"

# Routes that must use sovereign/uncensored models
SOVEREIGN_ROUTES = frozenset({"refusal_sensitive", "sovereign_only"})

# Model alias for uncensored routing (JOSIEFIED via Ollama on WORKSHOP)
UNCENSORED_MODEL = "uncensored"

# Patterns in error responses that indicate content policy refusal
_REFUSAL_PATTERNS = (
    "content_policy",
    "content policy",
    "content_filter",
    "content filter",
    "content moderation",
    "refused to generate",
    "i cannot",
    "i can't",
    "i'm not able to",
    "as an ai",
    "goes against my",
    "violates our",
    "not appropriate",
    "harmful content",
    "i must decline",
    "i'm unable to",
    "inappropriate content",
    "safety guidelines",
    "cannot assist with",
    "responsible ai",
)


async def classify_content(
    text: str,
    client: httpx.AsyncClient | None = None,
    timeout: float = 3.0,
) -> str:
    """Classify text via Semantic Router.

    Returns the route name (e.g. ``cloud_safe``, ``refusal_sensitive``,
    ``sovereign_only``).  Defaults to ``cloud_safe`` on any error so
    that classification failures never block normal traffic.
    """
    if not text or not text.strip():
        return "cloud_safe"

    try:
        _client = client or httpx.AsyncClient()
        try:
            resp = await _client.post(
                SEMANTIC_ROUTER_URL,
                json={"text": text},
                timeout=timeout,
            )
            resp.raise_for_status()
            route = resp.json().get("route", "cloud_safe")
            if route in SOVEREIGN_ROUTES:
                logger.info(
                    "Content classified as %s — routing to uncensored",
                    route,
                    extra={"text_preview": text[:80]},
                )
            return route
        finally:
            if client is None:
                await _client.aclose()
    except Exception as e:
        logger.warning("Semantic Router classification failed: %s", e)
        return "cloud_safe"


def is_refusal_error(status_code: int, response_data: dict[str, Any]) -> bool:
    """Detect whether an LLM response is a content policy refusal.

    Checks both HTTP error responses and in-band refusals where the
    model returns 200 but the completion text is a polite refusal.
    """
    # HTTP-level content policy errors (400, 403, 451)
    if status_code in (400, 403, 451):
        error_msg = str(response_data.get("error", "")).lower()
        if any(p in error_msg for p in _REFUSAL_PATTERNS):
            return True

    # In-band refusal: model returns 200 but the content is a refusal
    if status_code == 200:
        try:
            content = (
                response_data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .lower()
            )
            # Only flag short responses that look like refusals
            # (long responses are probably legitimate even if they mention limits)
            if len(content) < 500:
                refusal_hits = sum(1 for p in _REFUSAL_PATTERNS if p in content)
                if refusal_hits >= 2:
                    return True
        except (IndexError, AttributeError):
            pass

    return False


def should_route_sovereign(route: str) -> bool:
    """Check if a classified route should use the uncensored model."""
    return route in SOVEREIGN_ROUTES
