"""Render the evaluation as a markdown report — the artifact the README cites."""

from __future__ import annotations

from engpulse.eval.harness import EvaluationReport


def render_eval_report(report: EvaluationReport, deterministic: bool) -> str:
    lines: list[str] = [
        "# EngPulse — Evaluation Report",
        "",
        f"Labeled synthetic corpus · as of {report.as_of.date()}",
        "",
        "## Detectors & entity resolution",
        "",
        "| Task | Precision | Recall | F1 |",
        "|---|---|---|---|",
    ]
    for s in report.scores:
        lines.append(
            f"| {s['detector']} | {s['precision']:.2f} | "
            f"{s['recall']:.2f} | {s['f1']:.2f} |"
        )
    lines += [
        "",
        f"**Macro precision {report.macro_precision:.2f} / "
        f"recall {report.macro_recall:.2f}** across {len(report.scores)} tasks.",
        "",
    ]

    if report.agent:
        a = report.agent
        lines += [
            "## Ask EngPulse agent",
            "",
            f"- Questions: {a['answerable']}/{a['questions']} answerable",
            f"- Source recall: {a['source_recall']:.2f}",
            f"- Citation faithfulness: {a['citation_faithfulness']:.2f}",
            f"- Correct abstention (unanswerable): {a['correct_abstention']:.2f}",
            "",
        ]

    lines += [
        "## Determinism / regression",
        "",
        f"- Re-running the full evaluation yields identical scores: "
        f"{'yes' if deterministic else 'NO'}",
        "",
    ]
    return "\n".join(lines)
