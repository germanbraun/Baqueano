"""Step 8: links between classes, derived from the profiles (no queries).

Every property whose type-checked objects have a class defines an edge
    source class --property--> target class
with support = support(property) * share of checked objects of that class,
i.e. an estimate of the fraction of sampled subjects linking to that class.
"""

from __future__ import annotations

from baqueano import model
from baqueano.context import Context
from baqueano.model import ClassProfile, Link, StepResult
from baqueano.profiling import RDF_TYPE

NAME = "links"


def links_from_profiles(profiles: list[ClassProfile], class_property: str = RDF_TYPE) -> list[Link]:
    """All class-to-class links, strongest first (pure). The class property itself is not a link."""
    links = []
    for prof in profiles:
        for pp in prof.properties:
            if pp.path == class_property or pp.objects_checked == 0:
                continue
            for target, n in pp.target_classes.items():
                support = round(pp.support * n / pp.objects_checked, 4)
                links.append(Link(prof.class_iri, pp.path, target, support))
    links.sort(key=lambda link: (-link.support, link.source_class, link.path, link.target_class))
    return links


def run(client, ctx: Context) -> StepResult:
    ctx.discovery.links = links_from_profiles(ctx.discovery.profiles, ctx.discovery.class_property)
    n_classes = len({link.source_class for link in ctx.discovery.links} |
                    {link.target_class for link in ctx.discovery.links})
    return StepResult(NAME, model.OK, f"{len(ctx.discovery.links)} link(s) between {n_classes} classes")
