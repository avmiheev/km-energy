"""Offline rev05 RDF, SHACL and query checks; the scientific model is not rerun.

Usage: python validate.py [--dependency-dir PATH]
Boundary/negative fixtures are synthetic, small and kept in memory only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent
# This option also permits an offline package directory without installation.
if "--dependency-dir" in sys.argv:
    sys.path.insert(0, str(Path(sys.argv[sys.argv.index("--dependency-dir") + 1]).resolve()))

from rdflib import Graph, Literal, Namespace
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, XSD
from pyshacl import validate

A = Namespace("https://w3id.org/km-energy/ontology#")
EX = Namespace("https://w3id.org/km-energy/example#")
SH = Namespace("http://www.w3.org/ns/shacl#")
D = Decimal


def decimal(value):
    return Literal(str(value), datatype=XSD.decimal)


def short(value):
    if value is None:
        return None
    for prefix, namespace in (("a:", A), ("ex:", EX), ("sh:", SH)):
        if str(value).startswith(str(namespace)):
            return prefix + str(value)[len(str(namespace)):]
    return str(value)


def load_graphs():
    core = Graph().parse(BASE / "analytics-core.ttl", format="turtle")
    example = Graph().parse(BASE / "article-example.ttl", format="turtle")
    projection = Graph().parse(BASE / "cxl-example.ttl", format="turtle")
    shapes = Graph().parse(BASE / "constraints.ttl", format="turtle")
    shapes.parse(BASE / "alignment-shapes.ttl", format="turtle")
    return core, example, projection, shapes


def check_data(core, data, shapes, *, meta=False):
    conforms, report, _ = validate(
        core + data, shacl_graph=shapes, inference="none", meta_shacl=meta,
        advanced=False, abort_on_first=False, allow_infos=False,
        allow_warnings=False, do_owl_imports=False,
    )
    if not isinstance(report, Graph):
        raise RuntimeError(str(report))
    details = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        details.append({
            "focus": short(report.value(result, SH.focusNode)),
            "path": short(report.value(result, SH.resultPath)),
            "component": short(report.value(result, SH.sourceConstraintComponent)),
            "messages": sorted(str(m) for m in report.objects(result, SH.resultMessage)),
        })
    details.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    return {"conforms": bool(conforms), "validation_result_count": len(details), "details": details}, report


def classify(st, ce):
    """Independent decimal implementation of rev05, including No_ST priority."""
    if st is None or ce is None:
        return "undefined", None
    st, ce = D(str(st)), abs(D(str(ce)))
    if st <= 0 and ce >= D("0.1"):
        return "No_ST", None
    if st >= D("0.7") and ce >= D("0.3"):
        category = "Critical"
    elif 0 < st < D("0.3") and ce >= D("0.3"):
        category = "StrongLowST"
    elif st >= D("0.7") and ce < D("0.3"):
        category = "Uncertainty"
    elif st < D("0.7") and ce < D("0.1"):
        category = "Background"
    else:
        category = "Moderate"
    return "reported", A[category]


def selected(st, ce, status):
    return (status in ("reported", "complete") and st is not None and ce is not None
            and D(str(st)) > D("0.1") and abs(D(str(ce))) > D("0.3"))


def fixture(cases, *, include_map=False, projection=False):
    """Each case is (id, ST, CE); these are not observations from the article."""
    g = Graph()
    for triple in (
        (EX.model, RDF.type, A.OptimizationModel),
        (EX.italyExperiment, RDF.type, A.Experiment),
        (EX.italyExperiment, A.usesModel, EX.model),
        (EX.dataset, RDF.type, A.Dataset),
        (EX.dataset, A.datasetExperiment, EX.italyExperiment),
        (EX.table1Rule, RDF.type, A.ClassificationRule),
        (EX.table1Rule, A.ruleVersion, Literal("rev05-synthetic-fixture")),
    ):
        g.add(triple)
    for prop, value in ((A.stLow, "0.3"), (A.stHigh, "0.7"), (A.ceLow, "0.1"), (A.ceStrong, "0.3")):
        g.add((EX.table1Rule, prop, decimal(value)))
    if include_map:
        for prop, value in ((RDF.type, A.CognitiveMap), (A.mapExperiment, EX.italyExperiment),
                            (A.mapRule, EX.table1Rule), (A.tauST, decimal("0.1")),
                            (A.tauCE, decimal("0.3")), (A.selectionOperator, Literal(">"))):
            g.add((EX.demoMap, prop, value))
    for name, st, ce in cases:
        subject, factor, indicator = EX[name], EX[name + "Factor"], EX[name + "Indicator"]
        status, category = classify(st, ce)
        for triple in ((factor, RDF.type, A.AnalyticalFactor), (indicator, RDF.type, A.OutputIndicator),
                       (EX.italyExperiment, A.hasFactor, factor), (EX.italyExperiment, A.hasIndicator, indicator)):
            g.add(triple)
        for prop, value in ((RDF.type, A.InfluenceAssessment), (A.experiment, EX.italyExperiment),
                            (A.dataset, EX.dataset), (A.factor, factor), (A.indicator, indicator),
                            (A.rule, EX.table1Rule), (A.status, Literal(status))):
            g.add((subject, prop, value))
        if st is not None and ce is not None:
            g.add((subject, RDF.type, A.ReportedAssessment))
            g.add((subject, A.st, decimal(st)))
            g.add((subject, A.ce, decimal(ce)))
            g.add((subject, A.sourceLocator, Literal("In-memory synthetic fixture; not article data")))
            g.add((subject, A.evidenceNote, Literal("Constraint test only")))
        if category:
            g.add((subject, A.category, category))
        if include_map:
            g.add((EX.demoMap, A.candidateAssessment, subject))
            if selected(st, ce, status):
                add_edge(g, EX["edge_" + name], subject)
        if projection and st is not None and ce is not None:
            for prop, result_class, suffix, value in ((A.stResult, A.SensitivityIndex, "ST", st),
                                                      (A.ceResult, A.DirectedEffect, "CE", ce)):
                g.add((subject, prop, EX[name + suffix]))
                g.add((EX[name + suffix], RDF.type, result_class))
                g.add((EX[name + suffix], A.numericValue, decimal(value)))
    return g


def add_edge(g, edge, assessment):
    for prop, value in ((RDF.type, A.MapEdge), (A.inMap, EX.demoMap), (A.basedOn, assessment),
                        (A.source, g.value(assessment, A.factor)), (A.target, g.value(assessment, A.indicator)),
                        (A.weight, g.value(assessment, A.ce))):
        g.add((edge, prop, value))


def source_hashes():
    paths = [p for pattern in ("*.ttl", "*.owl", "*.py", "requirements.txt", "*.csv") for p in BASE.glob(pattern)]
    paths = [p for p in paths if p.name != "validation-report.ttl"]
    paths += [BASE / "source-manifest.json"] if (BASE / "source-manifest.json").exists() else []
    paths += sorted(p for p in (BASE / "data").rglob("*") if p.is_file())
    paths += sorted((BASE / "queries").glob("*.rq"))
    return {str(p.relative_to(BASE)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-dir", type=Path)
    parser.parse_args()
    core, example, projection, shapes = load_graphs()
    xml_core = Graph().parse(BASE / "analytics-core.owl", format="xml")
    data = example + projection
    base_validation, report = check_data(core, data, shapes, meta=True)
    report.serialize(BASE / "validation-report.ttl", format="turtle")
    checks = []

    def check(name, condition, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})

    check("rdfxml_turtle_isomorphic", isomorphic(core, xml_core))
    check("all_article_and_projection_shacl", base_validation["conforms"])
    assessments = set(example.subjects(RDF.type, A.InfluenceAssessment))
    check("484_assessments", len(assessments) == 484, len(assessments))
    statuses = Counter(str(example.value(s, A.status)) for s in assessments)
    check("status_counts", statuses == {"reported": 455, "No_ST": 7, "undefined": 22}, dict(statuses))
    check("462_reported_profile_no_complete", len(set(example.subjects(RDF.type, A.ReportedAssessment))) == 462
          and not list(example.subjects(RDF.type, A.CompleteAssessment)))
    check("rev05_rule_thresholds", all(example.value(EX.table1Rule, p) == decimal(v) for p, v in
          ((A.stLow, "0.3"), (A.stHigh, "0.7"), (A.ceLow, "0.1"), (A.ceStrong, "0.3"))))
    mismatches = []
    diagnostics = []
    for subject in sorted(assessments):
        st, ce = example.value(subject, A.st), example.value(subject, A.ce)
        status, category = classify(st, ce)
        if str(example.value(subject, A.status)) != status or example.value(subject, A.category) != category:
            mismatches.append(short(subject))
        if st is not None and (D(str(st)) < 0 or D(str(st)) > 1):
            diagnostics.append({"assessment": short(subject), "st": str(st)})
    check("all_classifications_match_rev05", not mismatches, mismatches)
    maps = {}
    for period, experiment, map_id, report_id, expected_edges in (
        ("january", EX.italyExperiment, EX.demoMap, EX.demoReport, 20),
        ("july", EX.italyExperimentJuly, EX.julyMap, EX.julyReport, 16),
    ):
        candidates = set(example.objects(map_id, A.candidateAssessment))
        report_assessments = set(example.objects(report_id, A.reportAssessment))
        expected = {s for s in assessments if example.value(s, A.experiment) == experiment}
        check(period + "_242_candidates_and_report", len(expected) == 242 and candidates == expected == report_assessments)
        pairs = {(example.value(s, A.factor), example.value(s, A.indicator)) for s in expected}
        check(period + "_22_by_11_unique_pairs", len(pairs) == 242 and
              len(set(example.objects(experiment, A.hasFactor))) == 22 and
              len(set(example.objects(experiment, A.hasIndicator))) == 11)
        desired = {s for s in expected if selected(example.value(s, A.st), example.value(s, A.ce), str(example.value(s, A.status)))}
        edges = set(example.subjects(A.inMap, map_id))
        actual = {example.value(edge, A.basedOn) for edge in edges}
        check(period + "_exact_edge_selection", actual == desired and len(edges) == len(desired) == expected_edges)
        check(period + "_strict_filter_parameters", example.value(map_id, A.tauST) == decimal("0.1") and
              example.value(map_id, A.tauCE) == decimal("0.3") and str(example.value(map_id, A.selectionOperator)) == ">")
        maps[period] = {(example.value(s, A.factor), example.value(s, A.indicator)) for s in desired}
    check("11_common_edge_pairs", len(maps["january"] & maps["july"]) == 11, len(maps["january"] & maps["july"]))

    boundary_cases = [
        ("criticalEqual", "0.7", "0.3"), ("criticalNegative", "0.7", "-0.3"),
        ("uncertaintyBelow", "0.7", "0.2999"), ("strongBelow", "0.2999", "-0.3"),
        ("moderateEqual", "0.3", "0.3"), ("backgroundBelow", "0.6999", "0.0999"),
        ("moderateLowEqual", "0.6999", "0.1"), ("noSTEqual", "0", "-0.1"),
        ("negativeNoST", "-0.01", "0.3"), ("negativeBackground", "-0.01", "0.0999"),
        ("aboveOne", "1.2", "0.1"), ("undefinedFixture", None, None),
        ("equalST", "0.1", "0.8"), ("equalCE", "0.8", "0.3"),
        ("equalNegativeCE", "0.8", "-0.3"), ("justAbove", "0.1001", "-0.3001"),
    ]
    boundary = fixture(boundary_cases, include_map=True)
    expected_boundaries = {
        "criticalEqual": ("reported", A.Critical), "criticalNegative": ("reported", A.Critical),
        "uncertaintyBelow": ("reported", A.Uncertainty), "strongBelow": ("reported", A.StrongLowST),
        "moderateEqual": ("reported", A.Moderate), "backgroundBelow": ("reported", A.Background),
        "moderateLowEqual": ("reported", A.Moderate), "noSTEqual": ("No_ST", None),
        "negativeNoST": ("No_ST", None), "negativeBackground": ("reported", A.Background),
        "aboveOne": ("reported", A.Uncertainty), "undefinedFixture": ("undefined", None),
        "equalST": ("reported", A.StrongLowST), "equalCE": ("reported", A.Critical),
        "equalNegativeCE": ("reported", A.Critical), "justAbove": ("reported", A.StrongLowST),
    }
    check("decimal_classifier_explicit_boundary_expectations", all(
        classify(st, ce) == expected_boundaries[name] for name, st, ce in boundary_cases))
    boundary_validation, _ = check_data(core, boundary, shapes)
    check("synthetic_boundaries_shacl", boundary_validation["conforms"], len(boundary_cases))
    cq5 = list((core + boundary).query((BASE / "queries/cq5_classification.rq").read_text(encoding="utf-8")))
    check("cq5_all_boundary_statuses_and_categories", len(cq5) == len(boundary_cases) and
          all(bool(row.asdict().get("matches", False).toPython()) for row in cq5))
    cq4 = list((core + boundary).query((BASE / "queries/cq4_selected_edges.rq").read_text(encoding="utf-8")))
    desired_boundary = {EX[name] for name, st, ce in boundary_cases if selected(st, ce, classify(st, ce)[0])}
    check("cq4_exact_strict_boundary_selection", {row.asdict()["assessment"] for row in cq4} == desired_boundary)

    # Each mutation runs against one tiny valid fixture, never all 484 observations.
    tiny = fixture([("sample", "0.8", "0.5")], include_map=True, projection=True)
    tiny_validation, _ = check_data(core, tiny, shapes)
    check("negative_fixture_initially_valid", tiny_validation["conforms"])
    negative_tests = []

    def negative(name, mutation, *, graph=tiny, path=None, message=None):
        altered = Graph() + graph
        mutation(altered)
        result, _ = check_data(core, altered, shapes)
        expected = any((path is None or d["path"] == path) and
                       (message is None or any(message in m for m in d["messages"])) for d in result["details"])
        negative_tests.append({"name": name, "passed": not result["conforms"] and expected, **result})

    negative("missing_factor", lambda g: g.remove((EX.sample, A.factor, None)), path="a:factor")
    negative("duplicate_ce", lambda g: g.add((EX.sample, A.ce, decimal("0.6"))), path="a:ce")
    negative("wrong_weight", lambda g: g.set((EX.edge_sample, A.weight, decimal("-0.5"))), message="Источник, цель и вес")
    negative("wrong_category", lambda g: g.set((EX.sample, A.category, A.Background)), message="Сохранённая категория")
    negative("missing_selected_edge", lambda g: g.remove((EX.edge_sample, None, None)), message="отсутствует ребро")
    negative("duplicate_selected_edge", lambda g: add_edge(g, EX.duplicateEdge, EX.sample), message="двумя разными")
    negative("untyped_edge", lambda g: g.remove((EX.edge_sample, RDF.type, A.MapEdge)))
    negative("failed_status_edge", lambda g: g.set((EX.sample, A.status, Literal("failed"))))
    negative("unknown_passport_not_complete", lambda g: g.add((EX.sample, RDF.type, A.CompleteAssessment)), path="a:estimation")
    negative("nonfinite_ce", lambda g: g.set((EX.sample, A.ce, Literal("NaN", datatype=XSD.double))), path="a:ce")
    negative("metric_projection_mismatch", lambda g: g.set((EX.sampleST, A.numericValue, decimal("0.1"))), message="Явный результат ST")
    negative("undefined_with_st", lambda g: g.add((EX.undefinedFixture, A.st, decimal("0"))), graph=boundary, message="Статус undefined")
    negative("no_st_with_category", lambda g: g.add((EX.noSTEqual, A.category, A.Moderate)), graph=boundary, message="Статус No_ST")
    negative("equality_not_selected", lambda g: add_edge(g, EX.invalidEdge, EX.equalST), graph=boundary, message="не проходит строгое условие")
    negative("wrong_map_context", lambda g: g.set((EX.demoMap, A.mapExperiment, EX.otherExperiment)), message="Каждый кандидат карты")
    negative("wrong_dataset_context", lambda g: g.set((EX.dataset, A.datasetExperiment, EX.otherExperiment)), message="Оценка и её набор данных")
    check("all_negative_tests_detected", all(t["passed"] for t in negative_tests), len(negative_tests))

    # Failed estimates remain candidates/reportable, but cannot become map edges.
    failed = Graph() + tiny
    failed.set((EX.sample, A.status, Literal("failed")))
    failed.remove((EX.edge_sample, None, None))
    failed_validation, _ = check_data(core, failed, shapes)
    check("failed_candidate_without_edge_is_valid", failed_validation["conforms"])
    requirements = dict(line.split("==", 1) for line in (BASE / "requirements.txt").read_text().splitlines() if "==" in line)
    versions = {name: importlib.metadata.version(name) for name in requirements}
    check("versions_match_requirements", versions == requirements, versions)
    passed = all(item["passed"] for item in checks)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "all_checks_passed": passed,
        "scope": "Offline RDF syntax/isomorphism, complete rev05 example plus explicit projection, SHACL and synthetic query boundaries. No full OWL DL consistency proof or scientific recomputation.",
        "python": platform.python_version(), "package_versions": versions,
        "ontology_triples": len(core), "example_triples": len(example), "projection_triples": len(projection),
        "base_validation": base_validation, "checks": checks, "negative_tests": negative_tests,
        "synthetic_boundary_validation": boundary_validation,
        "out_of_range_st": {"count": len(diagnostics), "diagnostics": diagnostics,
                            "note": "Raw finite estimates are retained without clipping. This diagnostic is separate from SHACL validity."},
        "sha256": source_hashes(),
    }
    (BASE / "validation-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"all_checks_passed": passed, "checks": len(checks), "negative_tests": len(negative_tests),
                      "base_conforms": base_validation["conforms"], "failed_checks": [c for c in checks if not c["passed"]]}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
