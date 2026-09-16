"""Run the six competency queries against local ontology and example files.

Usage from the repository root: python ontology/queries/run_queries.py
No network access, OWL inference, or scientific model calculation is performed.
"""
import json
import sys
from pathlib import Path

from rdflib import Graph


def main():
    base = Path(__file__).resolve().parent
    graph = Graph()
    for filename in ("analytics-core.ttl", "article-example.ttl"):
        graph.parse(base.parent / filename, format="turtle")
    results = {}
    for path in sorted(base.glob("cq*.rq")):
        result = graph.query(path.read_text(encoding="utf-8"))
        variables = [str(variable) for variable in result.vars]
        rows = [
            {name: None if row[i] is None else row[i].n3()
             for i, name in enumerate(variables)}
            for row in result
        ]
        results[path.name] = {
            "variables": variables, "row_count": len(rows), "rows": rows,
        }
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
