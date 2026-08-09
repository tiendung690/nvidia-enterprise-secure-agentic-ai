from __future__ import annotations

import pytest

from nvidia_agentic_rag.security import DataMasker, OutputPolicy, OutputPolicyViolation


def test_redaction_and_stable_pseudonymization() -> None:
    redactor = DataMasker(mode="redact", salt="s")
    result = redactor.apply("Email a@example.com card 4111 1111 1111 1111 nvapi-ABCDEFGHIJKLM")
    assert "a@example.com" not in result.text
    assert "4111" not in result.text
    assert "nvapi-" not in result.text
    assert set(result.signals) == {"api_key", "email", "payment_card"}

    pseudonymizer = DataMasker(mode="pseudonymize", salt="s")
    first = pseudonymizer.apply("a@example.com").text
    second = pseudonymizer.apply("a@example.com").text
    assert first == second
    assert first.startswith("[EMAIL_")


def test_output_policy_audit_redact_and_block() -> None:
    masker = DataMasker(mode="redact", salt="s")
    audit = OutputPolicy(mode="audit", masker=masker).validate("a@example.com")
    assert audit.answer == "a@example.com"
    assert audit.signals

    redacted = OutputPolicy(mode="redact", masker=masker).validate("a@example.com")
    assert redacted.modified
    assert "a@example.com" not in redacted.answer

    with pytest.raises(OutputPolicyViolation):
        OutputPolicy(mode="block", masker=masker).validate("a@example.com")


def test_masking_off_and_clean_output() -> None:
    masker = DataMasker(mode="off", salt="s")
    assert masker.apply("clean").text == "clean"
    output = OutputPolicy(mode="off", masker=masker).validate("clean")
    assert not output.signals
