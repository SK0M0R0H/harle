# Do AI Agents Hallucinate When Their History Grows Large?

## A Research Survey on Context-Induced Hallucination in Long-Running AI Agent Systems

---

## 1. Refined Problem Statement

**Original question:** *With a big dataset and all-time tracked history, could agents become hallucinate similar to how old chats hallucinate in ChatGPT and other similar products?*

**Refined formulation:** *As LLM-based agents accumulate operational history — including conversation logs, tool-use traces, stored memories, and indexed artifacts — does the growing body of context induce hallucination patterns analogous to those observed in extended ChatGPT conversations? If so, what are the mechanistic causes, and what architectural mitigations exist?*

This question decomposes into three sub-questions:

1. **Existence**: Is context-length-induced hallucination a documented phenomenon, and does it transfer from chat-based LLMs to agentic systems with persistent memory?
2. **Mechanism**: What are the root causes — is this purely a context-window limitation, or are there deeper architectural and statistical reasons?
3. **Prevention**: What design patterns, architectures, and operational strategies can mitigate or prevent this degradation?

---

## 2. The Phenomenon: Yes, It Happens — and It's Well-Documented

### 2.1 Evidence from Chat-Based LLMs

The phenomenon is unmistakably real in conversational LLMs. Multiple lines of evidence confirm it:

**User reports at scale.** The OpenAI Developer Community forums contain numerous reports of ChatGPT (GPT-4 and GPT-4o) losing context after approximately 30–50 messages within a single conversation, forgetting earlier instructions, mixing content from unrelated conversations, and generating fabricated information that contradicts earlier established facts [OpenAI Community, 2024–2025].

**Systematic research.** Hua et al. (2023) tested ChatGPT's *situational understanding* — its ability to track and update environment states across dialogue turns — and found that the model "cannot reliably maintain accurate environment states over extended interactions, despite the fundamental simplicity of such tasks" [arXiv:2310.16135]. The model was susceptible to hallucinated state updates that could artificially inflate apparent accuracy.

**Long-term conversation evaluation.** The LoCoMo benchmark (Maharana et al., 2024) evaluated LLMs on very long-term dialogues spanning 300+ turns and 9,000+ tokens. Models "substantially lag behind human performance in understanding lengthy exchanges and comprehending long-range temporal and causal dynamics" [arXiv:2402.17753; ACL 2024].

### 2.2 Evidence from Agent Memory Systems

The problem is not limited to vanilla chat. It extends — and in some ways, *worsens* — in agentic systems with persistent memory:

**HaluMem** (Qian et al., 2025) provides the first operation-level evaluation of hallucinations in agent memory systems. The benchmark evaluates contexts exceeding 1M tokens and reveals that "existing memory systems tend to generate and accumulate hallucinations during the extraction and updating stages, which subsequently propagate errors to the question answering stage" [arXiv:2511.03506]. Critically, hallucinations in the memory layer *propagate downstream* into reasoning and action.

**AgentHallu** (2025) categorizes agent hallucinations into five types — Planning, Retrieval, Reasoning, Human-Interaction, and Tool-Use — and found that tool-use hallucinations are especially challenging to detect, with even top-tier models achieving only 11.6% detection accuracy [arXiv:2601.06818].

**The answer is unambiguous: yes, agents with growing history will hallucinate, and the problem has characteristics that make it potentially *worse* than in simple chat interfaces.**

---

## 3. Root Causes: Why History Size Induces Hallucination

The causes are multifaceted, spanning fundamental architectural limitations, statistical inevitabilities, and emergent error dynamics.

### 3.1 Attention Dilution (The Fundamental Constraint)

The transformer attention mechanism suffers from a mathematically provable degradation as context length grows:

**Softmax rank-collapse.** As sequence length increases, softmax normalization flattens the attention distribution, causing tokens to receive increasingly uniform (and therefore uninformative) attention scores. Research on "critical attention scaling" (Barbero et al., 2025) demonstrates that attention requires scaling by a polylogarithmic factor β_n ∼ log(n) to prevent collapse [OpenReview:7SLtElfqCW]. Without this, attention converges toward uniformity — the model literally "stops paying attention."

**Long context, less focus.** Theoretical analysis in "Long Context, Less Focus" (2025) attributes performance degradation to "an inherent limitation of soft attention in fixed-capacity Transformers" [arXiv:2602.15028]. This is not a bug — it is a fundamental scaling gap.

**Performance degrades even with perfect retrieval.** Du et al. (2025) demonstrated that LLM performance degrades 13.9%–85% as input length increases, *even when the model can perfectly retrieve all relevant information*, *even when irrelevant tokens are replaced with whitespace*, and *even when attention is forced onto only relevant tokens* [arXiv:2510.05381; EMNLP 2025 Findings]. **The mere length of the input is itself a degradation factor**, independent of the quality of retrieval or the relevance of content.

### 3.2 The Lost-in-the-Middle Effect

Liu et al. (2024) demonstrated that LLMs exhibit a U-shaped performance curve over input positions: they attend well to information at the beginning (primacy bias) and end (recency bias) of contexts, but performance drops substantially for information in the middle [arXiv:2307.03172; TACL 2024]. This "lost in the middle" effect means that as an agent's history grows, the oldest context (pushed to the middle by new interactions) becomes progressively less accessible — not because it was deleted, but because the model can no longer effectively attend to it.

A related phenomenon, Posterior Salience Attenuation (PSA), shows that attention salience systematically degrades with distance from the generation point [arXiv:2506.08371].

### 3.3 The Hallucination Snowball Effect

Zhang et al. (2024, ICML) demonstrated that hallucinations *compound*: early errors in autoregressive generation trigger additional errors that the model would not make in isolation [ICML 2024, Proceedings]. Key findings:

- GPT-3.5, GPT-4, and LLaMA2-70B-chat can identify 67%, 87%, and 94% of their own incorrect claims respectively — when presented in isolation.
- Yet these models commit to initial errors over 95% of the time and then generate cascading false explanations.
- The phenomenon persists even with chain-of-thought prompting, beam search, and varied temperature settings.

**For agents, this means**: a single hallucinated memory entry or incorrect tool-use trace in the history can seed a chain of compounding errors as the agent references its own (incorrect) past.

### 3.4 Knowledge Conflicts and Confirmation Bias

When agent history contains contradictory information (e.g., an old fact that was later corrected), LLMs exhibit problematic behaviors:

- **Self-generated bias.** LLMs preferentially trust their own generated text over retrieved external information, even when the generated content is incorrect [arXiv:2401.11911; ACL 2024]. In an agent context, if the model previously wrote a summary containing an error, it will tend to trust that summary over raw data.
- **Confirmation bias.** LLMs favor external information that aligns with their parametric knowledge and resist conflicting evidence [arXiv:2305.13300]. Old memories that were correct at one time but are now outdated may be preferentially retained over newer corrections.
- **Conflict resolution failure.** While LLMs can often detect that a conflict exists, they struggle to identify *which specific segment* is incorrect and to generate appropriately hedged responses [arXiv:2310.00935].

### 3.5 Statistical Inevitability of Hallucination

Kalai and Vempala (2024, STOC) proved a theoretical lower bound: for any calibrated language model, the hallucination rate for "arbitrary" facts (those appearing only rarely in training data) must be at least as large as the fraction of single-occurrence facts — a Good-Turing-type estimate [ACM STOC 2024]. This means that even a perfect model will hallucinate on rare facts proportionally to how rare those facts are.

For an agent with a large, unique operational history (most of which is idiosyncratic and never appeared in pretraining data), this result implies that **hallucination about the agent's own history is statistically expected**. The history is, by construction, composed of facts that the model never saw during training.

### 3.6 RAG Amplification: When Retrieval Makes It Worse

Retrieval-Augmented Generation (RAG) is often proposed as a solution, but large and growing knowledge bases introduce their own failure modes:

- **Retrieval noise.** As the indexed dataset grows, irrelevant documents compete for retrieval slots, introducing noise that can trigger hallucination [arXiv:2310.01558].
- **Cascading multi-hop errors.** In multi-hop reasoning over retrieved data, misuse of irrelevant evidence causes cascading errors [arXiv:2506.00054].
- **Cross-source conflicts.** Multiple retrieval sources with sparse data distribution create information inconsistencies that exacerbate hallucination [arXiv:2508.03553].
- **The WildAGTEval finding.** Agent performance drops 27.3% when irrelevant information complexity increases in tool-calling scenarios [arXiv:2601.00268].

### 3.7 Memory Poisoning (Security Dimension)

Beyond natural degradation, MemoryGraft (2025) demonstrated that "a small set of poisoned records can account for a large fraction of retrieved experiences," causing persistent behavioral drift across agent sessions [arXiv:2512.16962]. This reveals that agent history is not just an accuracy concern — it is an attack surface.

---

## 4. How Agent History Differs from Chat History

While the root causes overlap, agent systems face additional challenges that do not apply to simple chat interfaces:

| Dimension | Chat LLM | Agent with Persistent History |
|---|---|---|
| **Context scope** | Single conversation | Cross-session, multi-modal (text, tool traces, memories, artifacts) |
| **Error propagation** | Errors stay within one session | Errors persist across sessions and compound |
| **Data authority** | User corrects in real-time | Agent may act on stale/incorrect data autonomously |
| **Volume growth** | Bounded by conversation length | Unbounded; grows with every interaction |
| **Conflict frequency** | Rare (one conversation thread) | Common (contradictory data from different sessions/sources) |
| **Autonomy** | User validates each response | Agent may chain multiple actions before human review |
| **Tool-use amplification** | Not applicable | Hallucinated tool calls produce real side effects |

The key insight is that **agent hallucination has real-world consequences** that chat hallucination does not. A hallucinated API call, a fabricated memory entry, or an incorrect summary that gets persisted becomes part of the agent's ground truth for future interactions.

---

## 5. Mitigation Strategies and Design Patterns

### 5.1 Hierarchical Memory Architecture

**Pattern**: Instead of feeding raw, ever-growing history into the context window, organize memory into tiered layers with different granularities and retention policies.

**HEMA** (Ahn, 2025) implements a hippocampus-inspired dual-memory system [arXiv:2504.16754]:
- **Compact Memory**: Continuously updated one-sentence summaries for global coherence, with a "Summary-of-Summaries" mechanism applied every 100 turns to prevent summary drift.
- **Vector Memory**: Episodic store of dialogue chunk embeddings indexed via FAISS, queried by cosine similarity.

Results: Factual recall accuracy increases from 41% to 87%; coherence from 2.7 to 4.3/5.0; dialogues sustained beyond 300 turns while keeping prompts under 3,500 tokens.

**H-MEM** (2025) proposes multi-level memory organization with positional index encoding and index-based routing that enables layer-by-layer retrieval without exhaustive similarity computations [arXiv:2507.22925].

**MemGPT** (Packer et al., 2023) applies operating-system-inspired virtual memory management, using interrupt-driven paging between fast (context window) and slow (vector database) memory tiers [arXiv:2310.08560].

**Design recommendation for Harle**: Implement a three-tier memory architecture:
1. **Working memory** — current session context, aggressively pruned (≤ 3,000 tokens)
2. **Episodic memory** — vector-indexed chunks of past interactions, retrieved on demand
3. **Semantic memory** — consolidated summaries with periodic re-summarization to prevent drift

### 5.2 Context Pruning and Selective Retrieval

**Pattern**: Never feed the full history into context. Retrieve only what is relevant, and validate retrieval quality before injection.

- **Train for irrelevant-context robustness.** Even 1,000 fine-tuning examples mixing relevant and irrelevant contexts can make RAG systems robust to noise [arXiv:2310.01558].
- **Evidence recitation.** Prompt the model to recite retrieved evidence before reasoning, effectively converting a long-context task into a short-context one. This yields up to 4% improvement on RULER benchmarks [arXiv:2510.05381].
- **Ext2Gen framework.** Joint extract-then-generate operations identify query-relevant content while suppressing noise, removing the need for independent compression [arXiv:2503.04789].

**Design recommendation for Harle**: Implement a retrieval pipeline that (a) retrieves candidate chunks, (b) re-ranks by relevance, (c) applies a relevance threshold to filter noise, and (d) injects only filtered chunks into the prompt with clear provenance markers.

### 5.3 Conflict Detection and Resolution

**Pattern**: Detect contradictions in the retrieved context before generation, and handle them explicitly rather than letting the model silently choose.

- **CoCoA** (Confidence- and Context-Aware Adaptive Decoding) uses divergence between parametric and contextual distributions to detect and resolve knowledge conflicts [arXiv:2508.17670].
- **Co-Sight** proposes Conflict-Aware Meta-Verification (CAMV), focusing verification effort only on disagreement hotspots among expert agents [arXiv:2510.21557].

**Design recommendation for Harle**: When retrieved memory chunks contain contradictory information, surface the conflict explicitly (e.g., "I have two conflicting records about X: [A] from session on DATE1 and [B] from session on DATE2") rather than silently choosing one.

### 5.4 Hallucination Detection and Self-Verification

**Pattern**: Verify generated outputs before persisting them to memory or executing tool calls.

- **Lookback Lens** (Chuang et al., 2024) detects contextual hallucinations via attention map analysis, using the ratio of attention weights on context versus generated tokens. Achieved 9.6% hallucination reduction in summarization [arXiv:2407.07071].
- **Self-consistency checking** generates multiple candidate responses and selects the one with highest agreement. Recent work shows this approach is near its performance ceiling for single-model checks, but cross-model verification significantly improves detection [OpenReview:6tlLISSgiu].
- **ORION** integrates retrieval with NLI models to predict factual consistency, achieving F1 of 0.83 in identifying unsupported claims at production scale [arXiv:2504.15771].

**Design recommendation for Harle**: Before persisting any generated content to memory:
1. Run a lightweight consistency check against existing memory
2. For high-stakes actions (tool calls, data modifications), require self-verification or confidence scoring
3. Tag persisted memories with confidence levels and provenance

### 5.5 Semantic Forgetting and Memory Hygiene

**Pattern**: Actively prune, consolidate, and age-out memory to prevent unbounded growth and the accumulation of stale/contradictory entries.

- **Age-weighted pruning** in HEMA reduces retrieval latency by 34% with minimal recall loss [arXiv:2504.16754].
- **Two-level summary hierarchies** prevent cascade errors in conversations exceeding 1,000 turns [arXiv:2504.16754].
- **Continuum Memory Architecture** (2025) incorporates selective retention with temporal chaining and consolidation into higher-order abstractions [arXiv:2601.09913].

**Design recommendation for Harle**: Implement memory lifecycle management:
- **Hot tier** (< 24h): Full detail, no pruning
- **Warm tier** (1–30 days): Summarized, key facts extracted
- **Cold tier** (> 30 days): Heavily consolidated, only high-importance facts retained
- **Periodic reconciliation**: Detect and resolve contradictions between memory tiers

### 5.6 Tool-Use Verification and Recovery

**Pattern**: Validate tool calls before execution and build recovery paths for failures.

- Tool-calling hallucinations manifest as inappropriate tool selection, malformed parameters, incorrect chaining, tool bypass, or semantically incorrect invocations [arXiv:2601.05214].
- **PALADIN** (2025) trains agents on 50,000+ recovery-annotated trajectories, improving recovery rates from 32.76% to 89.68% [arXiv:2509.25238].
- Real-time detection using LLM internal representations achieves up to 86.4% accuracy with minimal computational overhead [arXiv:2601.05214].

**Design recommendation for Harle**: Implement a tool-call validation layer that (a) checks parameter types and ranges before execution, (b) validates the tool selection against the user's stated intent, and (c) provides structured error recovery when calls fail.

### 5.7 Architectural: Prompt Engineering for History-Heavy Contexts

**Pattern**: Structure the prompt to counteract known attention biases.

- Place the most critical instructions and context at the **beginning** and **end** of the prompt (exploiting primacy and recency biases; avoiding the "lost in the middle" zone) [arXiv:2307.03172].
- Use clear section delimiters and explicit role assignments.
- Include a "recitation" step: ask the model to summarize what it knows before answering, converting long-context into short-context [arXiv:2510.05381].
- Keep the total context well below the model's nominal maximum; effective capacity is significantly less than the advertised context window.

---

## 6. Summary of Key Papers

| Paper | Year | Key Contribution |
|---|---|---|
| Liu et al., "Lost in the Middle" | 2024 (TACL) | U-shaped attention curve; middle context is poorly utilized |
| Zhang et al., "Hallucinations Can Snowball" | 2024 (ICML) | Early errors compound; models commit to initial mistakes |
| Du et al., "Context Length Alone Hurts" | 2025 (EMNLP) | Performance degrades 14–85% with length, even with perfect retrieval |
| "Long Context, Less Focus" | 2025 | Theoretical proof of attention dilution in fixed-capacity transformers |
| Barbero et al., "Critical Attention Scaling" | 2025 | Polylogarithmic scaling needed to prevent rank-collapse |
| Kalai & Vempala, "Calibrated LMs Must Hallucinate" | 2024 (STOC) | Statistical lower bound on hallucination rate for rare facts |
| Qian et al., "HaluMem" | 2025 | First benchmark for hallucination in agent memory systems |
| "AgentHallu" | 2025 | Taxonomy of 5 agent hallucination types; tool-use hardest to detect |
| Ahn, "HEMA" | 2025 | Hippocampus-inspired dual memory: 41%→87% factual recall |
| Packer et al., "MemGPT" | 2023 | OS-inspired virtual context management for LLMs |
| "MemoryGraft" | 2025 | Memory poisoning attack on agent experience retrieval |
| "Banishing Hallucinations / Lamini-1" | 2024 | Mixture of Memory Experts; memorization ≠ hallucination tradeoff |
| Maharana et al., "LoCoMo" | 2024 (ACL) | Long-term conversational memory benchmark; LLMs lag behind humans |
| Hua et al., "Can You Follow Me?" | 2023 | ChatGPT fails at situational tracking across extended dialogue |
| "Co-Sight" (CAMV + TRSF) | 2025 | Conflict-aware meta-verification for multi-agent systems |
| "PALADIN" | 2025 | Self-correcting agents for tool-failure recovery |

---

## 7. Conclusions

### The short answer

**Yes, agents with growing operational history will hallucinate** — and the problem is likely *more severe* than in simple chat interfaces because:

1. Errors persist across sessions and compound over time (snowball effect).
2. The attention mechanism has a fundamental, mathematically provable inability to maintain focus over very long contexts (attention dilution / rank-collapse).
3. Even perfect retrieval cannot fully compensate for the length-induced degradation.
4. Agent memory introduces unique failure modes: tool-use hallucination, cross-session conflict, memory poisoning, and autonomous error propagation.
5. The agent's own history is, by construction, unique data that the model never saw during training — making it statistically predisposed to hallucination about its own past (Good-Turing bound).

### The nuanced answer

The severity is **not inevitable** — it depends critically on architectural choices:

- **Naive approach** (dump all history into context): Severe hallucination guaranteed, degradation accelerating with history size.
- **RAG approach** (retrieve relevant chunks): Significantly better, but still vulnerable to retrieval noise, cross-source conflicts, and the inherent length penalty.
- **Hierarchical memory with active management** (summarization, pruning, verification, conflict detection): State-of-the-art approach that can maintain 87%+ factual accuracy beyond 300 turns, but requires careful engineering.

### Recommendation for Harle

Given that Harle is designed as a personal AI assistant with persistent memory and conversation history (see README: "Not yet implemented: [...] memory system, conversation history"), the memory architecture should be designed from the outset with hallucination resistance as a first-class concern. The key principles:

1. **Never feed raw, unbounded history into context.** Use hierarchical memory with tiered summarization.
2. **Retrieve, then verify, then inject.** Every memory retrieval should pass through relevance scoring and conflict detection before entering the prompt.
3. **Treat persisted memories as mutable, versioned data** — not as ground truth. Memories should have timestamps, confidence scores, and provenance chains.
4. **Implement active forgetting.** Old, low-importance memories should be consolidated or pruned, not accumulated indefinitely.
5. **Place critical context at prompt edges.** Exploit primacy/recency bias; avoid the "lost in the middle" zone.
6. **Verify before persisting.** Any model-generated content that will be saved to memory should pass a consistency check first, preventing the snowball effect from propagating across sessions.
7. **Design for conflict surfacing.** When contradictions exist, make them visible rather than silently resolving them.

### Realistic expectations for Harle with best-effort implementation

Given Harle's current architecture (as documented in `docs/trd/`) and assuming the recommendations above are implemented, here is a realistic projection of what to expect in practice.

#### What Harle already gets right (by design)

Harle's existing architecture already contains several decisions that inherently mitigate the worst hallucination risks, even though they were made for other reasons:

1. **Search-then-feed, not dump-everything.** The Orchestrator's Context Assembler uses a priority-based token budget system (P0–P4) that caps input at ~80% of the context window and includes only the top 5–10 relevant pages from the dataset. This is precisely the pattern that avoids the "context length alone hurts" degradation (Du et al., 2025). A dataset of 500+ files is never pushed into context wholesale — the Whoosh-based Search Algorithm reduces it to a focused subset first. This single design choice eliminates the most catastrophic failure mode.

2. **Non-AI search as a first filter.** Whoosh full-text search is deterministic — it either finds a keyword match or it does not. Unlike LLM-based retrieval, it cannot hallucinate results. This provides a grounded, trustworthy first stage before any AI reasoning begins. The architecture document explicitly notes: "There is no 'hallucination' — the search either finds a match or it does not."

3. **The `memories` table has confidence scores and provenance.** The database schema already includes `confidence NUMERIC(3,2)` and `source_run_id` fields on the `memories` table. This is exactly the "mutable, versioned data with provenance" pattern recommended by the research. Low-confidence memories can be treated differently from well-established ones, and any memory can be traced back to the run that created it.

4. **The dataset is human-readable and version-controlled.** Because the vault is plain Markdown in its own Git repository, a human can audit, correct, or revert any agent-written content. If the Specialist agent writes a bad summary or the Secretary stores an incorrect Trello interpretation, `git diff` and `git revert` provide a safety net that most agent memory systems lack. This is a critical difference from opaque vector stores.

5. **Conversation history has a running summary field.** The `conversations` table includes a `summary TEXT` column designed for compressing older messages. This aligns directly with the HEMA Compact Memory approach — continuously updated summaries that preserve global coherence without growing the token count indefinitely.

6. **Write operations require approval for high-risk areas.** Agents cannot modify `prompts/` or `policies/` without explicit user approval, and all work-context writes require confirmation. This prevents the snowball effect from propagating through the most critical data: if an agent hallucinates a "correction" to a policy file, the human gate stops it.

#### What needs to be built (the gap)

Several of the recommended mitigations are not yet present in the architecture:

| Recommendation | Current Status | Required Work |
|---|---|---|
| **Memory lifecycle management** (hot/warm/cold tiers, age-weighted pruning) | Not designed. Memories accumulate indefinitely. | Implement consolidation jobs: summarize old memories, prune low-confidence entries, merge duplicates. |
| **Conflict detection before context injection** | Not designed. The Context Assembler packs results by priority without checking for contradictions. | Add a lightweight conflict-detection step between retrieval and context assembly: compare retrieved chunks pairwise for factual contradictions. |
| **Verification before persisting agent outputs** | Partial. Approval gates exist for high-risk writes, but no automated consistency check. | Add a post-generation check: before saving an artifact or memory, verify key claims against existing memories/dataset (self-consistency or NLI-based). |
| **Prompt-position optimization** | Not explicitly designed. The Context Assembler packs by priority tier but does not consider position within the prompt. | Place P0 (agent prompt, policies) at the start and P3/P4 (memories, conversation history) at the end. Place P1/P2 (search results, external data) in between but anchor the most relevant result at the prompt boundary. |
| **Semantic forgetting** (HEMA-style summary-of-summaries) | The `conversations.summary` field exists but the mechanism to compute and refresh it is not implemented. | Implement a periodic summarization job: every N turns, regenerate the conversation summary. Every M summaries, produce a meta-summary to prevent drift. |
| **Tool-call validation layer** | Not designed. The Tool Manager calls tools without pre-validation of parameters. | Add schema-based parameter validation before every tool call. Log and flag calls where the agent fabricates parameter values not present in the context. |

#### Expected performance envelope

Based on the research and Harle's architecture, here is a realistic performance projection across three scenarios:

**Scenario 1: Short sessions (< 30 turns, single topic)**
- **Expected hallucination risk: Low.** Context stays well within the model's effective attention range. The Search Algorithm provides focused, relevant context. The lost-in-the-middle effect is minimal because the total prompt is short.
- **Comparable to**: Baseline ChatGPT quality on focused tasks. The dataset grounding should make it *better* than vanilla ChatGPT for domain-specific queries because the agent has access to the user's actual data rather than relying on parametric memory.
- **Realistic accuracy**: 90–95% factual accuracy on claims grounded in the dataset; higher for tasks that primarily use tool outputs (e.g., reading Trello cards).

**Scenario 2: Medium sessions (30–100 turns, multi-topic, within a single session)**
- **Expected hallucination risk: Moderate.** This is where the conversation summary mechanism becomes critical. Without it, the oldest turns fall into the "lost in the middle" zone as new turns are appended. With a well-implemented running summary, the effective context stays compact.
- **Key risk**: Cross-topic confusion. If the user switches from discussing Trello tasks to asking about a research report within the same session, earlier topic context may bleed into the new topic — especially if the conversation summary is too broad.
- **Realistic accuracy with mitigations**: 80–90% factual accuracy. The main failure mode is subtle — the agent "remembers" a preference or detail from earlier in the conversation but applies it to the wrong context.

**Scenario 3: Long-term operation (months of accumulated history, thousands of runs, hundreds of memories)**
- **Expected hallucination risk: The core challenge.** This is where the unique risks emerge. The `memories` table may contain entries from months ago that contradict more recent preferences. The `runs` table accumulates thousands of result summaries. The `file_index` may contain stale summaries of files that have since changed. Old artifacts in the `artifacts` table may contain facts that were correct at write time but are no longer accurate.
- **Key risks**:
  - **Memory staleness**: A memory entry saying "User prefers Trello board 'Work Q1'" persists long after the user switched to 'Work Q2'. The agent retrieves the old memory, acts on it, and the user has to correct it — again.
  - **Summary drift**: If conversation summaries are not periodically reconciled, small errors in summarization compound across hundreds of sessions (the snowball effect applied to meta-data).
  - **Retrieval noise growth**: As the dataset and memory tables grow, the ratio of relevant to irrelevant retrievable items decreases. The Search Algorithm returns results that are topically adjacent but factually misleading. The architecture's current `min_score: 0.1` threshold may need to be adaptive.
  - **Cross-session contradiction**: The agent generates a research report on Monday with Conclusion A. On Wednesday, new information leads to Conclusion B. Both the Monday artifact and the Wednesday artifact exist in the system. A future retrieval may surface either, and the model may blend them into an incoherent answer.
- **Realistic accuracy with mitigations**: 70–85% factual accuracy on history-dependent claims (claims that require the agent to correctly recall or synthesize from its own past). Accuracy on grounded claims (directly supported by a retrieved file) remains high (85–90%). Accuracy on fresh external data (web search, Trello reads) is unaffected by history size.

#### The honest bottom line

**Hallucination in Harle will not manifest as "the model goes crazy after 6 months."** The search-first architecture ensures that the model always works from a bounded, relevant context window — it never sees the full history at once. This fundamentally distinguishes Harle from the naive ChatGPT long-conversation pattern where everything is crammed into the context.

**Instead, the realistic failure mode is subtler: slow accuracy erosion on history-dependent reasoning.** Over months, the system accumulates stale memories, contradictory artifacts, and drifting summaries. No single interaction is catastrophically wrong, but the agent gradually becomes less reliable when drawing on its own past — confusing old preferences with current ones, blending conclusions from different sessions, or retrieving a memory that was correct six months ago but is now outdated.

**With the recommended mitigations fully implemented**, Harle can realistically sustain 80–90% accuracy on history-dependent claims across months of operation. Without them — relying only on the current architecture's inherent strengths — expect this to degrade to 65–75% over the same timeframe, concentrated in stale memory retrieval and cross-session contradiction.

**The critical investment is in memory lifecycle management** — not in bigger context windows or better models. The research is clear: context length alone hurts performance; better memory hygiene helps. For Harle, this means the `memories` table, the `conversations.summary` field, and the `artifacts` table each need active maintenance (expiry, consolidation, conflict resolution) — they cannot be treated as append-only logs.

The good news: Harle's architecture is well-positioned for this. The separation of concerns (files as source of truth, database as mirror, search as bridge), the approval gates, the confidence-scored memories, and the Git-backed vault all provide the right foundations. The remaining work is implementation of the lifecycle and verification layers on top of these foundations.

---

## References

- Ahn, K. (2025). HEMA: A Hippocampus-Inspired Extended Memory Architecture for Long-Context AI Conversations. arXiv:2504.16754.
- Barbero, F. et al. (2025). Critical Attention Scaling in Long-Context Transformers. OpenReview:7SLtElfqCW.
- Chuang, Y.-S. et al. (2024). Lookback Lens: Detecting and Mitigating Contextual Hallucinations in Large Language Models Using Only Attention Maps. arXiv:2407.07071.
- Du, Y. et al. (2025). Context Length Alone Hurts LLM Performance Despite Perfect Retrieval. arXiv:2510.05381. EMNLP 2025 Findings.
- Hua, W. et al. (2023). Can You Follow Me? Testing Situational Understanding in ChatGPT. arXiv:2310.16135.
- Kalai, A. T. & Vempala, S. S. (2024). Calibrated Language Models Must Hallucinate. Proceedings of the 56th Annual ACM Symposium on Theory of Computing (STOC 2024).
- Liu, N. F. et al. (2024). Lost in the Middle: How Language Models Use Long Contexts. Transactions of the Association for Computational Linguistics (TACL). arXiv:2307.03172.
- Maharana, A. et al. (2024). Evaluating Very Long-Term Conversational Memory of LLM Agents. ACL 2024. arXiv:2402.17753.
- Packer, C. et al. (2023). MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560.
- Qian, C. et al. (2025). HaluMem: Evaluating Hallucinations in Memory Systems of Agents. arXiv:2511.03506.
- Shafran, E. et al. (2025). Long Context, Less Focus: A Scaling Gap in LLMs Revealed through Privacy and Personalization. arXiv:2602.15028.
- Zhang, M. et al. (2024). How Language Model Hallucinations Can Snowball. Proceedings of the 41st International Conference on Machine Learning (ICML 2024).
- AgentHallu (2025). Benchmarking Automated Hallucination Attribution of LLM-based Agents. arXiv:2601.06818.
- MemoryGraft (2025). Persistent Compromise of LLM Agents via Poisoned Experience Retrieval. arXiv:2512.16962.
- PALADIN (2025). Self-Correcting Language Model Agents to Cure Tool-Failure Cases. arXiv:2509.25238.
- Co-Sight (2025). Trustworthy Reasoning with Structured Facts. arXiv:2510.21557.
- Continuum Memory Architectures (2025). arXiv:2601.09913.
- Rethinking Memory in LLM-based Agents (2025). arXiv:2505.00675.
