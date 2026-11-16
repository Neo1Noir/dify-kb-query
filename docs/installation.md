# Installation notes

Human documentation is separate from the self-contained `skills/dify-kb-query` folder, following [Anthropic Skills](https://github.com/anthropics/skills) and the [Agent Skills specification](https://agentskills.io/specification).

| Surface | Install | Execution requirements |
|---|---|---|
| Codex | `$skill-installer`, Skills CLI, or `.agents/skills` | Python and endpoint access |
| Claude Code | Skills CLI or `.claude/skills` | Python, configured key, network permission |
| ChatGPT | Upload the single-skill ZIP where available | Workspace allows Skills; runtime supports Python, secure secrets, and the target network |

Current Codex local locations are `~/.agents/skills` and a repository's `.agents/skills`. Older installations may use `$CODEX_HOME/skills`; the built-in installer manages its supported location. Avoid duplicate installations. [OpenAI guide](https://learn.chatgpt.com/docs/build-skills).

Claude Code uses `~/.claude/skills` for personal skills and `.claude/skills` for project skills. Local and account-synced availability differ. [Claude Code guide](https://code.claude.com/docs/en/skills).

ChatGPT's upload flow is **Plugins → Skills → Create → Upload from your computer**, subject to workspace availability and permissions. A ZIP is not an OAuth integration. [Official Help Center](https://help.openai.com/en/articles/20001066-skills-in-chatgpt).

## Local installer

```sh
python scripts/install.py --agent codex
python scripts/install.py --agent claude-code --scope project --project-dir /path/to/project
python scripts/install.py --skills-dir /custom/skills
```

Choose exactly one of `--agent` or `--skills-dir`. The destination is always named `dify-kb-query`. Existing destinations cause an error without changes.

## Verify

Confirm `SKILL.md` and `scripts/kb_query.py` exist and your agent discovers the skill. Configure endpoint/tags and provide the key securely. A real `--list` request verifies connectivity and discovery permissions. Reload or restart the host only if needed for discovery. Offline tests do not prove live-query success in every host.
