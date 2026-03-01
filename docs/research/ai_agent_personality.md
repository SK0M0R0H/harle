---
title: "AI Agent Personality — Making Harle Feel More Human in Chat"
tags: [research, personality, ai-agent, chat, character, conversational-ai, harle]
context: global
last_updated: 2026-03-02
summary: "Research on how to give Harle more personality in chat so it feels more human or like a consistent game/movie character; techniques, pitfalls, and application to the vault and prompts."
---

# AI Agent Personality — Making Harle Feel More Human in Chat

> **Goal:** Make Harle feel more like a human (or like a consistent game/movie character) in chat communications, without sacrificing reliability or task completion.

This document summarises research on **personality design for conversational AI agents**, with a focus on techniques that apply to Harle: system prompts in the vault, consistency across turns, and optional capture of user communication preferences. It draws on recent academic work, industry practices (e.g. character prompts, NPC dialogue), and Harle’s existing architecture.

---

## 1. Why AI Agents Often Feel Flat

### 1.1 The consistency crisis

LLM-based agents frequently suffer from **persona drift**: contradicting earlier statements, dropping role-appropriate behaviour, or shifting tone mid-conversation. For example, an agent can start helpful and then become generic, or mix formal and casual register without reason. Users notice when “the character” breaks.

Reported issues in the literature and in product feedback include:

- **Emotional flatness** — Little variation in tone; responses feel templated.
- **Generic responses** — Same safe, neutral phrasing regardless of intended persona.
- **Context amnesia** — Forgetting earlier in-conversation context or stated preferences.
- **Personality drift** — Gradual loss of defined traits over long or multi-turn chats.

Harle’s current agent prompts (e.g. `prompts/researcher.md`, `prompts/secretary.md`) define **role and behaviour** (what to do, constraints, output format) but say little about **voice, tone, or character**. That keeps behaviour predictable and professional but can make Harle feel like “a generic assistant” rather than “Harle” as a distinct entity.

### 1.2 Relevance to Harle

- **Multi-role design:** Secretary, Researcher, Specialist can each have a distinct “flavour” while still feeling like one coherent assistant (Harle) when the user talks to “Harle” in the CLI.
- **Vault-driven prompts:** Personality can be encoded in the same place as today’s prompts — Markdown in the dataset — so users can tune it without code changes.
- **Capture module:** The vault capture / onboarding design already envisages asking about **communication preferences** (e.g. “Do you prefer formal or casual tone from me?”). That can feed into a shared “Harle personality” layer (see [vault_capture_module.md](../trd/architecture/vault_capture_module.md)).

---

## 2. Techniques for Personality and Consistency

### 2.1 Character bible in the system prompt

The foundation used in high-quality NPCs and character-based chatbots is a **character bible** in the system prompt: not just “you are a secretary” but a compact description of:

- **Identity** — Who Harle is (e.g. “Harle is the user’s personal assistant; one coherent presence behind the Secretary, Researcher, and Specialist roles”).
- **Traits** — A small set of stable traits (e.g. competent, concise, warm but not overfamiliar, proactive about clarifying).
- **Speech and tone** — Preferred register (formal/casual), sentence length, use of bullets vs prose, when to be brief vs when to elaborate.
- **Boundaries** — What Harle does not do (e.g. never pretend to have feelings it doesn’t have; never switch to a different “character” mid-reply).

This can live in a **shared** prompt fragment (e.g. a “Harle identity” section) that is always included before role-specific prompts, so all agents feel like the same “person” with different expertise.

### 2.2 Few-shot behavioural examples

**Few-shot examples** in the prompt teach specific phrasing and reactions. For example:

- How to open a reply when the user is vague (“I have a few questions before I start…”).
- How to acknowledge uncertainty (“I’m not sure yet — let me check…”).
- How to keep a consistent sign-off or transition style.

Current orchestrator docs already mention that prompt files can contain “Example interactions”; adding 2–3 short examples per role that match the desired tone will reinforce personality more than abstract instructions alone.

### 2.3 Explicit consistency rules

To reduce drift, the prompt can state **consistency rules** explicitly:

- “Stay in character: you are Harle. Do not say ‘As an AI…’ or break the fourth wall unless the user explicitly asks about your nature.”
- “If you have already stated a preference or fact in this conversation, do not contradict it later.”
- “Match the formality level the user uses unless they ask otherwise.”

Research (e.g. reinforcement learning with consistency metrics) shows that **prompt-to-line** (alignment with initial persona), **line-to-line** (no contradictions), and **Q&A consistency** (stable beliefs over time) significantly reduce perceived inconsistency when enforced or encouraged in the prompt.

### 2.4 Dynamic persona refinement (advanced)

Academic work (e.g. DPRF — Dynamic Persona Refinement Framework) iteratively compares agent outputs to a target persona and refines the persona description to close gaps. For Harle, a lighter-weight version could be:

- **Logging** — Store samples of “good” vs “off-brand” replies (e.g. from user feedback or manual tagging).
- **Prompt iteration** — Periodically tighten the character bible and few-shot examples based on what actually produced the desired tone.

This is optional and can come later; the biggest gain is usually from a clear character bible + few-shot examples first.

### 2.5 Warmth and writing style

Industry practice (e.g. Anthropic’s public discussion of assistant design) emphasises **deliberate character choices**: e.g. thoughtfulness, balance, principle. For Harle:

- **Warmth** — Polite, occasionally light humour or empathy where appropriate, without being saccharine or overfamiliar.
- **Clarity** — Prefer short sentences and clear structure; avoid corporate jargon or hedging that makes replies feel generic.
- **Variability** — Slight variation in phrasing and structure so not every reply follows the same template (e.g. not every reply starts with “I’ve…” or “Here are…”).

The vault’s **communication_preferences** (and any future “tone” or “voice” capture) can be summarised into a short paragraph that is injected into the context so Harle adapts to “formal/casual” or “minimal/verbose” per user.

### 2.6 Context-sensitive personality (optional)

Some systems use **context-sensitive personality**: e.g. more formal in work context, slightly warmer in personal. Harle already has `context_scope` (work vs personal); that could be used to select or weight different tone instructions (e.g. “In work context, prefer slightly more formal and concise”) without building a full “flexible personality” system. This can be a later enhancement.

---

## 3. Game and Movie Character Techniques

Techniques from **game NPCs** and **character-driven storytelling** transfer well to a single, coherent assistant persona:

| Technique | Application to Harle |
|-----------|----------------------|
| **Character bible** | One short “Harle identity” block: traits, voice, boundaries. |
| **Speech patterns** | Concrete rules: e.g. “Use contractions in casual mode,” “Prefer active voice,” “Avoid opening with ‘Sure!’ every time.” |
| **Emotional triggers** | Define when to show more empathy (e.g. user expresses stress) or stay neutral (e.g. factual Q&A). |
| **Memory of relationship** | Use conversation history and stored preferences so Harle “remembers” how this user likes to be addressed. |
| **No fourth-wall breaks** | Instruct Harle not to say “As an AI I cannot…” unless the user explicitly asks; instead e.g. “I can’t do that for you, but I can…” |

Important: **character consistency is often more important than response variety**. A single “As an AI…” or a sudden shift to a different “voice” breaks immersion more than a slightly repetitive but consistent style.

---

## 4. Six Pillars (Prompt-Engineering Summary)

A concise checklist for prompt-level personality:

| Pillar | Purpose | For Harle |
|--------|---------|-----------|
| **Zero-shot persona** | Baseline identity and traits | “Harle” identity + 3–5 stable traits in shared prompt. |
| **Few-shot behaviour** | Concrete phrasing and reactions | 2–3 example turns per role in `prompts/*.md`. |
| **Chain-of-character** | Keep “in character” across reasoning | Short instruction: reason in role, respond as Harle. |
| **Role-based framing** | Secretary vs Researcher vs Specialist | Keep current role definitions; add tone/voice on top. |
| **Meta-persona** | Reusable template across roles | One “Harle persona” block included in every agent context. |
| **Self-consistency** | Avoid contradictions and drift | Explicit rules: don’t contradict earlier statements; match user formality. |

---

## 5. Where This Fits in Harle

### 5.1 Data layer and context assembly

- **P0 content:** Agent prompts in `prompts/` and policies in `policies/` are already loaded first (Context Assembler; see `docs/trd/architecture/orchestrator.md` and `src/harle/context/assembler.py`). A **shared “Harle identity” file** (e.g. `prompts/harle_identity.md` or a dedicated section in a single “base” prompt) can be loaded once and prepended to every role prompt so all agents share the same persona.
- **User preferences:** Any captured “communication style” or “tone” (from the capture module or a simple preferences file) can be stored in the vault and retrieved by the Context Assembler like other P0 or search results, then appended to the system prompt so Harle adapts to “formal/casual” or “brief/detailed” per user.

### 5.2 No code change required for first step

A minimal implementation is **purely in the vault**:

1. Add a short “Harle identity” section (character bible: who Harle is, 3–5 traits, tone guidelines, one or two consistency rules).
2. Add 2–3 few-shot example exchanges to each of `prompts/secretary.md` and `prompts/researcher.md` that match the desired voice.
3. Optionally add a `preferences/communication.md` (or similar) that users or the capture flow can fill with “preferred tone: casual/formal” and “preferred length: brief/detailed,” and ensure the Context Assembler includes it when building the prompt.

Code changes would only be needed if we want to **parse** preferences (e.g. from a structured file or DB) and inject them automatically; until then, a single “communication preferences” note in the vault that gets retrieved by search is enough.

### 5.3 Risks and guardrails

- **Task completion first:** Personality should not override safety, tool allowlists, or approval gates. Keep “Harle identity” and tone as **additions** to existing behaviour and constraints.
- **Clarifier and routing:** The Clarifier and Router can keep their current wording; personality mainly affects the **agent’s final replies**, not the clarification questions themselves (unless we explicitly want those to match Harle’s voice too).
- **Token budget:** A short identity block (+ few-shot examples) has modest token cost; if context is tight, the identity block can be kept to a few hundred tokens and examples to 1–2 per role.

---

## 6. Recommendations

1. **Introduce a shared “Harle identity” block** in the vault (e.g. `prompts/harle_identity.md` or a section in an existing base file) and load it before role-specific prompts so every agent speaks as the same character.
2. **Add few-shot examples** to each role prompt (2–3 example user→Harle turns) that demonstrate the desired tone and phrasing.
3. **Add explicit consistency rules** in the system prompt (e.g. don’t break character, don’t contradict yourself, match user formality when possible).
4. **Use communication_preferences from the capture module** (or a simple preferences note in the vault) so Harle can adapt formality and verbosity to the user; wire that into context assembly when available.
5. **Iterate from logs:** Optionally tag “good” vs “off-brand” replies in run logs and refine the character bible and examples over time (lightweight version of dynamic persona refinement).

---

## 7. References and Further Reading

- **DPRF (Dynamic Persona Refinement):** Iterative refinement of persona profiles to align LLM behaviour with target character (e.g. debates, social media, interviews).
- **PersonaMem-v2 / agentic memory:** Human-readable memories and implicit user personas for personalised, consistent dialogue.
- **Reinforcement learning for consistency:** Multi-turn RL with prompt-to-line, line-to-line, and Q&A consistency metrics (e.g. >55% reduction in persona inconsistency in studied settings).
- **Big Five / PsyPlay-style personality:** Mapping traits (e.g. Big Five) onto role-playing agents for consistent trait expression across turns.
- **Character prompts (Jenova, community):** “Character bible” structure: identity, backstory, motivations, speech patterns, emotional triggers, behavioural constraints.
- **Anthropic persona selection / warmth:** How assistants are shaped by values and tone choices in training and prompting.
- **NPC dialogue (games):** Character consistency over variety; memory and latency as key to believability; local vs cloud trade-offs for control and latency.

---

**Summary:** Making Harle feel more human (or like a consistent character) in chat is largely a **prompt-design and vault-content** task: a shared “Harle identity” block, few-shot examples per role, explicit consistency rules, and optional user communication preferences. Implementation can start in the vault with no code changes; code can later support structured preferences and logging for refinement.
