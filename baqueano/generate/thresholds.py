"""Every threshold the generators apply, in one place to tune and test."""

# SHACL shape inference (shares are fractions of the sample).
PROPERTY_MIN_SUPPORT = 0.05   # property included in the shape
MIN_COUNT_SUPPORT = 0.95      # sh:minCount 1
DATATYPE_SHARE = 0.95         # one datatype covers this share of the literals -> sh:datatype
CLASS_SHARE = 0.95            # one class covers this share of the checked IRI objects -> sh:class
KIND_SHARE = 0.95             # literals (or IRIs) must be this share of all objects for the above

# Starter queries.
TABLE_MAX_COLUMNS = 8         # properties in 12-<class>-table.rq
LINK_MIN_SUPPORT = 0.05       # links that get a 20-<A>-to-<B>.rq
MAX_LINK_QUERIES = 20
QUERY_LIMIT = 100

# Diagram.
DIAGRAM_MAX_CLASSES = 15
DIAGRAM_MIN_SUPPORT = 0.05    # attributes and edges shown
DIAGRAM_MAX_ATTRIBUTES = 12
