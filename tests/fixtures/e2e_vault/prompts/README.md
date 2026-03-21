# Prompts (E2E)

Role prompt files are **not** stored here. They live in `src/harle/bootstrap_data/agent_prompts/` and are copied into this tree when the E2E session fixture builds a temp vault (`tests/e2e/conftest.py`), matching `/init` and `harle-init` seeding.
