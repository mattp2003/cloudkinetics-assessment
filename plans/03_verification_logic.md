# Phase 03 — Verification Logic

## Prerequisites

- [ ] Phase 02 complete (mock data + tool stubs in place)
- [ ] `src/ck_agent/verification.py` stub exists

## Goal

Implement email regex, SSN last-4 extraction, and DOB natural-language parsing. These are the assessment's three "tricky" requirements and the primary way interviewers will probe your code.

## Context for Claude Code

- Email validation is strict: must match `@ck<digits>.com` pattern exactly
- SSN: user may input any format (`123-45-6789`, `6789`, `my ssn is 1234`, etc.) — strip non-digits, take last 4
- DOB: user may input ANY format — do NOT regex this. Use a Bedrock LLM call with structured output to parse it. This is the right engineering choice and a design-doc talking point.
- Every verification function returns a structured result with `ok: bool` and either the parsed value or a specific `reason`

## Steps

### 3.1 — `src/ck_agent/verification.py` full implementation

Replace the stub with:

```python
from __future__ import annotations
import json
import re
from dataclasses import dataclass

import boto3
from pydantic import BaseModel

from ck_agent.mock_data import USERS, User

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@ck\d+\.com$")
DIGITS_ONLY = re.compile(r"\D")

BEDROCK = boto3.client("bedrock-runtime", region_name="us-east-1")
PARSER_MODEL_ID = "global.anthropic.claude-sonnet-4-6-v1:0"  # see DECISIONS.md


@dataclass
class FieldResult:
    ok: bool
    value: str | None = None
    reason: str | None = None


class VerificationResult(BaseModel):
    verified: bool
    reason: str | None = None
    user: User | None = None

    model_config = {"arbitrary_types_allowed": True}


def validate_email(raw: str) -> FieldResult:
    """Email must match @ck<digits>.com pattern."""
    cleaned = raw.strip().lower()
    if EMAIL_PATTERN.match(cleaned):
        return FieldResult(ok=True, value=cleaned)
    return FieldResult(
        ok=False,
        reason=f"Email must match pattern user@ck<number>.com (got: {raw!r})",
    )


def extract_ssn_last4(raw: str) -> FieldResult:
    """Strip all non-digits, take last 4. Must have at least 4 digits."""
    digits = DIGITS_ONLY.sub("", raw)
    if len(digits) < 4:
        return FieldResult(
            ok=False,
            reason=f"Need at least 4 digits for SSN (got {len(digits)} digits)",
        )
    return FieldResult(ok=True, value=digits[-4:])


def parse_dob(raw: str) -> FieldResult:
    """
    Parse date of birth from any natural-language format using Bedrock.
    Returns ISO YYYY-MM-DD or an error reason.

    Design note: we use an LLM for this instead of dateutil/regex because:
    1. Users phrase dates wildly differently ("I was born on Jan 5th, 1990",
       "05-01-90", "five january ninety", etc.)
    2. LLM handles ambiguous formats (05/01/1990 could be Jan 5 or May 1)
       by using conversational context and returning a best-guess with confidence
    3. Structured output (JSON mode) gives us type safety
    """
    prompt = (
        "Extract the date of birth from the user's input below. "
        "Return ONLY a JSON object with this exact schema:\n"
        '{"iso_date": "YYYY-MM-DD" or null, "confidence": "high"|"medium"|"low", "note": "..."}\n\n'
        "Rules:\n"
        "- If no date can be extracted, iso_date must be null\n"
        "- For ambiguous formats like 05/01/1990, prefer US format (May 1, 1990) "
        "and note the ambiguity\n"
        "- Only return dates that could plausibly be a date of birth "
        "(i.e., year between 1900 and today)\n"
        "- Do not include any text outside the JSON object\n\n"
        f"User input: {raw!r}"
    )

    try:
        response = BEDROCK.converse(
            modelId=PARSER_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.0, "maxTokens": 200},
        )
        text = response["output"]["message"]["content"][0]["text"].strip()

        # Strip any accidental markdown fencing
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()

        parsed = json.loads(text)
        iso = parsed.get("iso_date")
        if not iso:
            return FieldResult(ok=False, reason=f"Could not parse a date from {raw!r}")

        # Sanity check format
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
            return FieldResult(ok=False, reason=f"LLM returned malformed date: {iso}")

        return FieldResult(ok=True, value=iso)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return FieldResult(ok=False, reason=f"DOB parse failed: {e}")


def verify_user(email: str, ssn_last4: str, dob_iso: str) -> VerificationResult:
    """
    Final check: look up user by email, confirm SSN last-4 and DOB match.
    All three fields must already be validated individually before calling this.
    """
    user = USERS.get(email.strip().lower())
    if user is None:
        return VerificationResult(verified=False, reason="No account found for this email")

    if user.ssn_full[-4:] != ssn_last4:
        return VerificationResult(verified=False, reason="Verification details do not match our records")

    if user.dob_iso != dob_iso:
        return VerificationResult(verified=False, reason="Verification details do not match our records")

    return VerificationResult(verified=True, user=user)
```

**Security note to include as a comment in the file:** the "details do not match" message is intentionally generic — do not leak which field failed. This is a standard practice for authentication flows.

### 3.2 — Unit tests (create `tests/test_verification.py`)

Test these cases explicitly:

**Email:**
- ✅ `user@ck1.com`
- ✅ `alice.nguyen@ck123.com`
- ✅ `BOB@CK2.COM` (should be lowercased, accepted)
- ❌ `user@gmail.com` (wrong domain)
- ❌ `user@ck.com` (missing digit)
- ❌ `user@ck1.net` (wrong TLD)
- ❌ `user@ck1a.com` (non-digit after ck)

**SSN last-4:**
- `"1234"` → `"1234"`
- `"123-45-6789"` → `"6789"`
- `"my ssn last 4 is 7890"` → `"7890"`
- `"12345678"` (8 digits) → `"5678"` (takes last 4)
- `"123"` → error (not enough digits)
- `""` → error

**DOB:** (these hit Bedrock — mark as `@pytest.mark.integration` so they can be skipped)
- `"January 5, 1990"` → `"1990-01-05"`
- `"I was born on May 10, 1985"` → `"1985-05-10"`
- `"05/10/1985"` → `"1985-05-10"` (US format)
- `"the banana is yellow"` → `ok=False`

### 3.3 — Wire into `tools.py`

`check_order_status` already calls `verify_user`. Now that it works, test the flow:

```bash
python -c "
from ck_agent.tools import check_order_status
# Alice's full data from mock_data
r = check_order_status(email='alice@ck1.com', ssn_last4='0001', dob_iso='1990-03-15')
print(r)
"
```

(Note: you need the SSN/DOB values to match what you seeded in `mock_data.py`. Make sure they're consistent.)

## Verification (human-runnable)

```bash
# Unit tests (no Bedrock)
pytest tests/test_verification.py -v -k "not integration"
# Expected: all pass

# Integration tests (hits Bedrock, costs ~$0.01)
pytest tests/test_verification.py -v -m integration
# Expected: all pass

# End-to-end verification flow
python -c "
from ck_agent.tools import check_order_status
r = check_order_status(email='alice@ck1.com', ssn_last4='<alice_real_last4>', dob_iso='<alice_dob>')
assert r['verified'] is True
assert 'multiple_orders_found' in r or 'order' in r
print('VERIFY OK')
"
# Expected: VERIFY OK (Alice has 3 orders → multiple_orders_found=True)

# Wrong SSN rejects
python -c "
from ck_agent.tools import check_order_status
r = check_order_status(email='alice@ck1.com', ssn_last4='9999', dob_iso='1990-01-01')
assert r['verified'] is False
print('REJECT OK')
"
```

## Definition of Done

- [ ] Email regex handles all 7 test cases
- [ ] SSN extraction handles all 6 test cases
- [ ] DOB parser handles all 4 test cases via Bedrock
- [ ] `verify_user` returns generic error message (does not leak which field failed)
- [ ] `check_order_status` successfully returns verified=True for a correct triple
- [ ] `check_order_status` returns verified=False for any mismatch
- [ ] All tests pass

## Out of Scope

- ❌ Rate limiting / brute force protection (designed in doc only)
- ❌ Audit logging for failed attempts (phase 12)
- ❌ Alternative parsers (dateutil as fallback) — not needed if LLM parse works
- ❌ Agent loop using these tools (phase 04)

## Commit Message

```
[phase 03] Implement verification logic

- Email regex validator for @ck<digits>.com pattern with test coverage
- SSN last-4 extractor (strip non-digits, return final 4)
- DOB parser using Bedrock Converse with structured JSON output
- verify_user with generic error messages (no field-level leakage)
- 17 unit tests covering edge cases; Bedrock tests marked as integration
- Reference: plans/03_verification_logic.md
```
