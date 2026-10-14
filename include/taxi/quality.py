"""Data-quality gate between load and transform: every rule is computed in one SQL pass over the month,
written to the audit table, and any failed "error" rule stops the run before dbt reads the data."""
import operator
from dataclasses import dataclass

from taxi import config

OPS = {">=": operator.ge, "<=": operator.le}


class DataQualityError(Exception):
    pass


@dataclass
class Result:
    rule: str
    value: float | None
    op: str
    threshold: float
    severity: str

    @property
    def passed(self) -> bool:
        return self.value is not None and OPS[self.op](self.value, self.threshold)

    def __str__(self):
        mark = "ok  " if self.passed else ("FAIL" if self.severity == "error" else "warn")
        return f"[{mark}] {self.rule:<22} {self.value!s:<24} {self.op} {self.threshold}"


def metrics_sql(rules=config.RULES) -> str:
    exprs = ",\n       ".join(f"{expr.replace(':start', '%(start)s').replace(':end', '%(end)s')} as {name}"
                              for name, expr, *_ in rules)
    return f"select {exprs}\nfrom {config.RAW_TABLE}\nwhere source_month = %(month)s"


def evaluate(metrics: dict, rules=config.RULES) -> list[Result]:
    return [Result(name, None if metrics.get(name) is None else float(metrics[name]), op, threshold, severity)
            for name, _, op, threshold, severity in rules]


def check(conn, month: str, start: str, end: str, run_id: str) -> list[Result]:
    with conn.cursor() as cur:
        cur.execute(metrics_sql(), {"month": f"{month}-01", "start": start, "end": end})
        metrics = dict(zip([d[0] for d in cur.description], cur.fetchone()))
        results = evaluate(metrics)
        cur.executemany(
            f"insert into {config.AUDIT_TABLE} (run_id, source_month, rule, value, op, threshold, severity, passed)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s)",
            [(run_id, f"{month}-01", r.rule, r.value, r.op, r.threshold, r.severity, r.passed) for r in results])
    conn.commit()                        # audit rows persist even when the gate fails
    failed = [r for r in results if r.severity == "error" and not r.passed]
    if failed:
        raise DataQualityError(f"{month}: " + "; ".join(map(str, failed)))
    return results
