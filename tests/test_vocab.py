from baqueano.model import ClassInfo
from baqueano.steps import vocab
from tests.fakes import FakeClient, iri, lit, select, timeout
from tests.helpers import make_ctx

EX = "http://ex/"


def test_ontologies_from_rows():
    rows = [
        {"ont": iri(EX + "onto"), "label": lit("Ontología", lang="es"), "versionInfo": lit("1.2")},
        {"ont": iri(EX + "onto"), "label": lit("Ontology", lang="en"), "versionIRI": iri(EX + "onto/1.2")},
        {"ont": iri(EX + "other"), "title": lit("Other")},
    ]
    assert vocab.ontologies_from_rows(rows) == [
        {"iri": EX + "onto", "label": "Ontology", "version_iri": EX + "onto/1.2", "version_info": "1.2"},
        {"iri": EX + "other", "label": "Other", "version_iri": None, "version_info": None},
    ]


def test_label_language_preference():
    assert vocab.pick([lit("Persona", lang="es"), lit("Person"), lit("Person EN", lang="en")]) == "Person EN"
    assert vocab.pick([lit("Persona", lang="es"), lit("Person")]) == "Person"
    assert vocab.pick([lit("Persona", lang="es")]) == "Persona"
    assert vocab.pick([]) is None


def test_apply_labels():
    classes = [ClassInfo(EX + "A", 1, True), ClassInfo(EX + "B", 1, True)]
    rows = [{"c": iri(EX + "A"), "label": lit("A thing", lang="en"), "comment": lit("Some A.")},
            {"c": iri(EX + "B")}]
    assert vocab.apply_labels(classes, rows) == 1
    assert (classes[0].label, classes[0].comment) == ("A thing", "Some A.")
    assert classes[1].label is None


def test_run_batches_labels(monkeypatch):
    monkeypatch.setattr(vocab, "LABEL_BATCH", 2)
    ctx = make_ctx()
    ctx.discovery.classes = [ClassInfo(f"{EX}C{i}", 1, True) for i in range(5)]
    client = FakeClient({vocab.ONTOLOGIES_STEP: select([]),
                         vocab.LABELS_STEP: select([{"c": iri(EX + "C0"), "label": lit("zero")}])})
    result = vocab.run(client, ctx)
    assert result.status == "ok"
    assert len(client.queries_for(vocab.LABELS_STEP)) == 3
    assert "1 of 5 classes have a label" in result.message


def test_failures_combine():
    ctx = make_ctx()
    ctx.discovery.classes = [ClassInfo(EX + "A", 1, True)]
    client = FakeClient({vocab.ONTOLOGIES_STEP: timeout(), vocab.LABELS_STEP: select([])})
    result = vocab.run(client, ctx)
    assert result.status == "timeout"
    assert "ontology query failed" in result.message
