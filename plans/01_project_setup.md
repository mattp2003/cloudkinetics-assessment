# Phase 01 — Project Setup

## Prerequisites

- [ ] AWS account with admin or PowerUser access
- [ ] AWS CLI installed and configured (`aws sts get-caller-identity` returns your account)
- [ ] Node.js 20+ installed (for AWS CDK)
- [ ] Python 3.13 installed (`python --version` or `python3.13 --version`)
- [ ] Git installed
- [ ] GitHub account
- [ ] An empty GitHub repo created: `cloudkinetics-assessment` (public)

## Goal

A local Python project scaffold, AWS CDK installed, Bedrock model access confirmed, and the repo pushed to GitHub.

## Context for Claude Code

- This is pure scaffolding. No business logic yet.
- Files to create: `pyproject.toml` or `requirements.txt`, `.gitignore`, `README.md` (stub), `src/ck_agent/__init__.py`
- Do NOT start writing agent logic, tool definitions, or CDK stacks in this phase
- Do NOT create AWS resources yet — only verify access

## Steps

### 1.1 — Verify AWS prerequisites (user does this, report results)

Ask the user to run these commands and share output:
```bash
aws sts get-caller-identity
# List available Claude models (current generation: 4.6, 4.5, 4.7 for Opus)
aws bedrock list-inference-profiles --region us-east-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileName, 'claude')].[inferenceProfileId, status]" \
  --output table
```

Expected: account ID returned, and `global.anthropic.claude-sonnet-4-6-v1:0` listed. If model access hasn't been granted yet, Matthew said he already has access — but if an `AccessDeniedException` appears, go to the Bedrock console → Model access → enable Anthropic models.

### 1.2 — Create project structure

```
cloudkinetics-assessment/
├── .gitignore
├── README.md
├── DECISIONS.md              (already exists)
├── pyproject.toml
├── plans/                    (already exists)
├── src/
│   └── ck_agent/
│       ├── __init__.py
│       ├── agent.py          (empty stub)
│       ├── tools.py          (empty stub)
│       ├── verification.py   (empty stub)
│       └── mock_data.py      (empty stub)
├── cdk/                      (will be populated in phase 07)
├── frontend/                 (will be populated in phase 10)
├── tests/
│   └── __init__.py
└── docs/
    └── .gitkeep
```

### 1.3 — `pyproject.toml` content

Use `uv` if available, otherwise plain pip + venv. Minimum deps:

```toml
[project]
name = "ck-agent"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "boto3>=1.35.0",
    "pydantic>=2.9.0",
    "python-dateutil>=2.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.6.0",
]

[tool.ruff]
line-length = 100
```

### 1.4 — `.gitignore` content

Standard Python + AWS + IDE patterns. Must include:
- `.venv/`, `__pycache__/`, `*.pyc`
- `.env`, `.env.*`
- `cdk.out/`, `cdk.context.json`
- `.pytest_cache/`
- `.vscode/`, `.idea/`

### 1.5 — Create virtualenv and install

```bash
python3.13 -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

### 1.6 — Install AWS CDK globally

```bash
npm install -g aws-cdk
cdk --version  # should be 2.x
```

### 1.7 — Stub README

Create a minimal README that will be expanded in phase 11/final polish. Just needs:
- Project title
- One-sentence description
- "Work in progress — see plans/ directory"

### 1.8 — Initial commit and push

```bash
git init
git add .
git commit -m "[phase 01] Project scaffolding"
git remote add origin <github-url>
git push -u origin main
```

## Verification (human-runnable)

Run these commands. All must pass:

```bash
# Python environment works
python -c "import boto3, pydantic; print('OK')"
# Expected: OK

# AWS access works
aws sts get-caller-identity
# Expected: your account ID returned

# Bedrock Claude Sonnet 4.6 is accessible via Global CRIS inference profile
aws bedrock-runtime converse \
  --model-id global.anthropic.claude-sonnet-4-6-v1:0 \
  --messages '[{"role":"user","content":[{"text":"say hi in 3 words"}]}]' \
  --region us-east-1
# Expected: JSON response with a 3-word greeting
# If the global. prefix fails, try regional: anthropic.claude-sonnet-4-6-v1:0
# If Sonnet 4.6 isn't enabled in your region/account, fall back to:
#   global.anthropic.claude-sonnet-4-5-v1:0
# and update DECISIONS.md

# CDK works
cdk --version
# Expected: 2.x.y (build ...)

# Repo pushed
git log --oneline
# Expected: at least one commit
```

## Definition of Done

- [ ] All verification commands pass
- [ ] Repo visible on GitHub with initial commit
- [ ] Model ID confirmed working (update DECISIONS.md if you had to fall back to a different model)
- [ ] `.venv` activated; `pip list` shows boto3, pydantic, pytest, ruff

## Out of Scope

- ❌ Writing any agent code
- ❌ Creating CDK stacks
- ❌ Creating Bedrock Knowledge Base
- ❌ Writing tests
- ❌ Setting up CI/CD

## Commit Message

```
[phase 01] Project scaffolding

- Python 3.13 venv with boto3, pydantic, pytest, ruff
- Directory structure: src/ck_agent, cdk/, frontend/, tests/, docs/
- .gitignore for Python + AWS + IDE
- AWS CDK installed globally
- Bedrock Claude Sonnet 4.6 access verified in us-east-1 (via global CRIS profile)
- Reference: plans/01_project_setup.md
```
