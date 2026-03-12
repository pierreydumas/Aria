# skill_guide

Self-documentation reader for Aria's skill system.

## Purpose

Lets Aria **read any skill's SKILL.md** before calling its tools.
This enables self-onboarding: when a new skill is added with a SKILL.md,
Aria can read it on demand to understand usage, parameters, and examples.

## Layer

**Layer 2 — Core** (available to all agents)

## Tools

### skill_guide__read

Read a skill's documentation.

| Parameter    | Type   | Required | Description                                |
|-------------|--------|----------|--------------------------------------------|
| `skill_name` | string | yes      | Snake_case directory name (e.g. `sandbox`) |

**When to use:** Before calling tools from an unfamiliar skill, or when
a tool call fails and you need to understand the expected parameters.

### skill_guide__list

List all available skills with their layer, status, and description.
No parameters required.

**When to use:** To discover what capabilities exist, or to find the
right skill name before calling `skill_guide__read`.

## Example Workflow

1. User asks Aria to do something unfamiliar
2. Aria calls `skill_guide__list` to find which skill handles it
3. Aria calls `skill_guide__read(skill_name="the_skill")` to learn usage
4. Aria calls the skill's tools with correct parameters
