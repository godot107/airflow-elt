# What "production-shaped" means for a data pipeline: Airflow 3, dbt and a month of bad data

*Draft. Code: [github.com/godot107/airflow-elt](https://github.com/godot107/airflow-elt).*

Most pipeline tutorials end when the happy path works: download a file, load it, run a query, draw a chart.
Real pipelines rarely fail there. They fail when a task is retried halfway through a load, when someone
backfills three years, when the source publishes late, when the schema quietly changes, and when a file
arrives that is wrong in a way nobody anticipated.

I built a small ELT warehouse on NYC taxi trips to practice the habits that handle those cases, using Airflow 3
for orchestration and dbt for the transformations. The taxi numbers are incidental. This post is about the
habits, and about what the data taught me about setting quality rules.

![The pipeline](https://raw.githubusercontent.com/godot107/airflow-elt/main/docs/img/workflow.png)

## The shape

Two DAGs, connected by data instead of by a clock:

- **`taxi_ingest`** runs once per month of data. It waits for the NYC TLC to publish the file, downloads
  it, replaces that month in a `raw` table, and runs a quality gate. Only a month that passes publishes an
  Airflow **asset** event.
- **`taxi_transform`** runs on that asset event. It is a dbt project rendered into Airflow tasks by
  Astronomer Cosmos: every model is a `run` task followed by its `test` task.

![taxi_transform in the Airflow UI](https://raw.githubusercontent.com/godot107/airflow-elt/main/docs/img/airflow_transform_graph.png)

## Habit 1: every run owns a slice, and rerunning a slice replaces it

Each `taxi_ingest` run owns one **data interval**, a calendar month. The load deletes that month and
`COPY`s the file in a single transaction, so a retry, a backfill, or a deliberate reload leaves exactly one
copy. Maxime Beauchemin called this "functional data engineering" in 2018; it is still the single most
useful property a batch task can have.

I tested it on real data rather than taking it on faith: clearing January's load task reloaded 2.96 million
trips, the raw count stayed exactly the same, the asset event re-triggered dbt, and the incremental fact
table rebuilt **only January**.

One Airflow 3 detail mattered here. Cron schedules now default to *trigger* timetables, which have no data
interval. To make each run own a month, the DAG declares a `CronDataIntervalTimetable` explicitly. The
same change bit me later: a manual trigger's data interval comes from the current time, not from the
logical date you pass, so "trigger April" loads the current month. Backfills are the right tool for
history.

## Habit 2: a gate between load and transform, with thresholds you measured

The quality gate computes seven rules in one SQL pass over the loaded month and writes every result,
pass or fail, to an audit table. Four are **error** rules (row count, pickups inside the month, valid zone
ids, dropoff after pickup): a failure fails the run, with no retries, because bad data doesn't get better
by waiting. Three are **warn** rules: they alert and let the month through.

The interesting part was choosing thresholds. "No negative fares" sounds reasonable and would fail every
single month: 1–2% of trips are refunds and disputes. Missing passenger counts climbed from 4.7% to 11.9%
over the first quarter of 2024, which looks like a feed degrading, until you notice that a row lacks a
passenger count *exactly* when its payment type is 0, a flex fare. It wasn't decay; flex fares were growing.

Then I loaded January 2025, and both warning rules fired for real: 4.2% negative fares and 15.5% missing
passenger counts. The jump is concentrated in flex-fare trips from one vendor. The month loaded, and the
alert said so. That's the difference between an error rule and a warning rule, and it's a judgment call
the audit table now makes visible instead of hiding in a default.

![Validation results](https://raw.githubusercontent.com/godot107/airflow-elt/main/docs/img/validation.png)

## Habit 3: make the bad path a demo, not a hope

Defenses you have never seen fire are hopes. So the loader has a fault-injection hook, switched on per
month by an Airflow Variable: shift half the pickups a year early, corrupt 5% of zone ids, or drop a
required column. The demo notebook loads a month that way and you watch it go red at the gate on its first
try, with the failing rule and its value in the audit table.

The bad month is in `raw`, because raw is a landing zone, but it never reaches the marts. That took two
mechanisms, not one. The asset event keeps dbt from running *because of* the bad month, but another
month's event can still start dbt. So the fact table only takes months whose latest gate check passed
and is newer than their latest load (`approved_months`). Recovery is an ordinary Airflow action: fix the
source, clear the load task with its downstream, and the month flows through.

## Habit 4: the schema will drift, so write the contract down

TLC's files are not stable: `airport_fee` in 2023 became `Airport_fee` in 2024, `passenger_count` changed
from double to integer, and 2025 added a congestion-pricing fee. The loader maps every file onto an
explicit column contract: names matched case-insensitively, types cast, missing columns NULL, unknown
columns logged rather than silently loaded, missing *required* columns a hard failure. Adding the 2025
fee to the contract added the column to the table on the next load, NULL for 2024.

## Habit 5: tests at three speeds

- **Unit tests** (pytest and dbt unit tests) run in seconds on hand-made rows: the contract, each fault,
  the alert webhook, which rows get which exclusion reason, which months count as approved, and which
  months an incremental run rebuilds.
- **Integration tests** run against the real warehouse container: a reload replaces a month, a new
  contract column appears, an injected fault reaches the table and the gate catches it.
- **Data tests** run after every dbt model on the real data, including two reconciliations: staging has
  exactly as many rows as raw, and the daily mart's trips and revenue equal the fact table's.

They earned their keep during the build. The integration test caught that the Postgres provider now hands
out psycopg 3 connections (my loader assumed psycopg2), and a cross-model test caught a Cosmos ordering
issue. All of it runs in CI on every push.

![dbt lineage](https://raw.githubusercontent.com/godot107/airflow-elt/main/docs/img/dbt_lineage.png)

## Running it for a demo, not forever

Locally it's `make up`. For demos there is a CloudFormation stack: one Graviton instance, **no inbound
ports** (the UI and warehouse come through an SSM tunnel), and a boot script whose first line schedules
its own shutdown, with the instance set to terminate on shutdown. A forgotten demo stops billing by
itself. Four hours costs about thirty cents. I deliberately did not add a cloud schedule: for something
that lives a few hours, create-and-delete beats start-and-stop.

## What I'd do next

- Move thresholds into a reviewed config with history, so changing "3%" is a pull request, not an edit.
- Store the warn-rule trend and alert on its slope, not just its level.
- Swap the local Postgres warehouse for a cloud one (the dbt project wouldn't change).

*References: Apache Airflow 3.3 docs (asset scheduling, backfill, best practices); Astronomer Cosmos;
dbt docs (incremental models, unit tests, data tests); M. Beauchemin, "Functional Data Engineering" (2018);
NYC TLC trip record data and data dictionary.*
