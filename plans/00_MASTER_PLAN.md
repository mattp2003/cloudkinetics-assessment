# Master Plan — Execution Order & Rules

## Instructions for Claude Code

**At the start of every session, read in this order:**
1. `DECISIONS.md` (architecture north star — never deviates)
2. `plans/00_MASTER_PLAN.md` (this file)
3. `plans/0X_<current_phase>.md` (the single phase you're executing)

**Do NOT read other phase files.** Each phase is intentionally isolated. Reading ahead causes scope drift and premature decisions.

**At the end of every phase:**
1. Run the verification commands in the phase file
2. If any verification fails, DO NOT proceed to the next phase
3. Commit with the exact message specified in the phase file
4. Report completion to the user and STOP — do not auto-start next phase

**When in doubt, ask the user before writing code.** Clarification is cheaper than refactoring.

---

## Phase list & dependency graph

```
Day 0 (Friday evening, already done): planning
│
Day 1 (Saturday):
├── 01_project_setup           [30 min]
├── 02_mock_data_and_tools     [45 min]  — local only
├── 03_verification_logic      [45 min]  — local only
├── 04_agent_loop_local        [90 min]  — Level 100 complete ✅
├── 05_bedrock_kb_ingestion    [30 min]  — uses console + CLI
├── 06_rag_diagnostic          [45 min]  — captures screenshots for design doc
├── 07_cdk_infrastructure      [90 min]
├── 08_lambda_handler          [60 min]
├── 09_websocket_streaming     [60 min]  — Level 200 core complete ✅
└── 10_frontend                [45 min]  — end of Saturday
│
Day 2 (Sunday):
├── 11_conversation_persistence  [60 min]
├── 12_observability             [60 min]  — Level 300 impl complete ✅
├── 13_cicd                      [45 min]
├── 14_tests                     [45 min]
└── (non-code) design doc + slides + submission
```

## Critical checkpoints

| After phase | You can submit and still pass | Reasoning |
|-------------|-------------------------------|-----------|
| 04 | Yes, as "Level 100 only" | Working agent locally, honest scoping in design doc |
| 10 | Yes, as "L100 + L200" | Deployed streaming system |
| 12 | Yes, full submission | All required L300 done |
| 14 | Ideal submission | Tests + CI give professional finish |

## Time pressure rules

**If you fall 2+ hours behind by end of Saturday:**
- SKIP phase 13 (CI/CD) — describe in design doc instead
- SKIP phase 14 (tests) down to minimum 3 test cases for verification logic
- Prioritize design doc over additional implementation

**If you fall 4+ hours behind:**
- Execute fallback in DECISIONS.md
- Do not try to "catch up" by cutting corners in current phase — finish current phase cleanly, skip next optional one

**Red lines (never cross):**
- Never skip verification steps
- Never commit broken code to main
- Never hardcode AWS credentials
- Never skip the demo recording (Saturday Block 6 in original plan)

---

## Commit message format

Every phase commits with:
```
[phase NN] <short description>

- Bullet list of what was added
- Reference to plan file: plans/NN_<name>.md
```

Example:
```
[phase 03] Add verification logic for email/SSN/DOB

- Email regex validator for @ck<int>.com pattern
- SSN last-4 extractor (strip non-digits, take last 4)
- DOB parser using Bedrock structured output
- Unit tests for all three validators
- Reference: plans/03_verification_logic.md
```

---

## Definition of "done" for the whole project

A reviewer at CloudKinetics can:
1. Open the GitHub repo and understand the system from the README in under 3 minutes
2. Watch the demo video and see all required flows work
3. Open the design doc and understand every architectural decision
4. Clone the repo and deploy it themselves with one command (`cdk deploy`)
5. Read the test suite and trust the verification logic is correct
