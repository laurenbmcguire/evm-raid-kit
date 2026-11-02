"""Critical path method (CPM) on working-day durations.

Times are working-day offsets from the project origin using a half-open convention:
a task with ``ES = 3`` and duration 2 occupies working days 3 and 4 and has ``EF = 5``.
A successor can start at ``max(EF of predecessors)`` (finish-to-start, zero lag).

* Total float  ``TF = LS - ES``
* Free float   ``FF = min(ES of successors) - EF`` (project end for terminal tasks)
* Critical     ``TF == 0``
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CPMResult:
    table: pd.DataFrame
    critical_path: list[str]
    duration: int
    order: list[str] = field(default_factory=list)


def parse_deps(value) -> list[str]:
    """Parse a ``depends_on`` cell such as ``"T03;T04"`` into a list of ids."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, float) and pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return [p.strip() for p in text.replace(",", ";").split(";") if p.strip()]


def topological_order(durations: dict[str, int], deps: dict[str, list[str]]) -> list[str]:
    for tid, preds in deps.items():
        for p in preds:
            if p not in durations:
                raise ValueError(f"Task {tid} depends on unknown task {p}")
    indeg = {t: len(deps.get(t, [])) for t in durations}
    succ: dict[str, list[str]] = {t: [] for t in durations}
    for t, preds in deps.items():
        for p in preds:
            succ[p].append(t)
    queue = deque([t for t in durations if indeg[t] == 0])
    order: list[str] = []
    while queue:
        t = queue.popleft()
        order.append(t)
        for s in succ[t]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(order) != len(durations):
        raise ValueError("Dependency cycle detected in the plan")
    return order


def cpm(durations: dict[str, int], deps: dict[str, list[str]]) -> CPMResult:
    """Forward and backward pass. ``durations`` in working days, ``deps`` = predecessors."""
    order = topological_order(durations, deps)
    succ: dict[str, list[str]] = {t: [] for t in durations}
    for t in durations:
        for p in deps.get(t, []):
            succ[p].append(t)

    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for t in order:
        es[t] = max((ef[p] for p in deps.get(t, [])), default=0)
        ef[t] = es[t] + int(durations[t])
    project = max(ef.values(), default=0)

    lf: dict[str, int] = {}
    ls: dict[str, int] = {}
    for t in reversed(order):
        lf[t] = min((ls[s] for s in succ[t]), default=project)
        ls[t] = lf[t] - int(durations[t])

    rows = []
    for t in order:
        tf = ls[t] - es[t]
        ff = min((es[s] for s in succ[t]), default=project) - ef[t]
        rows.append(
            {
                "id": t,
                "duration": int(durations[t]),
                "es": es[t],
                "ef": ef[t],
                "ls": ls[t],
                "lf": lf[t],
                "total_float": tf,
                "free_float": ff,
                "critical": tf == 0,
            }
        )
    table = pd.DataFrame(rows).set_index("id")
    critical = [t for t in order if table.at[t, "critical"]]
    return CPMResult(table=table, critical_path=critical, duration=project, order=order)
