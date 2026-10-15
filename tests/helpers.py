from baqueano.context import Context, Settings
from baqueano.model import Discovery


def make_ctx(graph=None, void=None):
    discovery = Discovery(endpoint="http://example.org/sparql", started_at="now", void=void)
    return Context(discovery, Settings(graph=graph))
