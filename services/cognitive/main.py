"""Cognitive Workspace — Global Workspace Theory (GWT) implementation.

The cognitive workspace is the attention mechanism of the system:
  1. Specialized modules (agents) operate in parallel
  2. Each module bids for attention based on relevance to the current context
  3. The winning coalition broadcasts its output to all other modules
  4. A Continuous State Tensor (CST) maintains coherent awareness across cycles
  5. Predictive processing generates expectations and learns from mismatches

This is NOT metaphorical — it literally routes messages between specialist agents
through a competitive attention mechanism.

Runs on hydra-storage (EPYC 7663 — ideal for parallel agent orchestration).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException

from local_system.config import get_settings
from local_system.models import (
    BidRequest,
    BroadcastMessage,
    CognitiveState,
    HealthResponse,
    SpecialistType,
)
from local_system.utils import generate_id, setup_logging

settings = get_settings()
logger = setup_logging("cognitive", settings)

# In-memory cognitive state (will be persisted to Redis)
_state = CognitiveState()
_specialists: dict[SpecialistType, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Cognitive workspace starting")
    app.state.start_time = time.time()

    # Register built-in specialists
    _register_default_specialists()

    # Load last cognitive state from Redis
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://localhost:{settings.ports.memory}/v1/memory/working"
            )
            if resp.status_code == 200:
                from local_system.models import WorkingContext
                _state.working_context = WorkingContext.model_validate(resp.json())
                logger.info("Restored working context from memory service")
    except Exception as e:
        logger.warning(f"Could not restore working context: {e}")

    yield
    logger.info("Cognitive workspace stopped")


app = FastAPI(
    title="Athanor Cognitive Workspace",
    version="0.1.0",
    lifespan=lifespan,
)


def _register_default_specialists():
    """Register the default specialist modules."""
    global _specialists
    _specialists = {
        SpecialistType.RESEARCH: {
            "name": "Research Agent",
            "model": "llama-70b",
            "description": "Autonomous research, cross-domain connections, paper analysis",
            "active": True,
        },
        SpecialistType.CODING: {
            "name": "Coding Agent",
            "model": "llama-70b",
            "description": "Code generation, debugging, architecture design",
            "active": True,
        },
        SpecialistType.CREATIVE: {
            "name": "Creative Agent (Empire of Broken Queens)",
            "model": "llama-70b",
            "description": "Visual novel dialogue, character consistency, story arcs",
            "active": True,
        },
        SpecialistType.BUILDING_SCIENCE: {
            "name": "Building Science Agent (HERS/Ulrich Energy)",
            "model": "llama-70b",
            "description": "RESNET/IECC/ASHRAE, duct leakage, ACH50, compliance",
            "active": True,
        },
        SpecialistType.MEDIA: {
            "name": "Media Agent",
            "model": "qwen2.5-7b",
            "description": "Content tagging, metadata, organization, 224TB library",
            "active": True,
        },
        SpecialistType.INFRASTRUCTURE: {
            "name": "Infrastructure Agent",
            "model": "qwen2.5-7b",
            "description": "Self-monitoring, health checks, optimization, self-healing",
            "active": True,
        },
    }


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        service="cognitive",
        node=settings.node.name.value,
        uptime_seconds=time.time() - app.state.start_time,
    )


# =============================================================================
# Cognitive State
# =============================================================================


@app.get("/v1/cognitive/state")
async def get_state() -> CognitiveState:
    """Get the current cognitive state (CST)."""
    return _state


@app.put("/v1/cognitive/focus")
async def set_focus(focus: str) -> dict:
    """Set the current attention focus."""
    _state.attention_focus = focus
    logger.info(f"Attention focus set: {focus}")
    return {"status": "focused", "focus": focus}


# =============================================================================
# Specialist Management
# =============================================================================


@app.get("/v1/cognitive/specialists")
async def list_specialists() -> dict:
    """List all registered specialist modules."""
    return {
        "specialists": {
            k.value: v for k, v in _specialists.items()
        },
        "active_specialist": _state.active_specialist.value if _state.active_specialist else None,
    }


# =============================================================================
# Attention Mechanism (Bidding)
# =============================================================================


@app.post("/v1/cognitive/bid")
async def submit_bid(bid: BidRequest) -> dict:
    """A specialist submits a bid for attention in the workspace.

    The workspace collects bids and selects the most relevant specialist
    to handle the current context. Winners broadcast their output to all
    other specialists.
    """
    if bid.specialist not in _specialists:
        raise HTTPException(status_code=404, detail=f"Specialist {bid.specialist} not registered")

    logger.info(
        f"Bid received from {bid.specialist.value}",
        extra={"relevance": bid.relevance_score, "action": bid.proposed_action},
    )

    # Simple winner-takes-all for now
    # TODO: Implement coalition formation and weighted bidding
    if _state.active_specialist is None or bid.relevance_score > 0.8:
        _state.active_specialist = bid.specialist
        _state.cycle_count += 1

        return {
            "status": "won",
            "specialist": bid.specialist.value,
            "cycle": _state.cycle_count,
        }

    return {
        "status": "outbid",
        "current_winner": _state.active_specialist.value,
    }


# =============================================================================
# Global Broadcast
# =============================================================================


@app.post("/v1/cognitive/broadcast")
async def broadcast(msg: BroadcastMessage) -> dict:
    """Broadcast a message from the winning specialist to all others.

    This is the core GWT mechanism — when a specialist wins attention,
    its output becomes available to all other specialists.
    """
    _state.recent_broadcasts.append(msg)
    # Keep only last 50 broadcasts
    if len(_state.recent_broadcasts) > 50:
        _state.recent_broadcasts = _state.recent_broadcasts[-50:]

    logger.info(
        f"Broadcast from {msg.source_specialist.value}",
        extra={"content_length": len(msg.content)},
    )

    return {
        "status": "broadcast",
        "source": msg.source_specialist.value,
        "listeners": len(_specialists) - 1,
    }


@app.get("/v1/cognitive/broadcasts")
async def get_broadcasts(limit: int = 10) -> list[BroadcastMessage]:
    """Get recent broadcasts from the workspace."""
    return _state.recent_broadcasts[-limit:]


# =============================================================================
# Cognitive Cycle (the main loop)
# =============================================================================


@app.post("/v1/cognitive/cycle")
async def run_cycle(input_text: str) -> dict:
    """Run a single cognitive cycle.

    1. Present input to all specialists
    2. Collect relevance bids
    3. Select winning coalition
    4. Execute winning specialist's proposed action
    5. Broadcast results to all specialists
    6. Update CST
    """
    _state.cycle_count += 1
    _state.attention_focus = input_text

    # TODO: Implement full cognitive cycle
    # For now, return a structured placeholder
    return {
        "cycle": _state.cycle_count,
        "input": input_text,
        "focus": _state.attention_focus,
        "active_specialist": _state.active_specialist.value if _state.active_specialist else None,
        "status": "cycle_complete",
    }
