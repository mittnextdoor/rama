"""Reasoning agents (docs/83 §4): a model where judgment is needed, deterministic code for everything else.

  config.py      per-agent settings from config/agents.json (model, escalation model, credential name, limits)
  secrets.py     API keys from the environment or the macOS Keychain; never logged, never sent to the browser
  providers.py   the model API (Anthropic Messages, structured output through one forced tool) and a scripted one for tests
  schemas.py     a small JSON Schema validator for the structured outputs
  agents.py      each agent: its context (only the records it needs), its schema, its deterministic checks, what
                 accepting its output does
  runner.py      tasks, gates (enabled, key, data authorization, budget), cache, retries, escalation, the decision log
An agent's output is a proposal or an observation for a person. It never posts, pays, approves or releases."""
