---
title: "Learning Resources for Harle Architecture"
tags: [research, learning, rag, agents, memory, context-engineering, architecture]
context: global
last_updated: 2026-02-22
summary: "Curated reading list of articles, papers, and tutorials covering topics relevant to Harle's architecture design."
---

# Learning Resources for Harle Architecture

Curated reading list covering the core topics behind Harle's design: personal AI assistants, RAG, hybrid search, agent architectures, memory systems, context engineering, security, and the specific technologies in the stack.

Resources are ordered as a learning path — foundations first, then retrieval, agents, memory, production concerns, and finally implementation-specific guides.

---

## 1. Foundations: LLM Agents

### LLM Powered Autonomous Agents
- **Link:** https://lilianweng.github.io/posts/2023-06-23-agent/
- **About:** Lilian Weng's seminal survey that frames LLM agents as systems with three pillars: planning, memory, and tool use. It covers Chain-of-Thought, Tree of Thoughts, self-reflection, short/long-term memory via vector stores, and API-based tool calling. Essential conceptual foundation before diving into any agent implementation.
- **Estimated reading time:** 30 min

### Building Effective Agents — Anthropic
- **Link:** https://www.anthropic.com/research/building-effective-agents
- **About:** Anthropic's practitioner guide distilled from working with dozens of production teams. Distinguishes workflows (orchestrated LLM calls) from agents (model-driven control flow) and presents five composable patterns: prompt chaining, routing, parallelization, orchestrator-worker, and evaluator-optimizer. Argues strongly for starting simple and avoiding premature framework adoption.
- **Estimated reading time:** 25 min

### AI Agent Planning: ReAct vs Plan-and-Execute for Reliability
- **Link:** https://byaiteam.com/blog/2025/12/09/ai-agent-planning-react-vs-plan-and-execute-for-reliability/
- **About:** Head-to-head comparison of ReAct (interleaved reasoning + action) and Plan-and-Execute (upfront plan, then execute). Covers when each pattern excels, their failure modes, and how to combine them. Directly maps to Harle's multi-step reasoning levels 1-3.
- **Estimated reading time:** 15 min

### ReAct Agent Pattern — Agent Patterns (with Code)
- **Link:** https://www.agentpatterns.tech/en/agent-patterns/react-agent
- **About:** Hands-on walkthrough of the ReAct pattern with production guardrails: hard loop caps, tool call budgets, cost controls, circuit breakers, and explicit stop conditions. Includes real incident data showing unbounded ReAct loops costing $3.60+ per request. Critical reading before implementing Harle's Level 1 reasoning.
- **Estimated reading time:** 20 min

---

## 2. Retrieval-Augmented Generation (RAG)

### The Complete Guide to RAG in 2025
- **Link:** https://ashutosh.dev/the-complete-guide-to-retrieval-augmented-generation-rag-in-2025/
- **About:** End-to-end walkthrough of a RAG pipeline: document loading, chunking, embedding, vector storage, retrieval, reranking, and generation. Covers RAG vs fine-tuning trade-offs and includes implementation examples. Good primer before tackling Harle's search pipeline.
- **Estimated reading time:** 25 min

### Document Chunking for RAG: 9 Strategies Tested (70% Accuracy Boost)
- **Link:** https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide
- **About:** Benchmarks nine chunking strategies — fixed-size, recursive, semantic, token-based, hybrid — with measured accuracy differences. Recommends recursive chunking as the default and semantic chunking only when accuracy justifies cost. Includes optimal parameters (256-512 tokens, 10-20% overlap) and covers emerging techniques like late chunking and contextual retrieval.
- **Estimated reading time:** 20 min

### Hybrid Search in 2025: Combining Semantic + BM25 for Production
- **Link:** https://thread-transfer.com/blog/2025-03-22-hybrid-search-production/
- **About:** Practical guide to combining keyword (BM25) and vector search for 30-40% better retrieval accuracy than either alone. Covers dual indexing, parallel retrieval, Reciprocal Rank Fusion (RRF) with the standard k=60 formula, and cross-encoder reranking. Maps directly to Harle's planned Phase 1-5 hybrid search pipeline.
- **Estimated reading time:** 15 min

### Reciprocal Rank Fusion (RRF) for Hybrid Search
- **Link:** https://apxml.com/courses/advanced-vector-search-llms/chapter-3-hybrid-search-approaches/rrf-fusion-algorithms
- **About:** Deep dive into the RRF algorithm: how `1/(rank + k)` scoring works, why it avoids score normalization issues, and when to prefer it over weighted linear combination. Short, focused read that complements the hybrid search overview above.
- **Estimated reading time:** 10 min

### Query Expansion in the Age of Pre-trained and Large Language Models: A Survey
- **Link:** https://arxiv.org/abs/2509.07794
- **About:** Comprehensive 2025 survey organizing query expansion along four dimensions: injection point, grounding/interaction, learning alignment, and knowledge-graph integration. Covers applications in first-stage retrieval, multi-query fusion, reranking, and RAG. Directly relevant to Harle's query expansion investigation for follow-up questions.
- **Estimated reading time:** 45 min

### Learning When to Retrieve, What to Rewrite, and How to Respond in Conversational QA
- **Link:** https://arxiv.org/abs/2409.15515
- **About:** Introduces SELF-multi-RAG for conversational settings — deciding when retrieval is needed, rewriting conversation history for better passage retrieval, and assessing passage relevance before generation. Showed ~13% improvement in multi-turn QA. Directly addresses Harle's conversation-aware query expansion gap.
- **Estimated reading time:** 30 min

---

## 3. Context Engineering & Token Management

### Context Engineering for AI Agents — Anthropic
- **Link:** https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- **About:** Anthropic's guide on curating the full token state for agents — moving beyond prompt engineering to manage accumulated tool outputs, memory, and retrieved data across long-running sessions. Introduces "context rot" and the four core strategies: write, select, compress, isolate. Foundational for Harle's context assembler design.
- **Estimated reading time:** 20 min

### Context Engineering for Agents — LangChain
- **Link:** https://blog.langchain.com/context-engineering-for-agents/
- **About:** Practical companion to Anthropic's piece, covering context clash, confusion, distraction, and poisoning problems in multi-turn agents. Presents the write/select/compress/isolate framework with implementation-oriented examples. Useful for thinking about Harle's P0-P4 priority tiers in practice.
- **Estimated reading time:** 15 min

### Context Window Budgeting for Multi-Turn Agents
- **Link:** https://gantz.ai/blog/post/context-budgeting/
- **About:** Treats context like a financial budget: fixed costs (system prompts, tool schemas), variable costs (conversation, tool results), and reserved generation headroom. Covers slot-based memory, rolling summarization, importance scoring, and message pruning — all applicable to Harle's token budget (~80% input / ~20% output) design.
- **Estimated reading time:** 15 min

### Context Window Management for LLM Apps — Redis Developer Guide
- **Link:** https://redis.io/en/blog/context-window-management-llm-apps-developer-guide/
- **About:** Developer-oriented guide on practical context management: why bigger windows don't mean better results, the lost-in-the-middle problem, effective context length vs advertised maximum, and cost/latency implications. Includes latency benchmarks (7x increase at 15K words) that inform Harle's token budget decisions.
- **Estimated reading time:** 20 min

### Lost in the Middle: How Language Models Use Long Contexts
- **Link:** https://aclanthology.org/2024.tacl-1.9/
- **About:** The foundational research paper (Liu et al., 2024) demonstrating that LLMs show a U-shaped attention curve — performing best when relevant information is at the beginning or end of input and worst when it's in the middle. Directly informs Harle's planned context position optimization (P0 at start, P3/P4 at end).
- **Estimated reading time:** 35 min

---

## 4. Memory Systems for Agents

### MemGPT: Towards LLMs as Operating Systems
- **Link:** https://arxiv.org/abs/2310.08560
- **About:** Introduces virtual context management for LLMs inspired by OS memory hierarchies. MemGPT (now Letta) manages working memory within the context window and external memory in databases, with self-directed memory operations (read/write/search). Foundational reference for Harle's three-tier memory architecture (working, episodic, semantic).
- **Estimated reading time:** 30 min

### Introduction to Stateful Agents — Letta Docs
- **Link:** https://docs.letta.com/guides/agents/memory
- **About:** Practical documentation on implementing stateful agents with persistent memory: core memory (persona + human blocks editable via tools), archival memory (unlimited searchable storage), and recall memory (conversation history search). Shows concrete patterns for the MemGPT architecture in production code.
- **Estimated reading time:** 15 min

### Rethinking Memory in LLM-based Agents: Representations, Operations, and Emerging Topics
- **Link:** https://arxiv.org/abs/2505.00675
- **About:** 2025 survey categorizing LLM memory into parametric (model weights) and contextual (external) forms, with six core operations: consolidation, updating, indexing, forgetting, retrieval, and condensation. Argues for structured knowledge graphs over unstructured memory for complex reasoning. Relevant to Harle's memory lifecycle design.
- **Estimated reading time:** 40 min

### Long-Term Knowledge Storage and Retrieval: Building Persistent Memory for AI Agents
- **Link:** https://mbrenndoerfer.com/writing/long-term-knowledge-storage-and-retrieval
- **About:** Practical guide on implementing persistent memory beyond simple conversation history. Covers key-value stores, vector databases, and structured retrieval for cross-session knowledge retention. Useful for designing Harle's episodic memory (learned preferences, past decisions in PostgreSQL).
- **Estimated reading time:** 15 min

### ACON: Optimizing Context Compression for Long-horizon LLM Agents
- **Link:** https://arxiv.org/abs/2510.00615
- **About:** Presents a framework for compressing both environment observations and interaction histories in long-running agents. Achieves 26-54% memory reduction while preserving task performance through compression guideline optimization. Relevant to Harle's planned conversation summarization and memory lifecycle management.
- **Estimated reading time:** 30 min

---

## 5. Hallucination & Safety

### Agent History Hallucination (already in Harle docs)
- **Link:** Internal — `docs/research/agent_history_hallucination.md`
- **About:** Harle's own research survey on context-induced hallucination in long-running agents. Covers attention dilution, lost-in-the-middle effect, hallucination snowball, and mitigation strategies. Re-read periodically as implementation progresses.
- **Estimated reading time:** 20 min

### Defeating Prompt Injections by Design (CaMeL)
- **Link:** https://arxiv.org/abs/2503.18813
- **About:** Introduces CaMeL, a system that extracts explicit control and data flows from trusted queries and uses capability-based security policies to prevent untrusted data from influencing program flow. Achieves 77% provably secure task completion. Relevant to Harle's planned tool allowlists and approval gates.
- **Estimated reading time:** 35 min

### Design Patterns for Securing LLM Agents against Prompt Injections
- **Link:** https://arxiv.org/abs/2506.08837
- **About:** Proposes principled design patterns for building AI agents with provable resistance to prompt injection. Systematically analyzes security-utility trade-offs with real-world case studies. Applicable to Harle's security architecture: external content wrapping, boundary markers, and homoglyph sanitization.
- **Estimated reading time:** 30 min

---

## 6. Multi-Agent Orchestration

### Multi-Agent Orchestration Patterns — Zylos Research
- **Link:** https://zylos.ai/research/2026-01-06-multi-agent-orchestration-patterns
- **About:** Surveys five production orchestration patterns (hierarchical, sequential, parallel, event-driven, peer-to-peer) with measured success rates. Key finding: orchestrator-to-specialist handoffs succeed 95.2% vs 76.8% for specialist-to-specialist. Covers anti-patterns and monitoring complexity beyond 5 agents. Maps to Harle's Researcher/Secretary/Specialist agent roles.
- **Estimated reading time:** 20 min

### Best Practices for Multi-Agent Orchestration and Reliable Handoffs
- **Link:** https://skywork.ai/blog/ai-agent-orchestration-best-practices-handoffs/
- **About:** Focuses specifically on handoff reliability — the primary failure point in multi-agent systems. Covers explicit state serialization (94% vs 66% success with implicit context), provenance preservation, and optimal handoff timing. Essential reading before implementing Harle's Level 5 multi-agent handoffs.
- **Estimated reading time:** 15 min

---

## 7. Implementation: OpenAI Agents SDK

### OpenAI Agents SDK — Overview & Quickstart
- **Link:** https://openai.github.io/openai-agents-python/
- **About:** Official documentation hub for the Agents SDK, covering the four core primitives: agents, handoffs, guardrails, and sessions. Includes installation guide, basic examples, and links to all sub-topics. Starting point for understanding Harle's agent framework.
- **Estimated reading time:** 10 min

### OpenAI Agents SDK — Handoffs
- **Link:** https://openai.github.io/openai-agents-python/handoffs/
- **About:** Detailed guide on agent-to-agent delegation: dynamic enable/disable, input filtering, callbacks, and typed handoff data via Pydantic models. Directly applicable to Harle's Researcher→Secretary→Specialist routing.
- **Estimated reading time:** 10 min

### OpenAI Agents SDK — Guardrails
- **Link:** https://openai.github.io/openai-agents-python/guardrails/
- **About:** Covers input and output guardrails with two execution modes: parallel (best latency) and blocking (prevents token waste). Shows how to implement validation agents and tripwire triggers. Relevant to Harle's planned approval gates and security patterns.
- **Estimated reading time:** 10 min

### OpenAI Agents SDK — Examples
- **Link:** https://openai.github.io/openai-agents-python/examples/
- **About:** Collection of working examples covering agent patterns, customer service workflows, financial research, memory implementations, and MCP integration. Useful as reference implementations when building Harle's specific agent use cases.
- **Estimated reading time:** 20 min (browsing)

---

## 8. Implementation: Data Layer & Search

### pgvector: Vector Search in Postgres — Crash Course
- **Link:** https://www.sachith.co.uk/pgvector-vector-search-in-postgres-crash-course-practical-guide-oct-9-2025/
- **About:** Hands-on guide to pgvector: installation, creating vector columns, distance metrics (L2, cosine, inner product), IVFFlat indexing, and query patterns. Practical companion to Harle's planned embeddings table and semantic search integration.
- **Estimated reading time:** 20 min

### PostgreSQL as Vector Database: Complete pgvector Guide
- **Link:** https://dbadataverse.com/tech/postgresql/2025/12/pgvector-postgresql-vector-database-guide
- **About:** Production-focused pgvector guide covering installation, configuration, index tuning, and performance optimization for 1-50M vectors. Explains why pgvector avoids the need for a separate vector database — directly validating Harle's architecture choice.
- **Estimated reading time:** 25 min

### Top Embedding Models 2026: Complete Guide
- **Link:** https://artsmart.ai/blog/top-embedding-models-in-2025
- **About:** Comparison of embedding models including OpenAI text-embedding-3, Voyage-3-large, Cohere embed-v4, and open-source options like Qwen3-Embedding. Covers MTEB benchmarks, dimensionality trade-offs, multilingual support, and domain specialization. Useful when choosing an embedding model for Harle's semantic search.
- **Estimated reading time:** 15 min

### Async SQLAlchemy 2.0 with FastAPI & Pydantic V2
- **Link:** https://medium.com/@tclaitken/setting-up-a-fastapi-app-with-async-sqlalchemy-2-0-pydantic-v2-e6c540be4308
- **About:** Step-by-step setup of async SQLAlchemy 2.0 with FastAPI: AsyncEngine, AsyncSession, dependency injection, and Pydantic V2 schema integration. Matches Harle's exact tech stack (FastAPI + SQLAlchemy async + asyncpg + Pydantic).
- **Estimated reading time:** 15 min

### Asynchronous SQLAlchemy 2: Step-by-Step Guide
- **Link:** https://dev.to/amverum/asynchronous-sqlalchemy-2-a-simple-step-by-step-guide-to-configuration-models-relationships-and-3ob3
- **About:** Covers async SQLAlchemy configuration, model definitions, relationships, and Alembic migrations in detail. Good companion to the article above, with more focus on the ORM patterns and migration workflows Harle will need as the schema evolves.
- **Estimated reading time:** 20 min

---

## 9. Implementation: API & CLI

### FastAPI Best Practices: Production-Ready Patterns for 2025
- **Link:** https://orchestrator.dev/blog/2025-1-30-fastapi-production-patterns/
- **About:** Domain-driven project structure, application factory pattern, lifecycle management, and async architecture for FastAPI in production. Covers health checks, dependency management, and error handling. Applicable to Harle's orchestrator service organization.
- **Estimated reading time:** 20 min

### Scaling FastAPI for AI Applications: Lessons Learned
- **Link:** https://medium.com/@kaushalsinh73/scaling-fastapi-for-ai-applications-lessons-learned-c41a6d0456a4
- **About:** AI-specific considerations for FastAPI: why uvicorn alone isn't sufficient, how inference workloads differ from typical web traffic, and strategies for throughput vs latency optimization. Relevant as Harle grows beyond single-user local deployment.
- **Estimated reading time:** 15 min

### How to Build Command Line Tools with Bubbletea in Go
- **Link:** https://oneuptime.com/blog/post/2026-01-30-how-to-build-command-line-tools-with-bubbletea-in-go/view
- **About:** Tutorial on building interactive terminal UIs with Bubbletea's Elm Architecture (Model → Update → View). Covers keyboard handling, Bubbles components, and Lip Gloss styling. Matches Harle CLI's exact framework stack.
- **Estimated reading time:** 20 min

### Bubbletea — GitHub Repository & Tutorials
- **Link:** https://github.com/charmbracelet/bubbletea
- **About:** Official Bubbletea repo with built-in tutorials, a command tutorial covering I/O patterns, and links to the Bubbles component library and Lip Gloss styling framework. Primary reference for Harle CLI development.
- **Estimated reading time:** 15 min (tutorials)

---

## 10. Implementation: Integrations & Protocols

### Model Context Protocol (MCP) — Official Documentation
- **Link:** https://modelcontextprotocol.io/
- **About:** Official MCP documentation covering the protocol's core concepts: resources, prompts, tools, transport mechanisms, and sampling. MCP is Harle's planned protocol for external integrations (Trello, web search, GitHub). Start here for protocol fundamentals.
- **Estimated reading time:** 15 min

### MCP Tutorials: From Concept to Production
- **Link:** https://modelcontextprotocol.info/docs/tutorials/
- **About:** Tiered learning path for MCP: Level 1 (AI-assisted development, 2-3h), Level 2 (Python client mastery, 3-4h), Level 3 (TypeScript, 4-5h). The Python client tutorial is most relevant to Harle's integration layer.
- **Estimated reading time:** 20 min (overview); 3-4h (Python tutorial)

### Building MCP with LLMs
- **Link:** https://modelcontextprotocol.io/tutorials/building-mcp-with-llms
- **About:** Guide on leveraging LLMs themselves to accelerate MCP server and client development. Covers using Claude for code generation, architectural guidance, and debugging MCP implementations. Practical shortcut for building Harle's Trello/GitHub integrations.
- **Estimated reading time:** 15 min

---

## 11. System Design: Personal AI Assistants

### Building a Personal Knowledge Assistant: A Local RAG Pipeline
- **Link:** https://www.zinkohlaing.com/building-a-personal-knowledge-assistant-a-local-rag-pipeline/
- **About:** End-to-end tutorial building a privacy-first personal knowledge assistant with local embeddings, Chroma vector store, and conversational retrieval. Similar goals to Harle but uses a simpler stack — useful for validating architectural decisions and spotting alternative approaches.
- **Estimated reading time:** 20 min

### Building Memno: A Technical Deep Dive into Personal AI Infrastructure
- **Link:** https://www.memno.ai/blog/building-memno-a-technical-deep-dive-into-personal-ai-infrastructure
- **About:** Architecture deep-dive of Memno, a personal AI platform with isolation-first design: dedicated storage per user, personal vector indexes, edge computing for sub-50ms latency. Offers a production-oriented perspective on the same problem space Harle targets.
- **Estimated reading time:** 20 min

### PersonalAI: Knowledge Graph Storage and Retrieval for Personalized LLM Agents
- **Link:** https://arxiv.org/abs/2506.17001
- **About:** Research comparing knowledge graph approaches for personal AI agents. Evaluates structured memory representations with multiple retrieval mechanisms (A*, beam search, hybrid). Relevant to Harle's long-term evolution toward a "Cognitive Digital Twin" (Horizon 3).
- **Estimated reading time:** 35 min

---

## Suggested Reading Order

For the most efficient learning path through this material:

1. **Start with foundations:** Lilian Weng's agent post → Anthropic's building agents guide
2. **Understand retrieval:** RAG complete guide → Chunking strategies → Hybrid search
3. **Learn context management:** Anthropic context engineering → Context budgeting → Lost-in-the-middle
4. **Study memory:** MemGPT paper → Letta docs → Memory survey
5. **Tackle agents in practice:** ReAct pattern → Plan-and-Execute → Multi-agent orchestration
6. **Address safety:** Harle's hallucination doc → CaMeL → Prompt injection design patterns
7. **Implement with the stack:** OpenAI Agents SDK docs → pgvector guide → FastAPI patterns → Bubbletea tutorial
8. **Integrate externally:** MCP documentation → MCP tutorials
9. **See the big picture:** Personal AI assistant architectures → PersonalAI knowledge graph research
