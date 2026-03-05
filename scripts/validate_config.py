#!/usr/bin/env python3
"""Config validation — cross-checks settings against live services.

Usage: python scripts/validate_config.py
"""
import asyncio
import sys
import httpx
from local_system.config import get_settings


async def main():
    settings = get_settings()
    errors = []
    warnings = []

    print("=== Local-System Config Validator ===")
    print()

    # 1. Check inference hosts are reachable
    inference_endpoints = {
        "litellm": (settings.inference.litellm_host, "/health"),
        "vllm_reasoning": (settings.inference.vllm_reasoning_host, "/v1/models"),
        "vllm_coding": (settings.inference.vllm_coding_host, "/v1/models"),
        "vllm_fast": (settings.inference.vllm_fast_host, "/v1/models"),
        "vllm_embedding": (settings.inference.vllm_embedding_host, "/v1/models"),
    }

    async with httpx.AsyncClient(timeout=5.0) as http:
        for name, (host, path) in inference_endpoints.items():
            url = f"{host.rstrip('/')}{path}"
            try:
                resp = await http.get(url)
                if resp.status_code == 200:
                    print(f"  OK  {name}: {url}")
                elif resp.status_code == 401:
                    warnings.append(f"{name}: {url} returned 401 (auth issue)")
                    print(f"  WARN {name}: {url} -> 401")
                else:
                    warnings.append(f"{name}: {url} returned {resp.status_code}")
                    print(f"  WARN {name}: {url} -> {resp.status_code}")
            except Exception as e:
                errors.append(f"{name}: {url} unreachable ({e})")
                print(f"  FAIL {name}: {url} -> {e}")

    # 2. Check service ports match running processes
    import subprocess
    for svc, port in [("mind", 8710), ("memory", 8720), ("gateway", 8700)]:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True
        )
        if f":{port}" in result.stdout:
            print(f"  OK  {svc}: port {port} in use")
        else:
            errors.append(f"{svc}: nothing listening on port {port}")
            print(f"  FAIL {svc}: port {port} not in use")

    # 3. Check config port values match reality
    configured_ports = {
        "mind": getattr(settings.ports, "mind", None),
        "memory": getattr(settings.ports, "memory", None),
        "gateway": getattr(settings.ports, "gateway", None),
    }
    actual_ports = {"mind": 8710, "memory": 8720, "gateway": 8700}
    for svc, actual in actual_ports.items():
        configured = configured_ports.get(svc)
        if configured and configured != actual:
            warnings.append(
                f"{svc}: config says port {configured}, actually running on {actual}"
            )
            print(f"  WARN {svc}: config port {configured} != actual {actual}")

    # 4. Check database connectivity
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=settings.database.host,
            port=settings.database.port,
            database=settings.database.name,
            user=settings.database.user,
            password=settings.database.password,
            timeout=5,
        )
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        await conn.close()
        print(f"  OK  PostgreSQL: {len(tables)} tables")
    except Exception as e:
        errors.append(f"PostgreSQL: {e}")
        print(f"  FAIL PostgreSQL: {e}")

    # 5. Check Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(
            host=settings.redis.host,
            port=settings.redis.port,
            password=settings.redis.password or None,
            decode_responses=True,
        )
        await r.ping()
        await r.aclose()
        print(f"  OK  Redis: connected")
    except Exception as e:
        errors.append(f"Redis: {e}")
        print(f"  FAIL Redis: {e}")

    # 6. Check Qdrant
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(
                f"http://{settings.qdrant.host}:{settings.qdrant.port}/collections"
            )
            if resp.status_code == 200:
                collections = resp.json().get("result", {}).get("collections", [])
                print(f"  OK  Qdrant: {len(collections)} collections")
            else:
                warnings.append(f"Qdrant: status {resp.status_code}")
    except Exception as e:
        errors.append(f"Qdrant: {e}")
        print(f"  FAIL Qdrant: {e}")

    # Summary
    print()
    print("=== Summary ===")
    if errors:
        print(f"  ERRORS: {len(errors)}")
        for e in errors:
            print(f"    - {e}")
    if warnings:
        print(f"  WARNINGS: {len(warnings)}")
        for w in warnings:
            print(f"    - {w}")
    if not errors and not warnings:
        print("  All checks passed!")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
