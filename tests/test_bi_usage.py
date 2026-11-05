"""bi.usage.sync copies only log rows past the warehouse high-water mark, so reruns never duplicate."""
from bi import usage


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if "max(log_id)" in sql:
            self._result = [(self.conn.watermark,)]
        elif sql is usage.EXTRACT_SQL:
            self._result = [r for r in self.conn.log if r[0] > params["since"]]
        elif sql is usage.INSERT_SQL:
            self.conn.inserted.append(params)

    def fetchone(self):
        return self._result[0]

    def fetchall(self):
        return self._result


class FakeConn:
    def __init__(self, watermark=0, log=()):
        self.watermark, self.log, self.executed, self.inserted, self.commits = watermark, list(log), [], [], 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def row(log_id):
    return (log_id, "2026-11-05 12:00", "ops_manager", False, "dashboard", None, 1, "Taxi operations",
            True, None, None, None, None, None)


def test_sync_inserts_only_new_rows_and_creates_table():
    warehouse = FakeConn(watermark=2)
    superset = FakeConn(log=[row(1), row(2), row(3), row(4)])
    assert usage.sync(warehouse, superset) == 2
    assert [r[0] for r in warehouse.inserted] == [3, 4]
    assert warehouse.executed[0][0] is usage.DDL and warehouse.commits == 1


def test_insert_is_idempotent_on_log_id():
    assert "on conflict (log_id) do nothing" in usage.INSERT_SQL
