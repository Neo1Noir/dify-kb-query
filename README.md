# Dify Knowledge Base Query

[![CI](https://github.com/Neo1Noir/dify-kb-query/actions/workflows/ci.yml/badge.svg)](https://github.com/Neo1Noir/dify-kb-query/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](#requirements)

An Agent Skill for searching Dify knowledge bases and reading source passages. Designed for **Codex, Claude Code, and ChatGPT** surfaces that support uploaded Skills and Python execution.

Ask a question in natural language. The skill discovers datasets under configured tags, applies explicit metadata filters, and returns evidence with document names and IDs. The client uses **only the Python standard library**.

## Why this skill?

- **Live tag discovery:** newly tagged datasets become discoverable; removed tags stop subsequent dataset operations.
- **Explicit scope:** select datasets or deliberately request all datasets under allowed tags. Incomplete discovery never silently becomes a partial inventory.
- **Inspectable evidence:** search, list documents, inspect metadata, and read source segments.
- **Read-only API surface:** no uploads, deletes, metadata writes, or administrative routes.
- **Bounded requests:** limits on pages, response size, results, and text length; redirects and ambient proxies are disabled.
- **Portable packaging:** one standard skill folder, an uploadable ZIP, and installation options without Node.js.

Tag checks are client-side constraints. They do **not** reduce the API key's permissions or replace Dify server authorization.

## Install

### Codex

Ask Codex:

```text
$skill-installer install https://github.com/Neo1Noir/dify-kb-query/tree/main/skills/dify-kb-query
```

Or use the third-party [Skills CLI](https://github.com/vercel-labs/skills), which requires Node.js 22.20+:

```sh
npx skills add Neo1Noir/dify-kb-query --skill dify-kb-query -a codex -g
```

Without Node.js:

```sh
git clone https://github.com/Neo1Noir/dify-kb-query.git
cd dify-kb-query
python scripts/install.py --agent codex
```

The local installer copies the skill to `~/.agents/skills/dify-kb-query`. For a project installation, add `--scope project --project-dir /path/to/project`.

### Claude Code

```sh
npx skills add Neo1Noir/dify-kb-query --skill dify-kb-query -a claude-code -g
```

Without Node.js, clone the repository and run:

```sh
python scripts/install.py --agent claude-code
```

This installs to `~/.claude/skills/dify-kb-query`. Project installations use `.claude/skills`. Invoke `/dify-kb-query`, or ask a relevant knowledge-base question.

The installer refuses to overwrite an existing skill. It does not configure credentials, contact Dify, or install dependencies.

### ChatGPT

1. Download [dify-kb-query.zip](https://github.com/Neo1Noir/dify-kb-query/releases/latest/download/dify-kb-query.zip).
2. On a supported account, open **Plugins → Skills → Create → Upload from your computer** and select the ZIP.
3. Configure the endpoint, tags, and key in the environment where the skill will execute.

Availability and upload permissions depend on the product/workspace. This is a file-based skill, not a connector: uploading it does not grant network access, transfer your laptop's environment variables to a remote runtime, or make an intranet server reachable. Use a runtime with Python, endpoint access, and secure credential provisioning. Never paste keys into chat. See [installation details](docs/installation.md).

## Configure once

Use a **Dify Knowledge API key**, not an app or model-provider key. An administrator configures `scripts/config.json` inside the installed skill. Bundled values are non-working examples:

```json
{
  "api_base_url": "https://your-dify-host.example/v1",
  "required_tags": [
    {"id": "00000000-0000-4000-8000-000000000001", "name": "Engineering"}
  ]
}
```

Alternatively, point `DIFY_KB_CONFIG` at a local JSON file outside the skill. Supply `DIFY_KB_API_KEY` through the agent's process environment or approved secret mechanism. On Windows, `python scripts/setup_key.py` inside the skill offers hidden interactive input and current-user persistence. `--status` reports presence without displaying the value.

The key must permit tag listing and dataset discovery as well as reads. Dify scoped keys may reject workspace-level operations; an administrator must choose the appropriate access. This skill never broadens it automatically. See [Dify key scopes](https://docs.dify.ai/en/api-reference/guides/knowledge-base-api).

## Try it

> Find the upgrade requirements in the Engineering knowledge bases and cite the source documents.
>
> Search Release Notes for Product A version 2.0, then read the supporting passages.
>
> Show which knowledge bases are available under the allowed Sales tag.

Direct CLI usage, from `skills/dify-kb-query`:

```sh
python scripts/kb_query.py --list
python scripts/kb_query.py "upgrade requirements" -d "Release Notes"
python scripts/kb_query.py "upgrade requirements" --tag Engineering --all --filter Version is "2.0"
python scripts/kb_query.py --documents -d "Release Notes" --keyword upgrade
python scripts/kb_query.py --read DOCUMENT_UUID -d "Release Notes" --page 1
python scripts/kb_query.py "upgrade requirements" --all --dry-run
```

`--dry-run` checks local arguments only, not connectivity or membership. Output is JSON; truncated passages are marked. See [the query guide](skills/dify-kb-query/references/query-guide.md).

## Requirements

- Python 3.10+; no third-party Python packages.
- A reachable Dify **Classic Knowledge Base API** exposing tags, discovery, retrieval, metadata, documents, and segments.
- Offline contracts derive from a Dify 1.16.1 integration. New versions and Agent Knowledge Base APIs require verification; universal compatibility is not claimed.
- Installing the skill and successfully querying a target Dify instance are separate checks.

## Repository layout

```text
skills/dify-kb-query/
  SKILL.md                 Agent instructions and trigger description
  agents/openai.yaml       Codex display metadata
  scripts/                 Read-only client, key helper, example configuration
  references/              Query and configuration guidance
  LICENSE.txt              License for standalone distribution
tests/                     Offline client and distribution tests
scripts/                   Local installer and reproducible ZIP builder
docs/                      Installation notes and design references
```

## Development

```sh
python -m unittest discover -s tests -v
python scripts/package_skill.py
```

Tests use mocks and a loopback HTTP server; no Dify key or production data is needed. Packaging creates `dist/dify-kb-query.zip` with one top-level skill folder. Do not contribute keys, private documents, or locally modified configuration.

## Design references

Packaging and onboarding follow the [Agent Skills specification](https://agentskills.io/specification), [Anthropic Skills examples](https://github.com/anthropics/skills), and [OpenAI's skill guide](https://learn.chatgpt.com/docs/build-skills). This community project is not affiliated with Dify, OpenAI, or Anthropic.

## License

[MIT](LICENSE). Copyright (c) 2026 Neo1Noir.
