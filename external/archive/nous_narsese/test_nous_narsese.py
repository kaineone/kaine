import pytest

from kaine.modules.nous.narsese import (
    TruthValue,
    make_belief,
    make_implication,
    parse_derivation_line,
    slugify_atom,
)


def test_slugify_basic():
    assert slugify_atom("soma") == "soma"
    assert slugify_atom("wellness.update") == "wellness_update"
    assert slugify_atom("a-b/c d") == "a_b_c_d"


def test_slugify_empty_yields_unknown():
    assert slugify_atom("") == "unknown"
    assert slugify_atom("...") == "unknown"


def test_slugify_leading_digit_padded():
    assert slugify_atom("3pm") == "_3pm"
    assert slugify_atom("9_alarms") == "_9_alarms"


def test_make_belief_structure():
    s = make_belief("soma", "wellness.update", 0.6)
    assert s == "<soma --> [wellness_update]>. :|: %0.6;0.9%"


def test_make_belief_clamps_salience():
    assert "%0.0;" in make_belief("a", "b", -0.5)
    assert "%1.0;" in make_belief("a", "b", 1.5)


def test_make_belief_clamps_confidence():
    s = make_belief("a", "b", 0.5, confidence=1.5)
    assert ";1.0%" in s


def test_make_implication_structure():
    s = make_implication("foo", "<bar --> baz>")
    assert s.startswith("<foo =/> <bar --> baz>>. :|: %1.0;")


def test_truth_value_repr():
    tv = TruthValue(0.5, 0.9)
    assert tv.as_narsese() == "%0.5;0.9%"


def test_parse_input_line():
    line = (
        "Input: <bird --> animal>. :|: occurrenceTime=1 Priority=1.000000 "
        "Stamp=[1] Truth: frequency=1.000000, confidence=0.900000"
    )
    d = parse_derivation_line(line)
    assert d is not None
    assert d.kind == "Input"
    assert d.statement == "<bird --> animal>. :|:"
    assert d.truth.frequency == 1.0
    assert d.truth.confidence == 0.9


def test_parse_derived_with_dt_prefix():
    line = (
        "Derived: dt=1.000000 <<$1 --> animal> =/> <$1 --> flier>>. "
        "Priority=0.232201 Stamp=[1,2] Truth: frequency=1.000000, confidence=0.282230"
    )
    d = parse_derivation_line(line)
    assert d is not None
    assert d.kind == "Derived"
    assert d.statement == "<<$1 --> animal> =/> <$1 --> flier>>."
    assert d.truth.frequency == 1.0
    assert d.truth.confidence == 0.282230


def test_parse_revised_line():
    line = (
        "Revised: <a --> b>. Priority=0.5 Stamp=[3,4] "
        "Truth: frequency=0.7245, confidence=0.5018"
    )
    d = parse_derivation_line(line)
    assert d is not None
    assert d.kind == "Revised"
    assert d.truth.frequency == 0.7245
    assert d.truth.confidence == 0.5018


def test_parse_unknown_line_returns_none():
    assert parse_derivation_line("performing 5 inference steps:") is None
    assert parse_derivation_line("done with 5 additional inference steps.") is None
    assert parse_derivation_line("") is None


def test_parse_answer_line():
    line = (
        "Answer: <a --> b>. occurrenceTime=10 Priority=1 Stamp=[5] "
        "Truth: frequency=0.5, confidence=0.4"
    )
    d = parse_derivation_line(line)
    assert d is not None
    assert d.kind == "Answer"
    assert d.statement == "<a --> b>."
