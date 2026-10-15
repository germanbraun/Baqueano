from baqueano.generate import diagram, thresholds as th
from baqueano.model import ClassInfo, ClassProfile, Link
from tests.sample_discovery import PERSON, PLACE, S, sample_discovery


def test_diagram_content():
    text = diagram.render(sample_discovery())
    lines = text.splitlines()
    assert "classDiagram" in lines
    assert '  class Person["schema:Person"]' in lines
    assert '  class Place["schema:Place"]' in lines
    assert "  Person : +string name" in lines
    assert "  Person : +date birthDate" in lines
    assert "  Person : +langString nick" in lines
    assert not any("faxNumber" in line for line in lines)      # below DIAGRAM_MIN_SUPPORT
    assert not any("Person : +" in line and "knows" in line for line in lines)  # IRIs are edges
    assert "  Person --> Place : birthPlace" in lines
    assert "  Person --> Person : knows" in lines
    assert "  Place --> Place : containedInPlace" in lines


def test_class_cap_and_edges_between_shown_classes_only():
    d = sample_discovery()
    extra = [f"http://ex/C{i}" for i in range(20)]
    d.classes += [ClassInfo(c, 1, True) for c in extra]
    d.profiles += [ClassProfile(c, 1, "first-n", False, None) for c in extra]
    d.links.append(Link(PERSON, S + "likes", extra[-1], 0.5))
    text = diagram.render(d)
    assert text.count("  class ") == th.DIAGRAM_MAX_CLASSES
    assert "likes" not in text            # C19 is not among the 15 shown


def test_unknown_namespace_and_duplicate_local_names():
    d = sample_discovery()
    d.profiles.append(ClassProfile("http://other.org/Person", 1, "first-n", False, None))
    text = diagram.render(d)
    assert '  class Person_2["http://other.org/Person"]' in text


def test_empty():
    d = sample_discovery()
    d.profiles, d.links = [], []
    assert "%% no profiled classes" in diagram.render(d)


def test_weak_links_hidden():
    d = sample_discovery()
    d.links = [Link(PERSON, S + "knows", PLACE, th.DIAGRAM_MIN_SUPPORT - 0.01)]
    assert "-->" not in diagram.render(d)
