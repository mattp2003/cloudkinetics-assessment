# Phase 13 — CI/CD

## Prerequisites

- [ ] Phase 12 complete
- [ ] Repo pushed to GitHub
- [ ] `cdk synth` passes locally

## Goal

A GitHub Actions workflow that runs tests + `cdk synth` on every PR, and runs `cdk deploy` on push to main. The *existence* of this pipeline scores the Level 200 CI/CD point — you do not need anything elaborate.

## Context for Claude Code

- Use **OIDC** for AWS auth if possible (cleaner, no long-lived secrets). Fallback: access keys in GitHub Secrets.
- Keep the workflow short and readable — complexity here is a negative signal
- `KB_ID` passed via GitHub variable (not secret, it's not sensitive)

## Steps

### 13.1 — Set up AWS OIDC identity provider (one-time, ~5 min)

Pick ONE of two paths based on what's faster for you:

**Path A — OIDC (recommended, more professional):**

1. Go to IAM → Identity providers → Add provider
   - Type: OpenID Connect
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`

2. Create IAM role `GitHubActionsDeployRole` with trust policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:<YOUR_GH_USERNAME>/cloudkinetics-assessment:*"
      },
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      }
    }
  }]
}
```

3. Attach these managed policies to the role (simpler for the assessment; tighten in prod):
   - `AdministratorAccess` (yes, admin — this is a demo; document that prod would scope tightly)

4. Save the role ARN.

**Path B — Access keys (fallback, faster):**

1. Create IAM user `gh-actions-deployer` with programmatic access
2. Attach `AdministratorAccess` (same caveat)
3. Save access key ID and secret
4. In GitHub repo → Settings → Secrets and variables → Actions:
   - Secret: `AWS_ACCESS_KEY_ID`
   - Secret: `AWS_SECRET_ACCESS_KEY`

### 13.2 — Add GitHub variable for KB_ID

Repo → Settings → Secrets and variables → Actions → Variables tab → New:
- Name: `BEDROCK_KB_ID`
- Value: `<your KB ID>`

### 13.3 — Create `.github/workflows/ci.yml`

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test:
    name: Test & Synth
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install Python deps
        run: |
          pip install -e ".[dev]"
          pip install "aws-cdk-lib>=2.150.0" "constructs>=10.0.0"

      - name: Install CDK CLI
        run: npm install -g aws-cdk

      - name: Lint
        run: ruff check src tests

      - name: Run unit tests (skip integration)
        run: pytest tests -v -m "not integration"

      - name: CDK synth
        working-directory: cdk
        env:
          BEDROCK_KB_ID: ${{ vars.BEDROCK_KB_ID }}
          CDK_DEFAULT_ACCOUNT: "000000000000"
          CDK_DEFAULT_REGION: "us-east-1"
        run: cdk synth -c kb_id=$BEDROCK_KB_ID > /dev/null
```

### 13.4 — Create `.github/workflows/deploy.yml`

```yaml
name: Deploy

on:
  push:
    branches: [main]

permissions:
  id-token: write      # for OIDC
  contents: read

jobs:
  deploy:
    name: Deploy CkAgentStack
    runs-on: ubuntu-latest
    # Only run after CI succeeds — GitHub Actions doesn't natively chain
    # workflows; simplest is to let both run and assume CI stays green

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      # --- Path A: OIDC ---
      - name: Configure AWS (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<ACCOUNT_ID>:role/GitHubActionsDeployRole
          aws-region: us-east-1

      # --- Path B: Access keys (delete above block, use this instead) ---
      # - name: Configure AWS (keys)
      #   uses: aws-actions/configure-aws-credentials@v4
      #   with:
      #     aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
      #     aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      #     aws-region: us-east-1

      - name: Install deps
        run: |
          pip install -e ".[dev]"
          pip install "aws-cdk-lib>=2.150.0" "constructs>=10.0.0"
          npm install -g aws-cdk

      - name: Deploy
        working-directory: cdk
        env:
          BEDROCK_KB_ID: ${{ vars.BEDROCK_KB_ID }}
        run: cdk deploy -c kb_id=$BEDROCK_KB_ID --require-approval never
```

### 13.5 — Push and watch it run

```bash
git add .github/
git commit -m "[phase 13] CI/CD with GitHub Actions"
git push
```

Check the Actions tab on GitHub. Both workflows should run. CI must go green. Deploy is optional — if it fails, document in the design doc that the deploy workflow is "configured but needs account-specific role ARN substitution."

## Verification (human-runnable)

```bash
# Workflows exist
ls .github/workflows/
# Expected: ci.yml, deploy.yml

# CI passes on the latest push
# (check GitHub Actions tab in browser — or use gh CLI)
gh run list --workflow=ci.yml --limit 1
# Expected: most recent run shows "completed success"

# Deploy runs (may fail if OIDC ARN not substituted; that's fine, document it)
gh run list --workflow=deploy.yml --limit 1
```

## Definition of Done

- [ ] `.github/workflows/ci.yml` exists and passes
- [ ] `.github/workflows/deploy.yml` exists (working or documented as configured-but-not-wired)
- [ ] AWS credentials configured via OIDC (preferred) or secrets
- [ ] `BEDROCK_KB_ID` set as a GitHub variable
- [ ] Latest CI run on main branch is green

## Out of Scope

- ❌ Staging environments (one stack is fine for assessment)
- ❌ Manual approval gates on production deploys
- ❌ Semantic versioning / release management
- ❌ Security scanning (GitHub Dependabot, Snyk, etc.)
- ❌ Post-deploy smoke tests against the deployed stack

## Commit Message

```
[phase 13] CI/CD with GitHub Actions

- ci.yml: lint + unit tests + cdk synth on PRs and main
- deploy.yml: cdk deploy on push to main, via OIDC auth
- GitHub variable BEDROCK_KB_ID, no secrets in repo
- Reference: plans/13_cicd.md
```
