# Demo deploy on AWS

One CloudFormation stack, created right before a demo and deleted right after. No scheduled
infrastructure: nothing runs, and almost nothing bills, between demos.

```
aws login                  # as the IAM user, never root
deploy/preflight.sh        # read-only: tools, session, default VPC, leftover stack, template, code pushed
deploy/deploy_cost.sh      # once: $5/month budget alert on tag project=airflow-elt (free, kept)
deploy/up.sh               # ~10-15 min: instance, Docker, image build, Airflow healthy, backfill starts
deploy/smoke.sh            # a few minutes later: containers, DAGs, backfill runs, transform, marts
deploy/tunnel.sh           # Airflow on localhost:8080 and the warehouse on localhost:5433, over SSM
deploy/down.sh             # delete everything
```

The instance clones **GitHub**, not your working tree: push first (`preflight.sh` warns about unpushed
commits). With the tunnel open, `notebooks/demo.ipynb` runs against the cloud stack unchanged; `up.sh`
prints the two passwords to export.

| Variable for `up.sh` | Default | |
|---|---|---|
| `MAX_HOURS` | `4` | Self-termination timer (1–24). `deploy/extend.sh 2` moves it to 2 hours from now. |
| `FROM`, `TO` | `2024-01-01`, `2024-03-31` | Months to backfill at boot. `FROM=` starts with an empty warehouse. |
| `GIT_REF` | `main` | Branch, tag or commit of this repo to deploy (the instance clones it from GitHub). |
| `INSTANCE_TYPE` | `t4g.large` | `t4g.medium` for a no-backfill demo; `t4g.xlarge` if the UI feels slow. |

## What gets created

`infra/demo.yaml`: one Graviton EC2 instance (Ubuntu 24.04 arm64, 30 GB encrypted gp3), an instance role
with only `AmazonSSMManagedInstanceCore`, and a security group with **no inbound rules**. At boot the
instance installs Docker, clones the repo, generates random secrets into `.env`, runs
`docker compose up --build --wait`, then `make backfill`. The Airflow UI stays bound to the instance's
localhost; you reach it through an SSM port-forwarding tunnel, so there is nothing to scan or log into
from the internet, and no SSH key to manage.

## Why no cloud schedule

- **Infrastructure:** a demo stack lives for hours. A start/stop schedule (EventBridge Scheduler or
  Instance Scheduler) suits a server that should exist every weekday; here it would keep a stopped instance
  and its disk around between demos for no benefit. Create and delete instead: `up.sh` / `down.sh`.
- **Forgetting `down.sh`:** the instance runs `shutdown -h +MaxHours` as the first line of its boot
  script and is configured to **terminate** on shutdown, so its disk and public IP go with it. What can be
  left is the empty stack shell (role, instance profile, security group), which costs nothing; `down.sh`
  removes it. The budget stack emails if the project's spend passes $2.50 in a month.
- **Airflow's own schedule:** `taxi_ingest` is monthly and TLC publishes two months late, so during a
  demo the schedule does nothing visible except the newest month's sensor waiting. The demo content comes
  from the boot-time backfill; trigger more months live with `make backfill` through the shell.

## Cost (us-east-1, on-demand; check the AWS Pricing Calculator before quoting)

| Item | Rate | 4-hour demo |
|---|---|---|
| t4g.large | ~$0.067/h | ~$0.27 |
| 30 GB gp3 | ~$0.08/GB-month | ~$0.01 |
| Public IPv4 | $0.005/h | $0.02 |
| Data in (Docker Hub, PyPI, TLC files) | free | $0 |
| **Total** | | **≈ $0.30** |

`CPUCredits: standard` means a busy instance slows down rather than billing surplus CPU credits.

## Prerequisites

- `aws login` as the IAM user (the scripts refuse root).
- The Session Manager plugin for `tunnel.sh` (no sudo needed; installed on the workstation 2026-10-14):

  ```bash
  curl -fsSLo /tmp/smp.deb https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb
  dpkg -x /tmp/smp.deb ~/.local/smp
  ln -sf ~/.local/smp/usr/local/sessionmanagerplugin/bin/session-manager-plugin ~/.local/bin/
  session-manager-plugin --version
  ```

## Troubleshooting

- `deploy/logs.sh` tails `/var/log/bootstrap.log` on the instance (`LINES=100 deploy/logs.sh` for more).
- Shell: `aws ssm start-session --target $(aws cloudformation describe-stacks --stack-name airflow-elt-demo --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)`,
  then `cd /opt/airflow-elt && sudo make logs`.
- Don't rerun `up.sh` with new settings against a running stack: `MAX_HOURS`, `FROM` and `GIT_REF` live in
  the boot script, and changing an instance's user data only stops and restarts it; the script does not run
  again. Use `extend.sh` for the timer; for anything else, `down.sh` then `up.sh`.
