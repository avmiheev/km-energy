"""Verify the self-contained explicit RDF projection for both rev05 maps.

No external CXL file, old diagram or CmapTools installation is required.
This checks explicit nodes/results against the compact RDF; it does not test
CmapTools rendering or establish full OWL DL consistency.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from validate import A, EX, BASE, check_data, decimal, fixture, load_graphs, short, source_hashes
from rdflib import Graph
from rdflib.namespace import RDF, OWL
from rdflib.compare import isomorphic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-dir", type=Path)
    parser.parse_args()
    core, example, projection, shapes = load_graphs()
    data = example + projection
    checks = []

    def check(name, condition, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})

    check("rdfxml_turtle_isomorphic", isomorphic(core, Graph().parse(BASE / "analytics-core.owl", format="xml")))
    check("projection_does_not_redefine_compact_assertions", not any(p in (A.st, A.ce, A.status, A.category, A.weight)
          for _, p, _ in projection))
    check("all_66_explicit_map_nodes", len(set(projection.subjects(RDF.type, A.FactorNode))) == 44 and
          len(set(projection.subjects(RDF.type, A.IndicatorNode))) == 22)
    defined = {s for s in example.subjects(RDF.type, A.InfluenceAssessment) if example.value(s, A.st) is not None}
    for relation, result_class, compact in ((A.stResult, A.SensitivityIndex, A.st), (A.ceResult, A.DirectedEffect, A.ce)):
        links = set(projection.subject_objects(relation))
        results = set(projection.subjects(RDF.type, result_class))
        valid = len(links) == len(results) == 462 and {s for s, _ in links} == defined and {o for _, o in links} == results
        valid = valid and all(len(list(projection.objects(s, relation))) == 1 and
                              len(list(projection.subjects(relation, o))) == 1 and
                              projection.value(o, A.numericValue) == example.value(s, compact) for s, o in links)
        check(short(relation) + "_all_462_values_and_unique_owners", valid)
    for period, experiment, map_id, count in (("january", EX.italyExperiment, EX.demoMap, 20),
                                             ("july", EX.italyExperimentJuly, EX.julyMap, 16)):
        for cls, relation, representation, membership, experiment_property, expected in (
            (A.FactorNode, A.hasFactorNode, A.representsFactor, A.factorNodeMap, A.hasFactor, 22),
            (A.IndicatorNode, A.hasIndicatorNode, A.representsIndicator, A.indicatorNodeMap, A.hasIndicator, 11),
        ):
            nodes = set(projection.objects(map_id, relation))
            reverse_nodes = set(projection.subjects(membership, map_id))
            represented = {projection.value(node, representation) for node in nodes}
            check(period + "_" + short(cls), len(nodes) == expected and nodes == reverse_nodes and
                  all((node, RDF.type, cls) in projection for node in nodes) and
                  represented == set(example.objects(experiment, experiment_property)))
        edges = set(example.subjects(A.inMap, map_id))
        check(period + "_inverse_hasEdge", len(edges) == count and set(projection.objects(map_id, A.hasEdge)) == edges)
        check(period + "_explicit_endpoint_nodes_and_categories", all(
            (data.value(edge, A.sourceNode), A.representsFactor, example.value(edge, A.source)) in data and
            (data.value(edge, A.sourceNode), A.factorNodeMap, map_id) in data and
            (data.value(edge, A.targetNode), A.representsIndicator, example.value(edge, A.target)) in data and
            (data.value(edge, A.targetNode), A.indicatorNodeMap, map_id) in data and
            data.value(edge, A.edgeCategory) == example.value(example.value(edge, A.basedOn), A.category)
            for edge in edges))
    check("inverse_properties_declared", (A.hasEdge, OWL.inverseOf, A.inMap) in core or (A.inMap, OWL.inverseOf, A.hasEdge) in core)

    semantic_queries = []
    for path in sorted((BASE / "queries").glob("cq*.rq")):
        for period, experiment in (("january", "italyExperiment"), ("july", "italyExperimentJuly")):
            query = path.read_text(encoding="utf-8").replace("VALUES ?experiment { ex:italyExperiment }", "VALUES ?experiment { ex:" + experiment + " }")
            if period == "july":
                query = query.replace("VALUES ?map { ex:demoMap }", "VALUES ?map { ex:julyMap }")
                query = query.replace("VALUES ?report { ex:demoReport }", "VALUES ?report { ex:julyReport }")
            compact = sorted(tuple(str(v) if v is not None else None for v in row) for row in (core + example).query(query))
            explicit = sorted(tuple(str(v) if v is not None else None for v in row) for row in (core + data).query(query))
            item = {"file": path.name, "period": period, "rows": len(explicit), "passed": compact == explicit}
            semantic_queries.append(item)
    check("all_cq_answers_preserved_by_explicit_projection", all(item["passed"] for item in semantic_queries))

    # Small valid projection, then independent corruptions of its six links.
    tiny = fixture([("sample", "0.8", "0.5")], include_map=True, projection=True)
    for triple in (
        (EX.factorNode, RDF.type, A.FactorNode), (EX.factorNode, A.representsFactor, EX.sampleFactor),
        (EX.factorNode, A.factorNodeMap, EX.demoMap), (EX.indicatorNode, RDF.type, A.IndicatorNode),
        (EX.indicatorNode, A.representsIndicator, EX.sampleIndicator), (EX.indicatorNode, A.indicatorNodeMap, EX.demoMap),
        (EX.edge_sample, A.sourceNode, EX.factorNode), (EX.edge_sample, A.targetNode, EX.indicatorNode),
        (EX.edge_sample, A.edgeCategory, A.Critical),
    ):
        tiny.add(triple)
    baseline, _ = check_data(core, tiny, shapes)
    check("synthetic_projection_baseline_valid", baseline["conforms"])
    negative = []
    for name, subject, predicate, value in (
        ("wrong_source_node", EX.edge_sample, A.sourceNode, EX.indicatorNode),
        ("wrong_target_node", EX.edge_sample, A.targetNode, EX.factorNode),
        ("wrong_node_map", EX.factorNode, A.factorNodeMap, EX.otherMap),
        ("mismatched_st_result", EX.sampleST, A.numericValue, decimal("0.1")),
        ("mismatched_ce_result", EX.sampleCE, A.numericValue, decimal("-0.5")),
        ("wrong_edge_category", EX.edge_sample, A.edgeCategory, A.Background),
    ):
        altered = Graph() + tiny
        altered.set((subject, predicate, value))
        result, _ = check_data(core, altered, shapes)
        negative.append({"name": name, "passed": not result["conforms"], "violation_count": result["validation_result_count"]})
    check("all_projection_negative_tests_detected", all(item["passed"] for item in negative))
    check("no_placeholder_namespace_in_active_rdf", all("example.org" not in p.read_text(encoding="utf-8") for p in
          [BASE / "analytics-core.ttl", BASE / "analytics-core.owl", BASE / "article-example.ttl", BASE / "cxl-example.ttl"]))
    passed = all(item["passed"] for item in checks)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "all_checks_passed": passed,
        "scope": "Self-contained explicit RDF nodes/results and compact-projection equivalence for both rev05 maps; synthetic SHACL negative tests. Full-data SHACL is recorded by validate.py. No external CXL/CmapTools validation, OWL DL consistency proof or scientific recomputation.",
        "projection_triples": len(projection), "checks": checks, "negative_tests": negative,
        "competency_queries": semantic_queries, "sha256": source_hashes(),
    }
    (BASE / "alignment-validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"all_checks_passed": passed, "checks": len(checks), "negative_tests": len(negative),
                      "failed_checks": [c for c in checks if not c["passed"]]}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
