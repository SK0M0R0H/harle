---
title: "Vault UX — Onboarding, Data Migration, and Personal Knowledge Capture"
tags: [research, ux, vault, onboarding, data-migration, knowledge-capture, cold-start]
context: global
last_updated: 2026-02-27
summary: "Researches UX patterns for vault creation, data migration from existing systems, and capturing personal knowledge from the user's head; proposes concrete options for Harle."
---

# Vault UX — Onboarding, Data Migration, and Personal Knowledge Capture

> The hardest moment in any personal knowledge system is the first hour. The vault is empty, the user has hundreds of notes scattered across Notion, Trello, email, and their own head — and Harle cannot help until data exists. This document researches how to close that gap.

**Context:** Harle's vault (`~/harle-vault/`) is a Markdown-based personal knowledge base that the system reads to personalize every response. Today, `harle init` creates the directory structure and seeds a few starter files, but there is no guided path for populating the vault with the user's actual data. Two specific problems are addressed:

1. **Data migration** — transferring existing knowledge from Notion, Trello, email, bookmarks, and other systems into the vault's Markdown format.
2. **Head-to-vault capture** — writing down things that exist only in the user's memory: favorite food, personal goals, travel preferences, work conventions, communication style, health notes.

For the vault architecture, see `docs/trd/architecture/data.md`. For the current gap analysis, see `docs/investigations/2026-02-26_not_implemented.md`.

---

## 1. The Cold Start Problem

### Why it matters for Harle

Harle's value is proportional to what it knows. An empty vault produces generic responses — indistinguishable from a vanilla ChatGPT session. The user invested effort to install and configure Harle; if the first interaction feels no different from a generic chatbot, trust erodes immediately.

The cold start is not just a data problem — it is an emotional one. The user sees an empty vault and faces two daunting questions:

- "Where do I even start?"
- "Is this worth the effort?"

Both questions must be answered within the first session.

### Industry context

The 2025–2026 shift in personal knowledge tools is clear: **the AI does the heavy lifting during cold start, while users refine rather than create from scratch.** Tools like ChatDB auto-generate dashboards and descriptions instantly, showing users what is possible through action rather than instruction. Obsidian's Importer plugin reduces Notion migration to a 10-minute process. Mem.ai and Rewind/Limitless capture knowledge passively from conversations and screen activity.

The pattern: **generate first, refine later.** Never present a blank canvas.

---

## 2. Data Migration from Existing Systems

Migration is not only about text: **some information is stored as images** (e.g., diagrams, whiteboards, screenshots) and must be *read* — via vision-capable LLMs or OCR — before it can become usable Markdown in the vault. Section 2.3 below expands on this.

### 2.1 Current state

Harle's `docs/trd/architecture/information_sources.md` documents five approaches for Notion integration, and the `2026-02-26_not_implemented.md` gap analysis lists ingestion pipelines (Trello exports, email summaries, bookmarks) as Priority 4. No migration tooling exists today.

### 2.2 Source systems and their export formats

| Source | Export format | Complexity | Data value |
|---|---|---|---|
| **Notion** | Markdown + CSV (native export) | Medium — needs link cleanup, property conversion | High — often contains structured project notes, wikis |
| **Trello** | JSON (native export) | Low — well-structured, predictable schema | Medium — task data, project context |
| **Miro** | PDF, PNG, or API (JSON) | Medium–High — boards are visual; export yields images or structured objects | High — diagrams, process maps, architecture, brainstorming |
| **Google Keep** | HTML (via Takeout) | Medium — needs HTML→Markdown conversion | Low–Medium — short notes, lists |
| **Apple Notes** | No clean export; iCloud scraping or third-party tools | High — vendor lock-in | Medium — personal notes |
| **Email (Gmail/Outlook)** | MBOX or API | High — noisy, needs filtering and summarization | Variable — depends on usage |
| **Browser bookmarks** | HTML (standard export) | Low — structured, predictable | Low — URLs + titles, limited context |
| **Obsidian** | Already Markdown | Trivial — copy files | High — already in target format |
| **Calendar (Google/Outlook)** | ICS or API | Medium — recurring events, time zones | Medium — schedule context |
| **Telegram saved messages** | JSON (via export) | Medium — mixed media, threaded | Variable |

### 2.3 Image-based content: diagrams and visuals

A significant share of user knowledge lives in **images**, not text. Diagrams (architecture, process flows, org charts), whiteboard snapshots, screenshots, and hand-drawn sketches are common in Notion, Miro, Confluence, email attachments, and slide decks. To migrate this into the vault, the system must **read** the image — via a vision-capable LLM or OCR — and produce text or structured Markdown (e.g., a description, a Mermaid diagram, or bullet-point summary). Without that step, image-heavy exports become opaque assets in the vault (e.g., `diagram.png`) that Harle cannot use for search or context assembly. Any import path that touches Miro, Notion (embedded images/databases with cover images), or “dump of screenshots” should assume an **image-reading pipeline** (vision API or OCR) as part of the conversion flow.

### 2.4 Proposed options

#### Option A: CLI Import Commands (Recommended for V1)

A set of `harle import <source>` CLI commands that convert external data to vault Markdown.

```
harle import notion --zip ~/Downloads/notion-export.zip
harle import trello --board "Work Q1" --token <api-token>
harle import miro --board <board-id> --token <api-token>
harle import bookmarks --file ~/bookmarks.html
harle import obsidian --vault ~/my-obsidian-vault
```

**How it works:**

1. User exports data from the source system (Notion ZIP, Trello JSON, etc.)
2. CLI reads the export, converts to Markdown with proper frontmatter
3. Files are placed in `knowledge/work/` or `knowledge/personal/` based on user choice or heuristics
4. Tags are auto-generated from source metadata (Notion properties, Trello labels, bookmark folders)
5. User reviews generated files and edits as needed

**Advantages:**
- Low complexity — each importer is a standalone converter
- No OAuth flows or API keys for file-based imports
- User controls timing and scope
- Output is plain Markdown — user can verify and edit before committing

**Disadvantages:**
- User must manually export from source systems first
- One-time import — no ongoing sync
- Some source formats lose structure (Notion databases → flat Markdown)

**Implementation priority:** Medium-High. Start with Notion (most common) and Trello (already planned as a tool module), then bookmarks.

#### Option B: API-Based Live Import

Direct API connections to source systems for automated, potentially recurring import.

```
harle connect notion --token <integration-token>
harle connect trello --api-key <key> --token <token>
harle connect google-calendar --oauth
```

**How it works:**

1. User authenticates via API token or OAuth
2. Harle queries the API, selects relevant data based on user configuration
3. Converts to Markdown and writes to vault
4. Optionally re-syncs on a schedule (daily, weekly)

**Advantages:**
- No manual export step — friction is minimal
- Can be scheduled for periodic sync
- Access to richer data (Notion database properties, Trello card comments, calendar recurring events)

**Disadvantages:**
- Requires API tokens or OAuth setup — more complex onboarding
- Each source needs its own connector with authentication handling
- Rate limits and API changes create maintenance burden
- Privacy concerns — user may not want to grant API access

**Implementation priority:** Medium. Best as a V2 enhancement after CLI importers prove the concept.

#### Option C: AI-Assisted Bulk Conversion

A "smart import" that uses an LLM to convert unstructured data into well-organized vault documents.

```
harle import smart --dir ~/Downloads/random-notes/
```

**How it works:**

1. User dumps any collection of files (text, HTML, PDFs, screenshots, diagram images) into a staging directory
2. Harle sends each file to an LLM for classification and conversion; **images (diagrams, screenshots) are read via a vision-capable model** and converted to text or structured Markdown (e.g., Mermaid, bullet summary)
3. LLM generates:
   - Proper vault directory placement (work vs personal, which subdirectory)
   - YAML frontmatter (title, tags, context, summary)
   - Clean Markdown content
   - Suggested merges for related files
4. User reviews a preview and approves/edits before files are committed

**Advantages:**
- Handles messy, unstructured input — the real state of most users' data
- Auto-generates metadata that users would skip manually
- Flexible — works with any file format the LLM can read

**Disadvantages:**
- LLM cost per file (~$0.01–0.05 depending on size and model)
- Risk of hallucination in metadata (wrong tags, incorrect summaries)
- Requires review step — not fully automated
- Slower than deterministic converters

**Implementation priority:** Low-Medium. Compelling as a differentiator but depends on reliable LLM summarization (which is also a dependency for the auto-summary pipeline in `indexing/summarizer.py`).

### 2.5 Recommendation

**Start with Option A (CLI Import Commands) for Notion and Trello.** These cover the two most common source systems based on the existing TRD. Add **Miro** to the import roadmap for users who rely on whiteboards and diagrams; Miro import should include an **image-reading step** (vision API or OCR) so board content becomes searchable Markdown, not just exported PNGs. Add Option C (AI-Assisted Bulk Conversion) once the auto-summary pipeline is working — the same infrastructure handles both, and Option C is the natural path for any source that yields images (diagrams, screenshots). Defer Option B (API-Based Live Import) until user demand justifies the OAuth/connector complexity.

For all options, the critical UX principle is: **never leave the user with an empty vault after import.** Even if only 10 notes transfer cleanly, those 10 notes make Harle immediately useful.

---

## 3. Capturing Personal Knowledge ("Head-to-Vault")

This is the harder problem. Data migration moves bits from one system to another. Head-to-vault capture requires the user to articulate things they have never written down — preferences, goals, habits, opinions, life context. Most people cannot sit down and write a "personal preferences document" from scratch. They need guidance, structure, and momentum.

### 3.1 Why people don't write personal knowledge down

| Barrier | Description |
|---|---|
| **Blank canvas paralysis** | An empty Markdown file with no prompts or structure is intimidating. Users don't know what to include or how to format it. |
| **Effort-value mismatch** | Writing "I prefer window seats on flights" feels trivial — too small to bother documenting, even though it is exactly what Harle needs. |
| **Articulation difficulty** | Preferences are often implicit. Users know they prefer something when they see the wrong thing, but cannot list preferences on demand. |
| **Time commitment anxiety** | Users overestimate how long it takes. They imagine needing to write 50 documents when 5 would suffice for a meaningful start. |
| **Maintenance burden fear** | "If I write this down, will I have to keep updating it?" Perceived ongoing cost deters initial investment. |

### 3.2 Proposed options

#### Option D: Conversational Interview Mode (Recommended)

An interactive chat session where Harle interviews the user and generates vault documents from the conversation.

```
harle setup interview
```

or triggered automatically on first run:

```
> Welcome to Harle. I'd like to learn about you so I can be more helpful.
> Let's start with the basics — this takes about 10 minutes.
>
> What kind of work do you do?
```

**How it works:**

1. Harle runs a structured-but-flexible interview using predefined topic trees
2. Topics are organized in tiers:
   - **Tier 1 (Essential, ~5 min):** Name, work role, primary language, communication style preference
   - **Tier 2 (Useful, ~10 min):** Current projects, tools used daily, reporting preferences, time zone, work hours
   - **Tier 3 (Personal, ~10 min):** Dietary preferences, travel habits, health notes (optional, clearly marked as private)
   - **Tier 4 (Goals, ~10 min):** Short-term goals, long-term aspirations, areas of interest, learning priorities
3. After each topic cluster, Harle generates a draft vault document and shows it to the user
4. User can edit, approve, or skip each generated document
5. Documents are saved to appropriate vault directories with proper frontmatter

**Topic tree examples:**

```
Work Context:
├── Role & team ("What's your job title? What team are you on?")
├── Projects ("What are you working on right now?")
├── Tools ("What tools do you use daily? Trello? Notion? Jira?")
├── Communication ("Do you prefer brief updates or detailed reports?")
├── Decisions ("Are there recurring decisions you make at work?")
└── Pain points ("What wastes your time most at work?")

Personal Context:
├── Preferences ("Do you have dietary restrictions? Favorite cuisine?")
├── Travel ("Do you travel often? Window or aisle? Hotel preferences?")
├── Health ("Any health conditions Harle should know about? This stays private.")
├── Goals ("What are your goals for this year?")
├── Interests ("What topics do you like learning about?")
└── Communication style ("Do you prefer formal or casual tone?")
```

**Interview techniques (research-backed):**

- **GATE (Generative Active Task Elicitation):** Use open-ended questions rather than multiple-choice. "Tell me about your typical workday" surfaces more information than "Do you use Slack? (yes/no)".
- **Progressive depth:** Start broad ("What kind of work do you do?"), then narrow based on responses ("You mentioned product management — do you track tasks in Trello or Jira?").
- **Reflection and confirmation:** After 3–4 questions, summarize what was captured and ask "Did I miss anything?" This catches implicit knowledge the user forgot to mention.
- **Latent preference discovery:** Ask follow-up questions that surface hidden preferences. "You said you prefer bullet points — is that for all documents or just status reports?"

**Advantages:**
- Feels natural — like talking to a new colleague on their first day
- User provides raw information; Harle handles formatting, frontmatter, and file organization
- Can be resumed — user does Tier 1 today, Tier 2 tomorrow
- Generates high-quality vault documents because the LLM has conversational context

**Disadvantages:**
- Requires conversation mode to be working (currently in progress)
- LLM cost per interview (~$0.10–0.30 for a full session)
- Risk of generating boilerplate-heavy documents if not carefully designed
- Some users may find chat-based onboarding tedious

**Implementation priority:** High. This is the single highest-impact UX improvement for cold start.

#### Option E: Template-Based Quick Fill

Pre-generated Markdown templates with fill-in-the-blank sections that users complete in their editor.

**How it works:**

1. `harle init` creates template files in the vault alongside the current seed files:

```markdown
---
title: "About Me — Work Context"
tags: [personal-profile, work]
context: work
last_updated: 2026-02-27
summary: "Work profile and preferences for Harle personalization."
---

# About Me — Work Context

## Role
<!-- Your job title and team. Example: "Product Manager, Platform Team" -->


## Current Projects
<!-- List your active projects, one per line. Example:
- Harle: Personal AI assistant
- Platform migration: Moving from AWS to GCP
-->


## Tools I Use Daily
<!-- Which tools should Harle know about? Example:
- Trello (board: "Work Q1")
- Notion (workspace: "Acme Corp")
- Slack
-->


## Communication Preferences
<!-- How do you prefer to receive information? Examples:
- Bullet points over paragraphs
- Include cost estimates in travel plans
- Keep status updates under 200 words
-->


## Recurring Decisions
<!-- Decisions you make regularly. Example:
- Task prioritization every Monday
- Sprint planning every two weeks
-->

```

2. Similar templates for personal context:

```markdown
---
title: "Personal Preferences"
tags: [personal-profile, preferences]
context: personal
last_updated: 2026-02-27
summary: "Personal preferences and lifestyle information for Harle."
---

# Personal Preferences

## Dietary
<!-- Any dietary preferences or restrictions? Example: "Vegetarian, no shellfish" -->


## Travel
<!-- Travel preferences. Example:
- Window seat
- Direct flights preferred
- Boutique hotels over chains
- Budget: moderate
-->


## Goals This Year
<!-- What are you trying to achieve? Example:
- Learn Rust
- Run a half marathon
- Read 24 books
-->

```

**Advantages:**
- Zero LLM cost — pure file templates
- User works in their familiar editor (VS Code, Cursor, Obsidian)
- Self-paced — no time pressure
- Templates serve as documentation of what Harle can use

**Disadvantages:**
- Blank canvas problem is only partially solved (structure helps, but fill-in-the-blank is still effortful)
- No guidance on what level of detail is useful
- Users tend to skip optional sections ("I'll come back to this later" — they won't)
- No follow-up questions to surface implicit knowledge

**Implementation priority:** Medium. Low effort, decent value. Best as a complement to Option D, not a replacement.

#### Option F: Progressive Capture During Normal Use

Instead of a dedicated onboarding session, Harle learns preferences incrementally from regular interactions.

**How it works:**

1. During normal use, Harle notices when it lacks information:
   ```
   User: "Book me a hotel in Berlin"
   Harle: "I'll search for hotels. Quick question — do you have a preference 
           for hotel type? (e.g., boutique, chain, budget, luxury)"
   User: "Boutique, mid-range budget"
   ```

2. Harle saves the preference as both a memory (database) and a vault document update:
   ```
   → memories table: {category: "preference", content: "Prefers boutique hotels, 
     mid-range budget", context_scope: "personal", confidence: 0.7}
   → Appends to knowledge/personal/preferences/travel.md
   ```

3. Over time, the vault fills organically through actual use.

4. Periodically, Harle offers to consolidate:
   ```
   Harle: "I've learned 12 new preferences this week. Want me to organize 
           them into a clean document?"
   ```

**Advantages:**
- Zero upfront effort — preferences are captured in context, when they are most natural to express
- High accuracy — preferences stated in context are more specific than abstract questionnaire answers
- No dedicated onboarding session required
- Feels natural and non-intrusive

**Disadvantages:**
- Slow — vault fills over weeks/months, not hours
- Does not help with cold start (first session is still generic)
- Requires working memory system (`db/memories.py` is currently a stub)
- Risk of incomplete coverage — preferences only surface when relevant situations arise

**Implementation priority:** Medium. Critical for long-term vault maintenance but does not solve the initial cold start. Best combined with Option D for initial setup.

#### Option G: Structured Questionnaire (Quick Profile)

A focused, timed questionnaire that captures the most impactful preferences in 5 minutes.

**How it works:**

1. On first run, Harle presents a structured form (CLI or web):

```
=== Harle Quick Profile (5 minutes) ===

1. What is your name? _______________
2. What do you do for work? (1-2 sentences) _______________
3. What tools do you use daily? (comma-separated) _______________
4. How do you prefer information delivered?
   [ ] Bullet points  [ ] Paragraphs  [ ] Tables  [ ] Depends on context
5. What are you working on right now? (1-2 projects) _______________
6. Do you have dietary restrictions? (optional) _______________
7. What are your top 3 goals this year? (optional)
   1. _______________
   2. _______________
   3. _______________
```

2. Responses are converted into vault documents with proper frontmatter
3. The entire flow takes under 5 minutes

**Advantages:**
- Fast — 5 minutes to a useful vault
- Predictable — every user answers the same core questions
- Low cognitive load — multiple choice + short answers
- Can be implemented in CLI without conversation mode dependency

**Disadvantages:**
- Less depth than a conversational interview
- Fixed questions cannot adapt to user responses
- Feels like a form, not a conversation — less engaging
- Missing the "follow-up" that surfaces implicit knowledge

**Implementation priority:** Medium-High. Good as a fallback if conversation mode is not ready, or as a "quick start" option alongside the full interview.

#### Option H: Import From Existing AI Conversations

Extract personal information from the user's existing ChatGPT, Claude, or other AI conversation history.

**How it works:**

1. User exports their ChatGPT/Claude conversation history (JSON)
2. Harle analyzes conversations for recurring preferences, decisions, and personal facts
3. Generates vault documents from extracted information
4. User reviews and approves

**Advantages:**
- Users have already told AI assistants about themselves — reuse that investment
- Can extract detailed, contextual preferences (not just "I like Italian food" but "I prefer casual Italian restaurants with outdoor seating in warm weather")
- No new effort required from the user

**Disadvantages:**
- Export availability varies by platform (ChatGPT exports well, Claude does not)
- Conversations are noisy — extracting structured preferences from thousands of messages is unreliable
- Privacy concerns — users may not want to share their full AI history
- High LLM cost for processing large conversation archives

**Implementation priority:** Low. Interesting concept but high complexity and uncertain reliability.

### 3.3 Recommendation

**Primary: Option D (Conversational Interview) + Option E (Templates) + Option G (Quick Profile)**

The recommended approach uses three tiers:

1. **Quick Profile (Option G)** — on `harle init`, a 5-minute structured questionnaire captures the essentials. This is the absolute minimum to make the vault useful. Implemented in CLI, no conversation mode dependency.

2. **Conversational Interview (Option D)** — after initial setup, `harle setup interview` runs a deeper, adaptive conversation that generates 5–15 vault documents across work and personal contexts. This is the core onboarding experience.

3. **Templates (Option E)** — for users who prefer self-paced writing, templates are generated during `harle init` as editable scaffolding. Power users who want to fill their vault manually have a clear structure to follow.

**Long-term: Option F (Progressive Capture)** runs continuously after onboarding, keeping the vault fresh as preferences evolve.

---

## 4. Vault Maintenance UX

Onboarding fills the vault initially. Maintenance keeps it useful over time. The research identifies four maintenance challenges.

### 4.1 Staleness detection

**Problem:** Vault documents become outdated. A file titled "Current Projects" from 6 months ago lists projects that no longer exist.

**Proposed solution: Periodic vault health check**

```
harle vault check
```

Output:
```
Vault Health Report
──────────────────
✓ 47 files indexed, 0 errors
⚠ 3 files not updated in 90+ days:
  - knowledge/work/projects/platform-migration.md (142 days)
  - knowledge/personal/goals/2025-goals.md (95 days)
  - workflows/quarterly-review.md (201 days)
⚠ 5 files missing frontmatter (title, tags, or context)
⚠ 2 files exceed recommended length (3000+ tokens)
✓ All files pass format validation
```

**Extension:** Harle can proactively ask about stale documents during normal conversation:

```
Harle: "I noticed your 'Current Projects' file hasn't been updated in 4 months.
        Want me to ask you a few questions and refresh it?"
```

### 4.2 Auto-generated metadata

**Problem:** Writing frontmatter (title, tags, summary) is tedious. Most users skip it, degrading search quality.

**Proposed solution:** The planned auto-summary pipeline (`indexing/summarizer.py`) should also generate:
- Missing `title` from first heading or content analysis
- Missing `tags` from content analysis and existing tag vocabulary
- Missing `summary` from content summarization
- Suggested `context` (work/personal) from content and directory location

This runs during indexing, not during user editing — invisible to the user.

### 4.3 Assisted editing

**Problem:** Editing vault documents requires opening a text editor, finding the right file, understanding the Markdown/frontmatter format, and saving. For simple updates ("my favorite restaurant changed"), this is too much friction.

**Proposed solution: Conversational vault updates**

```
User: "Update my travel preferences — I now prefer aisle seats"
Harle: "Updated knowledge/personal/preferences/travel.md:
        Changed 'Window seat' to 'Aisle seat' in the Flight section.
        Want to review the change?"
```

This requires the Vault Tool Module (`tools/vault/module.py`) which is currently missing (Priority 1 in the gap analysis). When implemented, the agent can `read_note`, `update_note`, `create_note`, and `search_notes` directly.

### 4.4 Vault completeness guidance

**Problem:** Users don't know what information would make Harle more useful. They have 10 files but could benefit from 30.

**Proposed solution: Contextual suggestions**

After each interaction, Harle can optionally suggest vault additions:

```
Harle: "I noticed you mentioned you have weekly 1:1s with your manager.
        Adding a note about your meeting cadence would help me prepare
        agendas in the future. Want me to create one?"
```

This uses the progressive capture pattern (Option F) combined with proactive suggestions based on detected knowledge gaps.

---

## 5. Comparison Matrix

| Option | Setup effort | Time to value | Vault quality | Implementation cost | Dependencies |
|---|---|---|---|---|---|
| **A: CLI Import** | Medium (manual export) | Fast (minutes) | Medium (needs cleanup) | Medium | Importers per source |
| **B: API Live Import** | Medium (API tokens) | Fast (minutes) | High (rich data) | High | OAuth, per-source connectors |
| **C: AI Bulk Convert** | Low (dump files) | Medium (review needed) | Medium-High | Medium | LLM summarization |
| **D: Interview** | Low (just talk) | Medium (10–30 min) | High (contextual, deep) | Medium | Conversation mode |
| **E: Templates** | Medium (manual writing) | Slow (user-paced) | Variable (depends on user) | Low | None |
| **F: Progressive** | None (automatic) | Slow (weeks) | High (accurate, in-context) | Medium | Memory system |
| **G: Quick Profile** | Low (5 min form) | Fast (5 min) | Medium (surface-level) | Low | None |
| **H: Chat History Import** | Low (export file) | Medium (review needed) | Variable | High | LLM processing, export format |

---

## 6. Implementation Roadmap

### Phase 1: Immediate (next sprint)

1. **Quick Profile (Option G)** — Add a structured questionnaire to `harle init` that captures 7–10 essential facts and generates 2–3 vault documents. No LLM dependency. Implemented in the Go CLI.

2. **Templates (Option E)** — Add template files to the bootstrap seed (`bootstrap.py`). Templates for work profile, personal preferences, goals. Zero additional code — just new seed files with commented placeholders.

### Phase 2: Near-term (1–2 sprints)

3. **Notion CLI Importer (Option A)** — `harle import notion --zip <path>`. Parse Notion's Markdown+CSV export, convert to vault format with auto-generated frontmatter.

4. **Trello CLI Importer (Option A)** — `harle import trello --board <name>`. Pairs with the planned Trello Tool Module — same API client, different output target.

5. **Vault Health Check** — `harle vault check`. Staleness detection, missing frontmatter, format validation.

### Phase 3: Medium-term (2–4 sprints)

6. **Conversational Interview (Option D)** — Depends on conversation mode and Vault Tool Module. The highest-impact onboarding feature, but has the most dependencies.

7. **Progressive Capture (Option F)** — Depends on the memories system (`db/memories.py`). Runs automatically during normal use.

8. **Auto-Generated Metadata** — Depends on `indexing/summarizer.py`. Fills in missing frontmatter during indexing.

### Phase 4: Long-term

9. **AI Bulk Conversion (Option C)** — For users with messy data. Reuses the summarizer infrastructure.
10. **API Live Import (Option B)** — For power users who want ongoing sync from Notion, Calendar, etc.
11. **Chat History Import (Option H)** — Experimental. Extract preferences from existing AI conversations.

---

## 7. UX Principles for Vault Onboarding

These principles should guide implementation of all options above.

### 7.1 Never present a blank canvas

Every vault file generated during onboarding should have meaningful content — even if it is just the user's name and role. The difference between "0 files" and "3 files with basic information" is the difference between "this tool doesn't know me" and "this tool is starting to learn."

### 7.2 Generate first, refine later

The AI writes the first draft. The user edits, approves, or discards. This inverts the traditional "user writes, AI reads" model and is the key insight from modern onboarding research (LukeW's "Let the AI do the Onboarding" principle).

### 7.3 Show immediate value

Within 5 minutes of completing onboarding, the user should be able to ask Harle a question and get a response that demonstrates personalization. Example: "What should I focus on this week?" should reference the user's stated projects and goals.

### 7.4 Make effort feel proportional

Each question asked during onboarding should visibly improve Harle's responses. If the user tells Harle their Trello board name, the next Trello query should use it without asking. This "immediate payoff" loop maintains motivation.

### 7.5 Respect the "I'll do it later" instinct

Every onboarding step must be skippable. Users who skip should still get a functional (if less personalized) experience. Harle can periodically remind them: "I could be more helpful with your travel planning if you told me your preferences. Want to spend 2 minutes on that?"

### 7.6 Progressive profiling over interrogation

Spreading data collection across touchpoints feels conversational rather than interrogative. Capture 5 facts today, 5 next week, 5 the week after — never 50 at once. Research shows this approach dramatically lowers abandonment rates and produces higher-quality data.

### 7.7 Privacy as a feature, not a warning

When asking for personal information (health, finances, goals), frame privacy controls as empowering, not alarming. "This stays in your vault on your machine — I never send it anywhere" is better than "Warning: this information is sensitive."

---

## 8. Key Research Sources

| Source | Key insight |
|---|---|
| LukeW, "Let the AI do the Onboarding" (2025) | AI should generate initial content that users refine — eliminates the blank canvas barrier |
| GATE — Generative Active Task Elicitation (ICLR 2025) | Open-ended LLM-guided questioning is more effective than traditional elicitation methods |
| RaPSIL — Rapport-Aware Preference Interview (SIGDIAL 2025) | Two-stage process for eliciting sensitive personal information with comfort and accuracy |
| JumpStarter (CHI 2025) | Adaptive context solicitation for personal goal achievement through targeted questions |
| Obsidian Importer Plugin | Notion→Obsidian migration in ~10 minutes; pre-migration cleanup reduces issues by 30% |
| Graphlit Platform | 30+ data connectors for AI context layers; demonstrates the API-based import pattern |
| Typeform, "Progressive Profiling" | Micro-forms collecting 2–3 fields at a time reduce abandonment and improve data quality |
| Limitless/Rewind (2025) | Passive knowledge capture from conversations; privacy-first design with local-only storage |
| Ness Labs, "Self-Discovery Questionnaire" | Template-based personal knowledge capture; 5 minutes per question, first instincts over overthinking |
| Obsidian Gamified PKM Plugin | Game mechanics (points, badges, milestones) increase note-writing consistency and engagement |

---

## 9. Open Questions

1. **Should the interview mode be a special agent role?** A "Setup Agent" with its own prompt in `prompts/setup.md` that is only activated during onboarding — or should the Secretary handle it?

2. **How deep should templates go?** Too many templates overwhelm; too few miss coverage. The proposed set (work profile, personal preferences, goals) covers the basics but may need domain-specific templates (e.g., "Developer Setup" for engineers, "Travel Profile" for frequent travelers).

3. **Should vault documents be auto-updated?** When Harle learns a new preference via progressive capture, should it automatically update the corresponding vault file, or only update the `memories` table and let the user manually sync? Auto-update risks drift; manual sync risks staleness.

4. **What is the minimum viable vault?** How many documents / facts does Harle need before its responses are meaningfully better than generic? This determines how aggressive the onboarding should be.

5. **Gamification — worth the complexity?** Research shows gamification (points, streaks, completeness percentage) increases PKM engagement. A "vault completeness" score (e.g., "Your vault is 40% complete — adding travel preferences would unlock better trip planning") could motivate users but adds UX complexity.
