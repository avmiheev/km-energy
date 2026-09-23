"""Execute and check competency queries against the two local article periods.

This checks RDF query results, not the scientific estimates or causal assumptions.
The checked-in reference is only changed with the explicit --write-expected flag.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from rdflib import Graph, Namespace

BASE = Path(__file__).resolve().parent
EX = Namespace("https://w3id.org/km-energy/example#")
PERIODS = {
    "january": {"experiment": EX.italyExperiment, "map": EX.demoMap, "report": EX.demoReport},
    "july": {"experiment": EX.italyExperimentJuly, "map": EX.julyMap, "report": EX.julyReport},
}
DEFAULTS = {"experiment": "italyExperiment", "map": "demoMap", "report": "demoReport"}


def query_for_period(query, period):
    """Replace only the documented resource VALUES, keeping indicator/rule logic."""
    substitutions = 0
    for variable, default in DEFAULTS.items():
        pattern = rf"(VALUES\s+\?{variable}\s*\{{\s*)ex:{default}(\s*\}})"
        query, count = re.subn(
            pattern,
            lambda match: match[1] + PERIODS[period][variable].n3() + match[2],
            query,
        )
        substitutions += count
    if substitutions != 1:
        raise ValueError(f"Expected one period resource VALUES, found {substitutions}")
    return query


def run_queries(periods, graph=None):
    if graph is None:
        graph = Graph()
        for filename in ("analytics-core.ttl", "article-example.ttl"):
            graph.parse(BASE.parent / filename, format="turtle")
    results = {"schema_version": 2, "periods": {}}
    for period in periods:
        period_results = {}
        for path in sorted(BASE.glob("cq*.rq")):
            result = graph.query(query_for_period(path.read_text(encoding="utf-8"), period))
            variables = [str(variable) for variable in result.vars]
            rows = [
                {name: None if row[i] is None else row[i].n3()
                 for i, name in enumerate(variables)}
                for row in result
            ]
            period_results[path.name] = {
                "variables": variables, "row_count": len(rows), "rows": rows,
            }
        results["periods"][period] = period_results
    return results


def compare_results(actual, expected):
    """Return compact differences for selected periods; never update the reference."""
    errors = []
    if actual.get("schema_version") != expected.get("schema_version"):
        errors.append("Reference schema_version differs")
    for period, queries in actual["periods"].items():
        reference = expected.get("periods", {}).get(period)
        if reference is None:
            errors.append(f"{period}: no reference period")
            continue
        if set(queries) != set(reference):
            errors.append(f"{period}: query filenames differ")
        for name, result in queries.items():
            wanted = reference.get(name)
            if result != wanted:
                if wanted is None:
                    detail = "no reference query"
                elif result["variables"] != wanted.get("variables"):
                    detail = "selected variables differ"
                elif result["row_count"] != wanted.get("row_count"):
                    detail = f"row count {result['row_count']}, expected {wanted.get('row_count')}"
                else:
                    wanted_rows = wanted.get("rows", [])
                    different = next((i for i, row in enumerate(result["rows"])
                                      if i >= len(wanted_rows) or row != wanted_rows[i]), None)
                    detail = (f"row {different + 1} differs" if different is not None
                              else "reference structure differs")
                errors.append(f"{period}/{name}: {detail}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=("all", *PERIODS), default="all")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="compare with the saved reference, exit 1 on mismatch")
    mode.add_argument("--write-expected", action="store_true", help="explicitly replace the reference for both periods")
    parser.add_argument("--expected", type=Path, default=BASE / "expected-results.json")
    args = parser.parse_args(argv)
    if args.write_expected and args.period != "all":
        parser.error("--write-expected requires --period all to preserve both periods")
    periods = tuple(PERIODS) if args.period == "all" else (args.period,)
    results = run_queries(periods)
    if args.check:
        try:
            expected = json.loads(args.expected.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Cannot read reference: {exc}", file=sys.stderr)
            return 1
        errors = compare_results(results, expected)
        if errors:
            print("Reference check failed:\n" + "\n".join(errors), file=sys.stderr)
            return 1
        for period, queries in results["periods"].items():
            counts = ", ".join(str(result["row_count"]) for result in queries.values())
            print(f"{period}: CQ1-CQ6 match; rows {counts}")
        return 0
    output = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    if args.write_expected:
        args.expected.write_text(output, encoding="utf-8", newline="\n")
        print(f"Wrote reference for both periods: {args.expected}")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
