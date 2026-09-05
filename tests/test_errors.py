"""Tests for the coded exception taxonomy.

The point of the taxonomy is that it adds a machine-readable ``.code``
*without* changing anything an existing caller can observe, so most of these
tests are backwards-compatibility tests: the builtin a caller already catches,
and the exact message text a caller already compares.
"""

import pytest

from projectman.deps import CycleError
from projectman.errors import (
    ERROR_CLASSES,
    ERROR_CODES,
    GENERIC_ERROR_CODE,
    ConflictError,
    NotFoundError,
    ProjectManError,
    StoreError,
    ValidationError,
    code_for,
)

# (class, builtin it must also be, code)
TAXONOMY = [
    (NotFoundError, FileNotFoundError, "not_found"),
    (ValidationError, ValueError, "invalid"),
    (ConflictError, RuntimeError, "conflict"),
    (StoreError, RuntimeError, "store"),
]


# ── codes ────────────────────────────────────────────────────────────


class TestCodes:
    @pytest.mark.parametrize("cls,_builtin,code", TAXONOMY)
    def test_class_declares_its_code(self, cls, _builtin, code):
        assert cls.code == code

    @pytest.mark.parametrize("cls,_builtin,code", TAXONOMY)
    def test_instance_carries_its_code(self, cls, _builtin, code):
        assert cls("boom").code == code

    def test_base_has_a_generic_code(self):
        assert ProjectManError("boom").code == GENERIC_ERROR_CODE

    def test_every_code_is_registered(self):
        for cls, _builtin, code in TAXONOMY:
            assert code in ERROR_CODES
            assert cls in ERROR_CLASSES

    def test_registry_matches_the_classes(self):
        assert ERROR_CODES == tuple(cls.code for cls in ERROR_CLASSES)

    def test_codes_are_unique(self):
        assert len(set(ERROR_CODES)) == len(ERROR_CODES)

    def test_code_can_be_overridden_per_instance(self):
        err = ValidationError("boom", code="custom")
        assert err.code == "custom"
        assert ValidationError.code == "invalid"


# ── message round-trip ───────────────────────────────────────────────


class TestMessage:
    @pytest.mark.parametrize("cls", [ProjectManError, *(c for c, _b, _c in TAXONOMY)])
    def test_str_is_exactly_the_message(self, cls):
        assert str(cls("Task US-TST-1-1 not found")) == "Task US-TST-1-1 not found"

    @pytest.mark.parametrize("cls", [ProjectManError, *(c for c, _b, _c in TAXONOMY)])
    def test_message_attribute_round_trips(self, cls):
        assert cls("something went wrong").message == "something went wrong"

    def test_args_hold_the_message(self):
        assert NotFoundError("gone").args == ("gone",)

    def test_code_kwarg_does_not_leak_into_the_message(self):
        assert str(StoreError("disk full", code="custom")) == "disk full"


# ── builtin compatibility ────────────────────────────────────────────


class TestBuiltinCompatibility:
    @pytest.mark.parametrize("cls,builtin,_code", TAXONOMY)
    def test_is_instance_of_the_builtin(self, cls, builtin, _code):
        assert isinstance(cls("boom"), builtin)

    @pytest.mark.parametrize("cls,_builtin,_code", TAXONOMY)
    def test_is_a_projectman_error(self, cls, _builtin, _code):
        assert isinstance(cls("boom"), ProjectManError)

    def test_except_file_not_found_catches_not_found(self):
        try:
            raise NotFoundError("gone")
        except FileNotFoundError as exc:
            assert exc.code == "not_found"
        else:  # pragma: no cover - the raise above always fires
            pytest.fail("NotFoundError was not caught by except FileNotFoundError")

    def test_except_value_error_catches_validation(self):
        try:
            raise ValidationError("bad points")
        except ValueError as exc:
            assert exc.code == "invalid"
        else:  # pragma: no cover
            pytest.fail("ValidationError was not caught by except ValueError")

    @pytest.mark.parametrize("cls,code", [(ConflictError, "conflict"), (StoreError, "store")])
    def test_except_runtime_error_catches_conflict_and_store(self, cls, code):
        try:
            raise cls("nope")
        except RuntimeError as exc:
            assert exc.code == code
        else:  # pragma: no cover
            pytest.fail(f"{cls.__name__} was not caught by except RuntimeError")

    def test_pytest_raises_on_the_builtin_still_works(self):
        with pytest.raises(ValueError, match="bad points"):
            raise ValidationError("bad points")

    def test_conflict_is_not_a_validation_error(self):
        assert not isinstance(ConflictError("x"), ValueError)

    def test_validation_is_not_a_runtime_error(self):
        assert not isinstance(ValidationError("x"), RuntimeError)


# ── CycleError ───────────────────────────────────────────────────────


class TestCycleErrorJoinsTheTaxonomy:
    def test_is_a_validation_error(self):
        assert isinstance(CycleError(["A", "B", "A"]), ValidationError)

    def test_is_still_a_value_error(self):
        assert isinstance(CycleError(["A", "B", "A"]), ValueError)

    def test_code_is_invalid(self):
        assert CycleError(["A", "B", "A"]).code == "invalid"

    def test_message_still_holds_the_path(self):
        err = CycleError(["A", "B", "A"])
        assert "A -> B -> A" in str(err)
        assert err.message == str(err)

    def test_cycle_attribute_survives(self):
        assert CycleError(["A", "B", "A"]).cycle == ["A", "B", "A"]


# ── code_for ─────────────────────────────────────────────────────────


class TestCodeFor:
    @pytest.mark.parametrize("cls,_builtin,code", TAXONOMY)
    def test_reads_the_taxonomy_code(self, cls, _builtin, code):
        assert code_for(cls("boom")) == code

    @pytest.mark.parametrize(
        "exc", [ValueError("x"), FileNotFoundError("x"), RuntimeError("x"), Exception("x")]
    )
    def test_falls_back_for_plain_builtins(self, exc):
        assert code_for(exc) == GENERIC_ERROR_CODE

    def test_fallback_code_is_registered(self):
        assert GENERIC_ERROR_CODE in ERROR_CODES

    def test_ignores_a_code_attribute_on_a_foreign_exception(self):
        class Impostor(Exception):
            code = "not_found"

        assert code_for(Impostor("x")) == GENERIC_ERROR_CODE


# ── the reference docs (US-PRJ-48-8) ─────────────────────────────────


def test_reference_docs_document_every_code():
    """``docs/reference/mcp-tools.md`` lists the whole taxonomy, not a subset.

    The table is the client-facing half of the promise that ``ERROR_CODES`` is
    a *closed* set: a code added to the taxonomy and not to the table would
    leave a caller unable to recognise it. Failing here is the reminder.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    doc = (root / "docs/reference/mcp-tools.md").read_text()
    assert "## Error codes" in doc
    for code in ERROR_CODES:
        assert f"| `{code}` |" in doc, f"{code} missing from the mcp-tools.md table"

    inventory = (root / "docs/reference/error-paths-inventory.md").read_text()
    assert "## 9. Error codes" in inventory
    for code in ERROR_CODES:
        assert f"| `{code}` |" in inventory, f"{code} missing from the inventory table"
