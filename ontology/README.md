# KM Energy ontology

Conceptual ontology of the analytical workflow for causal-cognitive analysis of energy-system optimization results.

- [Turtle](analytics-core.ttl)
- [OWL / RDF/XML](analytics-core.owl)
- [Example instances](article-example.ttl)
- [Explicit graph nodes and metric results](cxl-example.ttl), to be loaded together with `article-example.ttl`.
- [Six SPARQL competency queries](queries/README.md), with the question-to-query mapping, execution instructions and expected results.

Version 0.2.0 contains 38 named classes and 82 object properties. The corresponding conceptual map covers 34 classes and 55 relations; the remaining terms describe metadata, technical profiles and additional links. The RDF/XML and Turtle files represent the same RDF graph (945 triples).

Ontology IRI: `https://w3id.org/km-energy/ontology`.
Term namespace: `https://w3id.org/km-energy/ontology#`.
Example namespace: `https://w3id.org/km-energy/example#`.

The w3id registration request is [pull request #6703](https://github.com/perma-id/w3id.org/pull/6703); its current status is available there. This working version is not a frozen article release and has no assigned DOI.

The example reproduces five rounded pairs from the manuscript revision rev01. It illustrates the representation and queries; it does not provide raw scenario data or reproduce the new January/July calculations. Ontology validation does not establish the validity of causal assumptions.

## Running the SPARQL examples

Load `analytics-core.ttl` and `article-example.ttl` into one default graph. No OWL inference, remote SPARQL endpoint or resolution of w3id IRIs is required. From the repository root:

```sh
python -m pip install rdflib==7.6.0 pyparsing==3.3.2
python ontology/queries/run_queries.py
```

The six queries return 2, 2, 2, 4, 5 and 5 rows respectively. See [queries/README.md](queries/README.md) for the six questions, parameters and interpretation, and [expected-results.json](queries/expected-results.json) for all returned RDF terms. The queries retrieve, rank and classify stored estimates; they do not recompute sensitivity indices or directed effects.

Maintainer: [Alexey Mikheev](https://github.com/avmiheev).
