# SPSS InsightGenius — Repos & Distribution Channels

> Last updated: 2026-04-06

## Repositories

| Repo | GitHub | Carpeta local | Stack |
|------|--------|---------------|-------|
| **Backend API** | `quack2025/spss-insightgenius-api` | `C:\Users\jorge\proyectos_python\quantipro-api` | Python 3.11, FastAPI, QuantipyMRX, Redis |
| **npm SDK** | `quack2025/insightgenius-sdk` | `C:\Users\jorge\proyectos_python\insightgenius-sdk` | TypeScript, tsup, vitest, MSW |
| **Claude Code Skill** | `quack2025/insightgenius-skill` | `C:\Users\jorge\proyectos_python\insightgenius-skill` | Markdown (SKILL.md) |
| **Zapier Integration** | `quack2025/insightgenius-zapier` | `C:\Users\jorge\proyectos_python\insightgenius-zapier` | Node.js, zapier-platform-core |

## Distribution Channels

| Canal | URL | Status | Audiencia |
|-------|-----|--------|-----------|
| **REST API** | https://spss.insightgenius.io | Live | Developers, agencies, automation tools |
| **Claude.ai MCP** | Settings > Connectors > Talk2Data InsightGenius | Live | Claude.ai users (millones) |
| **npm** | `npm install insightgenius-sdk` | Live (v0.1.0) | JS/TS developers |
| **Zapier** | platform.zapier.com → InsightGenius | Live (v1.0.0) | Zapier users (6M+) |
| **Claude Code Skill** | github.com/quack2025/insightgenius-skill | Live | Claude Code users |
| **Swagger/OpenAPI** | https://spss.insightgenius.io/docs | Live | API consumers |
| **MCP Docs** | https://spss.insightgenius.io/docs/mcp | Live | MCP integrators |

## Deployment

| Repo | Deploy method | Auto-deploy? |
|------|--------------|--------------|
| Backend API | Railway (4 replicas) | Yes, push to `master` |
| npm SDK | `npm publish --access public` | Manual |
| Zapier | `zapier push` | Manual |
| Skill | Git push (public repo) | N/A |

## Key Metrics

| Metric | Value |
|--------|-------|
| REST endpoints | 29 |
| MCP tools | 13 |
| Zapier actions | 5 |
| Zapier triggers | 1 |
| SDK methods | 28 |
| Backend tests | 114 |
| SDK tests | 13 |
| Zapier tests | 6 |
| Enterprise score | 7.5/10 |

## Skills (local, no repo)

| Skill | Path | Comando |
|-------|------|---------|
| SPSS Analysis | `~/.claude/skills/spss/SKILL.md` | `/spss` |
| Enterprise Audit | `~/.claude/skills/audit-enterprise/SKILL.md` | `/audit-enterprise` |
