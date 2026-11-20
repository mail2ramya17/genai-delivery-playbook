"""Pin 1: not every idea should become a GenAI project.

Runs the intake funnel: submitted -> value screen -> feasibility & data readiness ->
approved (every governance control cleared), and prints a weighted shortlist.

    python usecases/score_usecases.py [usecases/candidates.yaml]
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


def run(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    w, cut, controls = cfg["weights"], cfg["cutoffs"], set(cfg["governance_controls"])
    stages = {"submitted": cfg["candidates"]}
    stages["value_screen"] = [c for c in stages["submitted"] if c["scores"]["value"] >= cut["value_screen"]]
    stages["feasible_and_data_ready"] = [
        c for c in stages["value_screen"]
        if min(c["scores"]["feasibility"], c["scores"]["data_ready"]) >= cut["feasibility_and_data"]
    ]
    for c in stages["submitted"]:
        c["weighted"] = round(sum(c["scores"][k] * wt for k, wt in w.items()), 2)
        c["missing_controls"] = sorted(controls - set(c.get("governance", [])))
    stages["approved"] = sorted(
        (c for c in stages["feasible_and_data_ready"] if not c["missing_controls"]),
        key=lambda c: c["weighted"], reverse=True,
    )
    return stages


def bar(score: int) -> str:
    return "#" * score + "." * (5 - score)


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("candidates.yaml"))
    stages = run(path)
    print("FUNNEL")
    for name, items in stages.items():
        print(f"  {name:<24} {len(items):>3}")
    print("\nSHORTLIST (value / feasibility / low risk / data ready)")
    for c in stages["approved"]:
        s = c["scores"]
        print(f"  {c['name']:<32} {bar(s['value'])} {bar(s['feasibility'])} {bar(s['low_risk'])} "
              f"{bar(s['data_ready'])}  weighted {c['weighted']}")
    print("\nREJECTED")
    approved = {c["name"] for c in stages["approved"]}
    screened = {c["name"] for c in stages["feasible_and_data_ready"]}
    for c in stages["submitted"]:
        if c["name"] not in approved:
            s = c["scores"]
            why = (f"missing governance: {', '.join(c['missing_controls'])}" if c["name"] in screened
                   else f"below screen cutoffs (value {s['value']}, feasibility {s['feasibility']}, data {s['data_ready']})")
            print(f"  {c['name']:<32} {why}")


if __name__ == "__main__":
    main()
