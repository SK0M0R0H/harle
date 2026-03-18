---
title: "Privacy Policy"
tags: [policy, privacy, security, data-protection]
context: global
priority: P0
last_updated: 2026-02-17
---

# Privacy Policy

Core privacy rules that all agents must follow during every operation.

## General Rules

- Never share personal data with external services unless explicitly approved
- Work context data must not appear in personal context responses
- Personal context data must not appear in work context responses
- Do not include real names in any content shared externally

## Data Classification

- **Private**: Health notes, financial data, personal credentials — never include in any agent output
- **Internal**: Work project details, internal decisions — share only within the matching context scope
- **Open**: General knowledge, public information — can be referenced freely

## Agent Behaviour

- When uncertain about data sensitivity, ask the user before including it
- Log which files were accessed in each run for auditability
- Do not cache or store conversation content beyond the current session unless explicitly saving to the dataset
