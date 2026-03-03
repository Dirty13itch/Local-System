# Agent Development Rules

## Framework
- Use `create_agent` from `langchain.agents` (LangGraph 1.0+)
- Do NOT use deprecated `create_react_agent` from `langgraph.prebuilt`
- Use LangChain middleware for escalation: `before_model`, `after_model`, `wrap_tool_call`

## Agent Server
- FastAPI + LangGraph + LiteLLM on FOUNDRY:9000
- OpenAI-compatible API with streaming (`astream_events()`)
- Per-agent system prompts, tool definitions, and escalation thresholds

## Model Routing
- All agents call LiteLLM, never vLLM/SGLang directly
- Use model aliases: `reasoning`, `fast`, `embedding`, `coding`
- Temperature per agent: most use default, Knowledge/Coding use 0.3

## Context Injection
- 1 embedding call + parallel Qdrant queries per request (~30-50ms)
- Per-agent collection config (which Qdrant collections to search)
- Redis goals injected from GWT workspace

## NSFW
- Allowed. No filtering, no moralizing.
- Qwen3 think blocks: strip `<think>...</think>` tags from responses before display

## Task Engine
- Redis 8 queue with built-in JSON/Search modules
- 5-second poll interval, max 2 concurrent tasks
- Step logging for every task action
- Delegation tools for inter-agent routing

## Letta Integration
- Letta v0.16 container on port 8283
- Each agent has a corresponding Letta agent for self-editing memory
- Core memory always in-context, archival memory searchable
- No direct LangGraph↔Letta integration — bridge via REST API
