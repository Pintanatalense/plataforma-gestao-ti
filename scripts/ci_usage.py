#!/usr/bin/env python3
"""Relatório de consumo do GitHub Actions: minutos por semana, por job e por PR.

Somente leitura (`gh api`), roda na máquina de quem pergunta e não gasta minutos de CI.
Os minutos são uma ESTIMATIVA: duração de cada job arredondada para cima, em minutos, como o GitHub
faz em runners Linux. O valor oficial é o da página Settings > Billing and plans.

Uso:
    python scripts/ci_usage.py                       # últimos 28 dias, tabelas em texto
    python scripts/ci_usage.py --since 2026-10-23 --until 2026-10-24
    python scripts/ci_usage.py --json > consumo.json
    python scripts/ci_usage.py --repo dono/repositorio --steps 3
"""
import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta


def gh_lines(path: str) -> list[dict]:
    """Chama `gh api --paginate` e devolve um objeto por linha (o --jq do gh já achata as páginas)."""
    expr = ".workflow_runs[]" if "/runs?" in path else ".jobs[]"
    out = subprocess.run(
        ["gh", "api", path, "--paginate", "--jq", expr],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        sys.exit(f"gh api falhou ({path}): {out.stderr.strip()}")
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]


def ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def seconds(start: str | None, end: str | None) -> float:
    a, b = ts(start), ts(end)
    return max((b - a).total_seconds(), 0.0) if a and b else 0.0


def billed_minutes(secs: float) -> int:
    return math.ceil(secs / 60) if secs > 1 else 0


def default_repo() -> str:
    out = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.exit("Informe --repo dono/repositorio (gh repo view falhou).")
    return out.stdout.strip()


def collect(repo: str, since: str, until: str | None, top_steps: int) -> dict:
    created = f"{since}..{until}" if until else f"%3E%3D{since}"
    runs = gh_lines(f"repos/{repo}/actions/runs?created={created}&per_page=100")
    by_week, by_job, by_event = defaultdict(int), defaultdict(lambda: {"min": 0, "secs": 0.0, "n": 0}), defaultdict(lambda: [0, 0])
    by_pr: dict[str, dict] = {}
    steps: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    total = 0
    for run in runs:
        run_min = 0
        for job in gh_lines(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100"):
            if job.get("conclusion") == "skipped" or not job.get("completed_at"):
                continue
            secs = seconds(job.get("started_at"), job.get("completed_at"))
            minutes = billed_minutes(secs)
            run_min += minutes
            agg = by_job[job["name"]]
            agg["min"] += minutes
            agg["secs"] += secs
            agg["n"] += 1
            for step in job.get("steps", []):
                steps[job["name"]][step["name"]].append(seconds(step.get("started_at"), step.get("completed_at")))
        total += run_min
        iso = ts(run["created_at"]).isocalendar()
        by_week[f"{iso.year}-S{iso.week:02d}"] += run_min
        by_event[run["event"]][0] += 1
        by_event[run["event"]][1] += run_min
        prs = run.get("pull_requests") or []
        number = f" #{prs[0]['number']}" if prs else ""
        key = f"{run['event']}{number}: {run['head_branch']}"
        pr = by_pr.setdefault(key, {"runs": 0, "min": 0, "cancelled": 0, "failed": 0})
        pr["runs"] += 1
        pr["min"] += run_min
        pr["cancelled"] += run.get("conclusion") == "cancelled"
        pr["failed"] += run.get("conclusion") == "failure"
    slow_steps = {
        job: sorted(((name, sum(v) / len(v), len(v)) for name, v in s.items()), key=lambda t: -t[1])[:top_steps]
        for job, s in steps.items()
    }
    return {"repo": repo, "since": since, "until": until, "runs": len(runs), "estimated_minutes": total,
            "by_week": dict(sorted(by_week.items())), "by_event": {k: tuple(v) for k, v in by_event.items()},
            "by_job": dict(sorted(by_job.items(), key=lambda kv: -kv[1]["min"])),
            "by_pr": dict(sorted(by_pr.items(), key=lambda kv: -kv[1]["min"])), "slow_steps": slow_steps}


def render(d: dict) -> str:
    lines = [f"Repositório: {d['repo']} | {d['since']} até {d['until'] or 'hoje'} | {d['runs']} execuções | ~{d['estimated_minutes']} min (estimado)", ""]
    lines += ["Por semana (min):"] + [f"  {w}: {m}" for w, m in d["by_week"].items()]
    lines += ["", "Por evento (execuções, min):"] + [f"  {e}: {n} exec, {m} min" for e, (n, m) in d["by_event"].items()]
    lines += ["", "Por job (min faturados | duração média | execuções):"]
    for name, a in d["by_job"].items():
        lines.append(f"  {name}: {a['min']} min | {a['secs'] / max(a['n'], 1):.0f} s | {a['n']}")
    lines += ["", "Por PR (min | execuções | canceladas | falhas | min/execução):"]
    for name, p in d["by_pr"].items():
        lines.append(f"  {name}: {p['min']} min | {p['runs']} | {p['cancelled']} | {p['failed']} | {p['min'] / max(p['runs'], 1):.1f}")
    if d["slow_steps"]:
        lines += ["", "Etapas mais lentas por job (duração média):"]
        for job, items in d["slow_steps"].items():
            lines += [f"  {job}:"] + [f"    {avg:.0f} s  {name}  (x{n})" for name, avg, n in items]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="dono/repositorio (padrão: o do diretório atual)")
    parser.add_argument("--since", default=(date.today() - timedelta(days=28)).isoformat(), help="AAAA-MM-DD")
    parser.add_argument("--until", help="AAAA-MM-DD (inclusive; padrão: hoje)")
    parser.add_argument("--steps", type=int, default=3, help="quantas etapas lentas listar por job (0 = nenhuma)")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # o console do Windows usa cp1252
    data = collect(args.repo or default_repo(), args.since, args.until, args.steps)
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data))


if __name__ == "__main__":
    main()
