from pydantic import BaseModel


class VerificationResult(BaseModel):
    verified: bool
    reason: str | None = None
    user: object | None = None  # typed properly in phase 03


def verify_user(email: str, ssn_last4: str, dob_iso: str) -> VerificationResult:
    """Stub — phase 03 will implement real logic."""
    return VerificationResult(verified=False, reason="verification not implemented yet")
