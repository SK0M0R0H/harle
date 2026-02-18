---
title: "Harle Project Description"
tags: [project, requirements, overview, roles, functionality]
context: global
last_updated: 2026-02-19
summary: "High-level description of Harle's purpose, requirements, potential actions, required functionality, and agent roles."
---

Harle is a system that feels like a small team of reliable assistants, but with your rules, your
integrations, and a memory you control.
The basic idea is create an AI orchestration which operates other huge personal dataset.
The dataset may contain rules for AI, personal information about the user, project-related information, etc. 

Requirements:
* Prompts and rules live in Markdown, ideally in an Obsidian style vault, so you can edit, version, and
search them.
* Whole dataset is human-friendly to update it (directories, readable files, etc.)
* **Data (user dataset, DB state) lives outside the code repository.** The repo is the application — customizable for different users. Each user points it at their own vault and database via configuration.
* On top of the dataset there's a database which may duplicate some dataset information for better search.
* Integrations with Notion, Trello, GitHub, and room for more later.
* Start on hosted LLMs, for example OpenAI, later switch to open-source models with minimal
refactors.
* Work and personal use cases, treat them as separate contexts with different privacy and risk levels.
* Secure enough by default, but not a compliance project.
* Works smoothly across two computers, meaning shared state and synced prompt files.
* Handles vague goals, by using a clarifier step and by retrieving your prior decisions from your own
database.
* Future friendly, you may add cross-agent communication and payments, including x402.
* Chat mode (like chatgpt)
* **Multi-user customizable.** Different users share the same codebase, with all personalization via external configuration and data.

List of potential actions for Harle:
* Protocol design
* Market Analysis
* Work with Product Hypothesis
* Task manager 
* Source code analysis 
* News preparations
* Analysis of the task manager (stalled tasks, etc.)
* Pre-processing of personal tasks from task manager (e.g., seach for potential flights)
* Informations search
* Travels planning
* Improving the AI agents frameowrk orchestration (e.g., requiresing exrtra personal information from the user)
* Tracking for some events online (e.g. tickets for the concert)
* Health helper
* Preparing twitter publications and blog posts
* Coding
* Help to the user with productivity 
* Finding essential information in the docs

List of poterntial required functionality:
* Chat
* Dataset search, read, write
* Codebase updates 
* Internet search
* Integration with external projects 
* Working 24/7
* Access from the phone and other computers
* Access control by roles in dataset
* Sub-agents creation

Roles examples for agents:
* Developer
* Personal assistant 
* Researcher witha access to corporate information
* Agents orchestrator 
* Agents optimizer 
* Web Searcher 