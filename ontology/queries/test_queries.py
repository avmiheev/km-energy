"""Boundary and regression-check tests using explicit synthetic RDF fixtures."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import XSD

import run_queries

A = Namespace("https://w3id.org/km-energy/ontology#")
EX = run_queries.EX


def rule_graph():
    graph = Graph()
    for predicate, value in ((A.stLow, "0.3"), (A.stHigh, "0.7"),
                             (A.ceLow, "0.1"), (A.ceStrong, "0.3")):
        graph.add((EX.table1Rule, predicate, Literal(value, datatype=XSD.decimal)))
    return graph


def add_assessment(graph, name, st, ce, status, category=None, experiment=EX.italyExperiment):
    assessment = EX[name]
    graph.add((assessment, A.experiment, experiment))
    graph.add((assessment, A.rule, EX.table1Rule))
    if status is not None:
        graph.add((assessment, A.status, Literal(status)))
    for predicate, value in ((A.st, st), (A.ce, ce)):
        if value is not None:
            graph.add((assessment, predicate, Literal(value, datatype=XSD.decimal)))
    if category is not None:
        graph.add((assessment, A.category, A[category]))
    return assessment


class ClassificationTests(unittest.TestCase):
    def test_boundaries_statuses_and_missing_values(self):
        # These values are synthetic tests of table 1, not scientific observations.
        cases = [
            ("critical_at_both_bounds", "0.7", "0.3", "reported", "Critical", "Critical", True),
            ("critical_negative_ce", "0.7", "-0.3", "reported", "Critical", "Critical", True),
            ("strong_below_st_low", "0.299999", "0.3", "reported", "StrongLowST", "StrongLowST", True),
            ("moderate_at_st_low", "0.3", "0.3", "reported", "Moderate", "Moderate", True),
            ("moderate_below_st_high", "0.699999", "0.3", "reported", "Moderate", "Moderate", True),
            ("uncertainty_below_ce_strong", "0.7", "0.299999", "reported", "Uncertainty", "Uncertainty", True),
            ("uncertainty_at_ce_low", "0.7", "0.1", "reported", "Uncertainty", "Uncertainty", True),
            ("background_below_both", "0.699999", "0.099999", "reported", "Background", "Background", True),
            ("moderate_at_ce_low", "0.3", "0.1", "reported", "Moderate", "Moderate", True),
            ("nost_at_zero", "0", "0.1", "No_ST", None, None, True),
            ("nost_negative_st", "-0.001", "-0.3", "No_ST", None, None, True),
            ("background_zero_st_small_ce", "0", "0.099999", "reported", "Background", "Background", True),
            ("undefined", None, None, "undefined", None, None, True),
            ("partial_is_invalid", "0.2", None, "undefined", None, None, False),
            ("nost_category_is_invalid", "0", "0.1", "No_ST", "Moderate", None, False),
            ("undefined_category_is_invalid", None, None, "undefined", "Background", None, False),
            ("defined_status_is_wrong", "0.7", "0.3", "undefined", "Critical", "Critical", False),
            ("reported_category_is_missing", "0.7", "0.3", "reported", None, "Critical", False),
            ("status_is_missing", "0.7", "0.3", None, "Critical", "Critical", False),
        ]
        graph = rule_graph()
        for name, st, ce, status, category, _, _ in cases:
            add_assessment(graph, name, st, ce, status, category)
        query = (run_queries.BASE / "cq5_classification.rq").read_text(encoding="utf-8")
        rows = {str(row.assessment).split("#")[-1]: row for row in graph.query(query)}
        self.assertEqual(len(rows), len(cases), "No_ST and missing estimates must not vanish")
        for name, _, _, _, _, computed, matches in cases:
            with self.subTest(name=name):
                row = rows[name]
                self.assertEqual(row.computed, A[computed] if computed else None)
                self.assertEqual(row.matches.toPython(), matches)
        self.assertEqual(str(rows["nost_at_zero"].computedStatus), "No_ST")
        self.assertEqual(str(rows["undefined"].computedStatus), "undefined")

    def test_strict_map_thresholds_and_signed_weights(self):
        graph = rule_graph()
        for predicate, value in ((A.mapExperiment, EX.italyExperiment),
                                 (A.mapRule, EX.table1Rule),
                                 (A.tauST, Literal("0.1", datatype=XSD.decimal)),
                                 (A.tauCE, Literal("0.3", datatype=XSD.decimal)),
                                 (A.selectionOperator, Literal(">"))):
            graph.add((EX.demoMap, predicate, value))
        cases = [
            ("st_equal", "0.1", "0.31", "reported", False),
            ("ce_equal", "0.100001", "0.3", "reported", False),
            ("negative_ce_equal", "0.100001", "-0.3", "reported", False),
            ("negative_selected", "0.100001", "-0.300001", "reported", True),
            ("positive_selected", "0.100001", "0.300001", "reported", True),
            ("status_excluded", "0.2", "0.5", "No_ST", False),
            ("missing_excluded", None, None, "undefined", False),
        ]
        for name, st, ce, status, _ in cases:
            assessment = add_assessment(graph, name, st, ce, status)
            graph.add((EX.demoMap, A.candidateAssessment, assessment))
            graph.add((assessment, A.factor, EX.market_price))
            graph.add((assessment, A.indicator, EX.profit_eur))
        query = (run_queries.BASE / "cq4_selected_edges.rq").read_text(encoding="utf-8")
        rows = {str(row.assessment).split("#")[-1]: row for row in graph.query(query)}
        self.assertEqual(set(rows), {name for name, _, _, _, selected in cases if selected})
        self.assertLess(rows["negative_selected"].weight.toPython(), 0)
        self.assertIsNone(rows["positive_selected"].actualEdge, "Suitable candidates remain visible if an edge is missing")

    def test_period_parameter_selects_july_only(self):
        graph = rule_graph()
        add_assessment(graph, "jan", "0.7", "0.3", "reported", "Critical")
        add_assessment(graph, "jul", None, None, "undefined", experiment=EX.italyExperimentJuly)
        query = (run_queries.BASE / "cq5_classification.rq").read_text(encoding="utf-8")
        rows = list(graph.query(run_queries.query_for_period(query, "july")))
        self.assertEqual([row.assessment for row in rows], [EX.jul])
        for path in run_queries.BASE.glob("cq*.rq"):
            with self.subTest(query=path.name):
                converted = run_queries.query_for_period(path.read_text(encoding="utf-8"), "july")
                self.assertTrue(any(value.n3() in converted for value in run_queries.PERIODS["july"].values()))


class ReferenceCheckTests(unittest.TestCase):
    def test_check_mismatch_fails_and_does_not_overwrite_reference(self):
        sample = {"schema_version": 2, "periods": {"january": {
            "cq1_factors.rq": {"variables": ["factor"], "row_count": 1,
                               "rows": [{"factor": EX.market_price.n3()}]}}}}
        changed = copy.deepcopy(sample)
        changed["periods"]["january"]["cq1_factors.rq"]["rows"][0]["factor"] = EX.other.n3()
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference.json"
            reference.write_text(json.dumps(sample), encoding="utf-8")
            before = reference.read_bytes()
            with patch.object(run_queries, "run_queries", return_value=sample):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run_queries.main(["--period", "january", "--check", "--expected", str(reference)]), 0)
            with patch.object(run_queries, "run_queries", return_value=changed):
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(run_queries.main(["--period", "january", "--check", "--expected", str(reference)]), 1)
                self.assertIn("row 1 differs", errors.getvalue())
            self.assertEqual(reference.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
