---
title: "Dummy Module — Usage Skill"
tags: [dummy, tool-skill, testing]
context: global
last_updated: 2026-02-25
summary: "Example skill file shipped with the dummy module for testing the skills system."
---

# Dummy Module Usage

This is a placeholder skill file used to verify that the skills loading
infrastructure works correctly.

When working with dummy items:

1. Use `dummy_read` to fetch an item before modifying it.
2. Use `dummy_create` only when you need a new item — check first.
3. Use `dummy_delete` with caution — deletions cannot be undone.
