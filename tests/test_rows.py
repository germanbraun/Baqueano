from baqueano.context import worst
from baqueano.rows import int_value, iri, node_id, value
from tests.fakes import bnode, iri as iri_term, lit


def test_row_helpers():
    row = {"a": iri_term("http://x"), "b": bnode("b0"), "n": lit("12"), "f": lit("1.5E3"), "bad": lit("many")}
    assert value(row, "a") == "http://x"
    assert value(row, "missing") is None
    assert iri(row, "a") == "http://x"
    assert iri(row, "b") is None
    assert node_id(row, "b") == "_:b0"
    assert int_value(row, "n") == 12
    assert int_value(row, "f") == 1500
    assert int_value(row, "bad") is None


def test_worst():
    assert worst("ok", "ok") == "ok"
    assert worst("ok", "sampled", "timeout") == "timeout"
    assert worst("skipped", "error") == "error"
    assert worst("unsupported", "ok") == "unsupported"
