import pytest

from ck_agent.verification import validate_email, extract_ssn_last4, parse_dob, verify_user


# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

class TestValidateEmail:
    def test_simple_valid(self):
        r = validate_email("user@ck1.com")
        assert r.ok and r.value == "user@ck1.com"

    def test_subdomain_digits_valid(self):
        r = validate_email("alice.nguyen@ck123.com")
        assert r.ok and r.value == "alice.nguyen@ck123.com"

    def test_uppercased_is_accepted_and_lowercased(self):
        r = validate_email("BOB@CK2.COM")
        assert r.ok and r.value == "bob@ck2.com"

    def test_gmail_rejected(self):
        r = validate_email("user@gmail.com")
        assert not r.ok

    def test_ck_without_digit_rejected(self):
        r = validate_email("user@ck.com")
        assert not r.ok

    def test_wrong_tld_rejected(self):
        r = validate_email("user@ck1.net")
        assert not r.ok

    def test_non_digit_after_ck_rejected(self):
        r = validate_email("user@ck1a.com")
        assert not r.ok


# ---------------------------------------------------------------------------
# SSN last-4 extraction
# ---------------------------------------------------------------------------

class TestExtractSsnLast4:
    def test_bare_four_digits(self):
        r = extract_ssn_last4("1234")
        assert r.ok and r.value == "1234"

    def test_full_formatted_ssn(self):
        r = extract_ssn_last4("123-45-6789")
        assert r.ok and r.value == "6789"

    def test_natural_language(self):
        r = extract_ssn_last4("my ssn last 4 is 7890")
        assert r.ok and r.value == "7890"

    def test_eight_digits_takes_last_four(self):
        r = extract_ssn_last4("12345678")
        assert r.ok and r.value == "5678"

    def test_too_few_digits_rejected(self):
        r = extract_ssn_last4("123")
        assert not r.ok

    def test_empty_string_rejected(self):
        r = extract_ssn_last4("")
        assert not r.ok


# ---------------------------------------------------------------------------
# DOB parsing (integration — hits Bedrock)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestParseDob:
    def test_month_name_format(self):
        r = parse_dob("January 5, 1990")
        assert r.ok and r.value == "1990-01-05"

    def test_natural_sentence(self):
        r = parse_dob("I was born on May 10, 1985")
        assert r.ok and r.value == "1985-05-10"

    def test_us_numeric_format(self):
        r = parse_dob("05/10/1985")
        assert r.ok and r.value == "1985-05-10"

    def test_nonsense_returns_error(self):
        r = parse_dob("the banana is yellow")
        assert not r.ok


# ---------------------------------------------------------------------------
# verify_user end-to-end
# ---------------------------------------------------------------------------

class TestVerifyUser:
    def test_correct_credentials_verified(self):
        # Alice: ssn_full=123456789, dob_iso=1990-03-15
        r = verify_user(email="alice@ck1.com", ssn_last4="6789", dob_iso="1990-03-15")
        assert r.verified
        assert r.user is not None
        assert r.user.full_name == "Alice Nguyen"

    def test_wrong_ssn_rejected(self):
        r = verify_user(email="alice@ck1.com", ssn_last4="9999", dob_iso="1990-03-15")
        assert not r.verified
        assert r.reason == "Verification details do not match our records"

    def test_wrong_dob_rejected(self):
        r = verify_user(email="alice@ck1.com", ssn_last4="6789", dob_iso="1990-01-01")
        assert not r.verified
        assert r.reason == "Verification details do not match our records"

    def test_unknown_email_rejected(self):
        r = verify_user(email="nobody@ck99.com", ssn_last4="1234", dob_iso="1990-01-01")
        assert not r.verified
        assert r.reason == "No account found for this email"

    def test_error_message_does_not_leak_field(self):
        # Wrong SSN and wrong DOB should return identical message — no field leakage
        r_ssn = verify_user(email="alice@ck1.com", ssn_last4="0000", dob_iso="1990-03-15")
        r_dob = verify_user(email="alice@ck1.com", ssn_last4="6789", dob_iso="2000-01-01")
        assert r_ssn.reason == r_dob.reason
