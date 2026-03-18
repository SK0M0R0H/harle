---
title: "Tools Allowlist"
tags: [policy, tools, security, permissions]
context: global
priority: P0
last_updated: 2026-02-17
---

# Tools Allowlist

Defines which external tools and integrations each agent role is permitted to use.

## Researcher Agent

- **Dataset search**: always allowed
- **Web search**: allowed for work and personal contexts
- **File write**: requires approval (writes to knowledge/ or logs/)

## Secretary Agent

- **Dataset search**: always allowed
- **Trello integration**: allowed for work context only
- **File write**: allowed for logs/ without approval; requires approval for other directories

## All Agents

- **Dataset read**: always allowed for files matching the active context scope
- **External API calls**: require explicit user approval on first use per session
- **File deletion**: never allowed without explicit approval
