---
name: alpha
description: "Example skill that delegates to a real agent and a missing one."
argument-hint: "[target]"
user-invocable: true
allowed-tools: Read, Glob, Agent
model: sonnet
---
# Alpha

Hand the review to `subagent_type: reviewer` and then to `subagent_type: ghost`.

Next: `/beta` then `/nope`.
