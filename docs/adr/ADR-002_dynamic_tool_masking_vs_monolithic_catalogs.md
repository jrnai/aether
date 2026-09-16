# ADR-002: Dynamic Intent Tool Masking vs. Monolithic Tool Catalogs

## Status
**Accepted** (2026-08)

## Context
Project Aether provides 35+ capabilities across diverse domains: filesystem manipulation, AST symbol tracing, Google Calendar events, IMAP email triage, Markdown note checklists, web browsing, weather forecasting, and SDXL image generation.

If all 35+ tool schemas are injected into every prompt:
1. **Schema Token Overhead**: Tool definitions alone consume 2,500–3,500 prompt tokens per turn, representing over 25% of an 8k/16k context window before conversation history is even included.
2. **Attention Dilution & Hallucinations**: Sub-14B parameter models suffer from severe attention dispersion when presented with massive tool catalogs, leading to false tool invocations (e.g., trying to call a calendar tool when asked to edit a Python file).
3. **Inference Latency**: Increased prompt tokens directly increase time-to-first-token (TTFT).

## Decision
We implemented **Dynamic Intent Domain Masking** ([`src/agent/loop.py`](file:///C:/Users/jrrya/Projects/aether/src/agent/loop.py)):
1. Partition tools into 6 isolated capability domains: `files_and_coding`, `calendar`, `mail`, `notes`, `web`, and `image_generation`.
2. Evaluate user queries with a fast, zero-latency regex keyword classifier (`detect_intent_domains`).
3. Dynamically filter the tool schema presented to the model (`get_active_tools_schema`) to include only the relevant domain tools.
4. If multi-domain tools are invoked during an ongoing multi-step ReAct turn, add the newly invoked domain to `active_domains` so the model can pivot seamlessly between domains.
5. If no specific domain is detected with high confidence, fall back gracefully to the full tool catalog.

## Consequences
### Positive
- **60%–75% Reduction in Schema Tokens**: Reduces prompt tool schema overhead from ~3,200 tokens down to ~800–1,100 tokens per turn.
- **Dramatically Lower Hallucination Rate**: By hiding irrelevant tools (e.g. hiding email and image tools during a code refactoring task), the model cannot hallucinate calls to unrelated tools.
- **Faster TTFT**: Shorter prompt prefill times directly accelerate real-time voice and chat response latency.

### Negative
- A query with ambiguous phrasing (e.g. "look up and tell me what happened") might fail domain classification and require the fallback catalog or multi-step domain expansion.

## Alternatives Considered
- **Embedding-Based Semantic Tool Retrieval**: Using vector embeddings to retrieve top-k tools. Evaluated but rejected for local desktop use because loading an extra embedding model wastes ~1 GB of GPU VRAM that is critical for image generation and the LLM context cache.
- **Monolithic Static Catalog**: Injecting all tools unconditionally. Rejected due to unacceptable token overhead and high error rates on 7B models.
