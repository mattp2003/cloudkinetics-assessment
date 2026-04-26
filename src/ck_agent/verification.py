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
PARSER_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"


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
    Parse date of birth from any natural-language format.
    Returns ISO YYYY-MM-DD or an error reason.

    Fast path: if the input is already YYYY-MM-DD, return it immediately
    without calling Bedrock (keeps unit tests credential-free and saves latency).

    Slow path: delegate to Bedrock for natural-language / ambiguous formats.
    We use an LLM here instead of dateutil/regex because users phrase dates
    wildly differently and ambiguous formats (05/01/1990) benefit from
    conversational context. Structured JSON output gives us type safety.
    """
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw.strip()):
        return FieldResult(ok=True, value=raw.strip())

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

        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()

        parsed = json.loads(text)
        iso = parsed.get("iso_date")
        if not iso:
            return FieldResult(ok=False, reason=f"Could not parse a date from {raw!r}")

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
            return FieldResult(ok=False, reason=f"LLM returned malformed date: {iso}")

        return FieldResult(ok=True, value=iso)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return FieldResult(ok=False, reason=f"DOB parse failed: {e}")


def verify_user(email: str, ssn_last4: str, dob_iso: str) -> VerificationResult:
    """
    Look up user by email, confirm SSN last-4 and DOB match.
    All three fields must already be individually validated before calling this.

    Error messages are intentionally generic — do not leak which field failed.
    This is standard practice for authentication flows to prevent enumeration attacks.
    """
    user = USERS.get(email.strip().lower())
    if user is None:
        return VerificationResult(verified=False, reason="No account found for this email")

    if user.ssn_full[-4:] != ssn_last4:
        return VerificationResult(verified=False, reason="Verification details do not match our records")

    if user.dob_iso != dob_iso:
        return VerificationResult(verified=False, reason="Verification details do not match our records")

    return VerificationResult(verified=True, user=user)
