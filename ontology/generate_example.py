#!/usr/bin/env python3
"""Rebuild the rev05 RDF example from the published decimal-preserving extract.

No statistical estimation is performed. Python's standard library is sufficient.
Use --source-dir only to import the two original run JSON files; normal operation
and --check are offline and need only files already in this directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNS = {
    "2013-01": ("jan", "italyExperiment", "scenarioDataset", "demoMap", "demoReport",
                "ce_2013-01_dowhy_a4ae95b6c5fb8ac2.json"),
    "2013-07": ("jul", "italyExperimentJuly", "scenarioDatasetJuly", "julyMap", "julyReport",
                "ce_2013-07_dowhy_ca3b781aa7162aef.json"),
}
FIELDS = ("month", "source", "target", "st", "ce_normalized", "excluded",
          "exclusion_reason", "source_file", "source_pair")
PREFIXES = """@prefix a: <https://w3id.org/km-energy/ontology#> .
@prefix ex: <https://w3id.org/km-energy/example#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

"""
CATEGORY_NAMES = ("Critical", "StrongLowST", "Uncertainty", "Background", "Moderate")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def number(value: str) -> str:
    # xsd:decimal has no exponent syntax. Conversion to fixed notation is exact;
    # the original JSON numeric spelling is retained in assessments.csv.
    return quoted(format(Decimal(value), "f")) + "^^xsd:decimal"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def import_sources(source_dir: Path, article: Path) -> None:
    rows = []
    metadata = {}
    sources = []
    for month, run in RUNS.items():
        source = source_dir / run[-1]
        raw = source.read_bytes()
        # parse_float=str preserves every digit, sign and exponent as written.
        document = json.loads(raw, parse_float=str, parse_int=str)
        if document["month"] != month:
            raise ValueError(f"Wrong source month: {source.name}")
        sources.append({"file": source.name, "sha256": sha256(raw), "bytes": len(raw),
                        "scope": "edges (X-to-Y only); z_edges are outside this example"})
        metadata[month] = {
            "source_file": source.name,
            "method": document["method"],
            "n_observations": int(document["n_observations"]),
            "normalization": document["metadata"]["normalization"],
            "x_adjustment": document["metadata"]["identification"]["x_adjustment"],
            "reference_scales": document["reference_scales"],
            "note": "Numeric scale values preserve the original JSON spelling as strings. "
                    "These are monthly aggregate run metadata, not published scenario rows.",
        }
        for source_pair, edge in document["edges"].items():
            excluded = bool(edge.get("excluded", False))
            rows.append({
                "month": month, "source": edge["source"], "target": edge["target"],
                "st": "" if excluded else str(edge["st"]),
                "ce_normalized": "" if excluded else str(edge["ce_normalized"]),
                "excluded": "true" if excluded else "false",
                "exclusion_reason": edge.get("exclusion_reason", ""),
                "source_file": source.name, "source_pair": source_pair,
            })
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    write_text(ROOT / "data/assessments.csv", stream.getvalue())
    write_text(ROOT / "data/run-metadata.json", json_text(metadata))
    article_bytes = article.read_bytes()
    manifest = {
        "schema_version": 1,
        "article": {"file": article.name, "revision": "rev05",
                    "sha256": sha256(article_bytes), "bytes": len(article_bytes)},
        "source_runs": sources,
        "extracts": {
            name: {"sha256": sha256((ROOT / name).read_bytes())}
            for name in ("data/assessments.csv", "data/run-metadata.json")
        },
        "transformations": [
            "Extract all 242 X-to-Y edges per month (22 factors x 11 indicators).",
            "Preserve every original numeric token for defined st and ce_normalized as CSV text.",
            "For excluded=true, omit numeric placeholders and use status undefined, without category.",
            "Keep defined ST <= 0 and |CE| >= 0.1 as status No_ST, without category.",
            "Apply rev05 Table 1 to other defined pairs; do not modify or re-estimate ST or CE.",
            "Select map edges strictly by ST > 0.1 and |CE| > 0.3; weight is signed CE.",
            "Dataset resources refer to original monthly scenario sets; scenario rows are not published here.",
        ],
        "statistical_recomputation": False,
    }
    write_text(ROOT / "source-manifest.json", json_text(manifest))


def classify(row: dict[str, str]) -> tuple[str, str | None]:
    if row["excluded"] == "true":
        return "undefined", None
    st, ce = Decimal(row["st"]), abs(Decimal(row["ce_normalized"]))
    if st <= 0 and ce >= Decimal("0.1"):
        return "No_ST", None
    if st >= Decimal("0.7") and ce >= Decimal("0.3"):
        return "reported", "Critical"
    if 0 < st < Decimal("0.3") and ce >= Decimal("0.3"):
        return "reported", "StrongLowST"
    if st >= Decimal("0.7") and ce < Decimal("0.3"):
        return "reported", "Uncertainty"
    if st < Decimal("0.7") and ce < Decimal("0.1"):
        return "reported", "Background"
    if st > 0:
        return "reported", "Moderate"
    raise ValueError(f"Unclassified pair: {row}")


def selected(row: dict[str, str]) -> bool:
    return (row["excluded"] != "true" and Decimal(row["st"]) > Decimal("0.1")
            and abs(Decimal(row["ce_normalized"])) > Decimal("0.3"))


def assessment_id(row: dict[str, str]) -> str:
    return f"{RUNS[row['month']][0]}_{row['source']}__{row['target']}"


def label(identifier: str) -> str:
    factors = {
        "peak_load_factor": "Фактор пиковой нагрузки", "wind_resource_factor": "Ветровой ресурс",
        "solar_resource_factor": "Солнечный ресурс", "subsidy_wind": "Субсидия на ВЭС",
        "subsidy_solar": "Субсидия на СЭС", "fossil_availability_factor": "Доступность ТЭС",
    }
    for suffix, region in (("_north", "Север"), ("_centre", "Центр"), ("_south", "Юг")):
        if identifier.endswith(suffix):
            return f"{factors[identifier[:-len(suffix)]]} ({region})"
    return {
        "investment_budget": "Инвестиционный бюджет", "co2_price": "Налог на CO₂",
        "market_price": "Рыночная цена электроэнергии", "fuel_price_gas": "Цена на газ",
        "profit_eur": "Прибыль", "revenue_eur": "Выручка",
        "co2_emissions_tonnes": "Выбросы CO₂", "budget_utilization_pct": "Использование бюджета",
        "operational_expenditure_eur": "Эксплуатационные затраты", "installed_wind_mw": "Новые мощности ВЭС",
        "installed_solar_mw": "Новые мощности СЭС", "renewable_generation_gwh": "Генерация ВИЭ",
        "renewable_share_pct": "Доля ВИЭ", "capital_expenditure_eur": "Капитальные затраты",
        "fossil_generation_gwh": "Генерация на ископаемом топливе",
    }[identifier]


def refs(ids: list[str]) -> str:
    return ", ".join("ex:" + item for item in ids)


def build(rows: list[dict[str, str]], metadata: dict) -> dict[str, str]:
    article = [PREFIXES, "# Generated by generate_example.py from data/assessments.csv; no re-estimation.\n",
               'ex:italyModel a a:OptimizationModel; rdfs:label "Оптимизационная модель энергосистемы Италии"@ru .\n',
               'ex:table1Rule a a:ClassificationRule; a:ruleVersion "table1-rev05";\n'
               ' a:stLow 0.3; a:stHigh 0.7; a:ceLow 0.1; a:ceStrong 0.3;\n'
               ' rdfs:comment "Таблица 1 редакции rev05; применяется модуль CE. No_ST и undefined являются состояниями записи, не категориями таблицы 1."@ru .\n\n']
    cxl = [PREFIXES, "# Load together with article-example.ttl. Explicit results and nodes for both monthly maps.\n"]
    summary = {"article_revision": "rev05", "rule_version": "table1-rev05",
               "filter": {"st_operator": ">", "st_threshold": "0.1", "abs_ce_operator": ">", "abs_ce_threshold": "0.3"},
               "months": {}}
    global_sources = sorted({row["source"] for row in rows})
    global_targets = sorted({row["target"] for row in rows})
    for identifier in global_sources + global_targets:
        type_name = "AnalyticalFactor" if identifier in global_sources else "OutputIndicator"
        article.append(f'ex:{identifier} a a:{type_name}; rdfs:label {quoted(label(identifier))}@ru .\n')
    article.append("\n")
    map_pairs = {}
    for month, (prefix, experiment, dataset, map_id, report, source_file) in RUNS.items():
        month_rows = [row for row in rows if row["month"] == month]
        sources = sorted({row["source"] for row in month_rows})
        targets = sorted({row["target"] for row in month_rows})
        pairs = {(r["source"], r["target"]) for r in month_rows}
        if len(month_rows) != 242 or len(pairs) != 242 or len(sources) != 22 or len(targets) != 11:
            raise ValueError(f"Incomplete or duplicate 22 x 11 matrix: {month}")
        if pairs != {(s, t) for s in sources for t in targets}:
            raise ValueError(f"Incomplete Cartesian product: {month}")
        month_name = "январь" if prefix == "jan" else "июль"
        article.append(f'ex:{experiment} a a:Experiment; a:usesModel ex:italyModel;\n'
                       f' rdfs:label "{month_name.capitalize()} 2013 года"@ru;\n'
                       f' a:hasFactor {refs(sources)};\n a:hasIndicator {refs(targets)} .\n')
        article.append(f'ex:{dataset} a a:Dataset; a:datasetExperiment ex:{experiment};\n'
                       ' a:metadataStatus "reference_only";\n'
                       f' a:artifactReference {quoted("Козлов_Михеев_rev05.docx; DXY, " + month + "; " + str(metadata[month]["n_observations"]) + " наблюдений по метаданным " + source_file)};\n'
                       ' rdfs:comment "Ресурс обозначает исходный месячный набор сценариев DXY. Строки сценариев здесь не опубликованы; 242 записи оценки пар не являются сценариями."@ru .\n')
        article.append(f'ex:{prefix}Normalization a a:NormalizationSpecification;\n'
                       ' a:formula "CE = beta * s_x / s_y";\n'
                       f' a:normalizationNote {quoted("Эмпирические стандартные отклонения исходной выборки за " + month + "; значения reference_scales сохранены в data/run-metadata.json. Нулевой масштаб показателя даёт undefined. Точные строки выборки и ddof этим примером не устанавливаются.")} .\n')
        article.append(f'ex:{prefix}Estimation a a:EstimationSpecification;\n'
                       ' a:method "dowhy_linear; backdoor.linear_regression"; a:adjustmentSet "[]";\n'
                       f' a:analysisSettings {quoted("Импорт агрегированных результатов " + source_file + "; исходные n_observations=" + str(metadata[month]["n_observations"]) + ". Повторное статистическое оценивание не выполнялось.")} .\n\n')
        selected_rows = []
        categories = Counter()
        statuses = Counter()
        for row in month_rows:
            identifier = assessment_id(row)
            status, category = classify(row)
            statuses[status] += 1
            if category:
                categories[category] += 1
            if row["source_file"] != source_file or row["excluded"] not in ("true", "false"):
                raise ValueError(f"Unexpected source metadata: {identifier}")
            if status == "undefined" and (row["st"] or row["ce_normalized"]):
                raise ValueError(f"Undefined assessment has numeric placeholders: {identifier}")
            types = "a:InfluenceAssessment" + (", a:ReportedAssessment" if status != "undefined" else "")
            source_locator = f'{source_file}#/edges/{row["source_pair"]}'
            article.append(f'ex:{identifier} a {types};\n'
                           f' a:experiment ex:{experiment}; a:dataset ex:{dataset};\n'
                           f' a:factor ex:{row["source"]}; a:indicator ex:{row["target"]};\n'
                           f' a:rule ex:table1Rule; a:status {quoted(status)};\n'
                           f' a:sourceLocator {quoted(source_locator)};\n')
            if status == "undefined":
                article.append(' a:evidenceNote ' + quoted("excluded=true; " + row["exclusion_reason"] + ". Нулевые заполнители исходного JSON не являются определёнными ST или CE и не перенесены.") + " .\n\n")
                continue
            article.append(f' a:st {number(row["st"])}; a:ce {number(row["ce_normalized"])};\n'
                           f' a:normalization ex:{prefix}Normalization; a:estimation ex:{prefix}Estimation;\n')
            if category:
                article.append(f' a:category a:{category};\n')
            note = "Исходные st и ce_normalized без округления или переоценивания."
            if status == "No_ST":
                note += " ST <= 0 при |CE| >= 0.1; запись не отнесена к пяти категориям таблицы 1."
            article.append(f' a:evidenceNote {quoted(note)} .\n\n')
            cxl.append(f'ex:{identifier} a:stResult ex:{identifier}ST; a:ceResult ex:{identifier}CE .\n'
                       f'ex:{identifier}ST a a:SensitivityIndex; a:numericValue {number(row["st"])} .\n'
                       f'ex:{identifier}CE a a:DirectedEffect; a:numericValue {number(row["ce_normalized"])} .\n')
            if selected(row):
                selected_rows.append(row)
        ids = [assessment_id(row) for row in month_rows]
        article.append(f'ex:{map_id} a a:CognitiveMap; a:mapExperiment ex:{experiment};\n'
                       ' a:mapRule ex:table1Rule; a:tauST 0.1; a:tauCE 0.3; a:selectionOperator ">";\n'
                       f' a:candidateAssessment {refs(ids)};\n'
                       f' a:purpose {quoted("Карта " + month + " по исходным X-to-Y оценкам; фильтр ST > 0.1 и |CE| > 0.3 из rev05")} .\n')
        article.append(f'ex:{report} a a:AnalyticalReport; a:reportMap ex:{map_id};\n'
                       f' a:reportAssessment {refs(ids)};\n'
                       ' rdfs:comment "Отчёт включает все пары, в том числе No_ST и undefined; отбор рёбер выполняется отдельно."@ru .\n')
        for identifier in sources + targets:
            kind = "Factor" if identifier in sources else "Indicator"
            cxl.append(f'ex:{prefix}_{identifier}_node a a:{kind}Node; a:represents{kind} ex:{identifier}; a:{kind.lower()}NodeMap ex:{map_id} .\n')
        cxl.append(f'ex:{map_id} a:hasFactorNode {refs([f"{prefix}_{s}_node" for s in sources])};\n'
                   f' a:hasIndicatorNode {refs([f"{prefix}_{t}_node" for t in targets])};\n'
                   f' a:hasEdge {refs(["edge_" + assessment_id(r) for r in selected_rows])} .\n')
        for row in selected_rows:
            identifier = assessment_id(row)
            category = classify(row)[1]
            article.append(f'ex:edge_{identifier} a a:MapEdge; a:inMap ex:{map_id}; a:basedOn ex:{identifier};\n'
                           f' a:source ex:{row["source"]}; a:target ex:{row["target"]}; a:weight {number(row["ce_normalized"])} .\n')
            cxl.append(f'ex:edge_{identifier} a:sourceNode ex:{prefix}_{row["source"]}_node; '
                       f'a:targetNode ex:{prefix}_{row["target"]}_node; a:edgeCategory a:{category} .\n')
        map_pairs[month] = {(r["source"], r["target"]) for r in selected_rows}
        summary["months"][month] = {
            "factors": len(sources), "indicators": len(targets), "assessments": len(month_rows),
            "defined_assessments": sum(v for k, v in statuses.items() if k != "undefined"),
            "statuses": {name: statuses[name] for name in ("reported", "No_ST", "undefined")},
            "categories": {name: categories[name] for name in CATEGORY_NAMES},
            "selected_edges": len(selected_rows),
        }
        article.append("\n")
        cxl.append("\n")
    summary["common_selected_pairs"] = len(map_pairs["2013-01"] & map_pairs["2013-07"])
    summary["total_assessments"] = len(rows)
    summary["scope_note"] = "Counts describe aggregated X-to-Y assessments; no scenario rows or statistical estimates are regenerated."
    return {"article-example.ttl": "".join(article), "cxl-example.ttl": "".join(cxl),
            "data/example-summary.json": json_text(summary)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="One-time import of the original run JSON files")
    parser.add_argument("--article", type=Path, help="rev05 DOCX for provenance when importing")
    parser.add_argument("--check", action="store_true", help="Check byte-for-byte reproducibility without writing")
    args = parser.parse_args()
    if args.source_dir:
        if args.check or not args.article:
            parser.error("--source-dir requires --article and cannot be combined with --check")
        import_sources(args.source_dir, args.article)
    elif args.article:
        parser.error("--article is used only with --source-dir")
    manifest = json.loads((ROOT / "source-manifest.json").read_text(encoding="utf-8"))
    for name, record in manifest["extracts"].items():
        if sha256((ROOT / name).read_bytes()) != record["sha256"]:
            raise ValueError(f"Extract hash differs from source manifest: {name}")
    with (ROOT / "data/assessments.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    metadata = json.loads((ROOT / "data/run-metadata.json").read_text(encoding="utf-8"))
    outputs = build(rows, metadata)
    manifest["generated"] = {name: {"sha256": sha256(content.encode("utf-8"))} for name, content in outputs.items()}
    manifest["generator"] = {"file": "generate_example.py", "sha256": sha256(Path(__file__).read_bytes()),
                             "dependencies": "Python 3.10+ standard library"}
    outputs["source-manifest.json"] = json_text(manifest)
    differences = []
    for name, content in outputs.items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_bytes() != content.encode("utf-8"):
                differences.append(name)
        else:
            write_text(path, content)
    if differences:
        print("Regeneration differs: " + ", ".join(differences))
        return 1
    print("Offline reproducibility check passed." if args.check else "Example regenerated from the published extract.")
    print(outputs["data/example-summary.json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
