# Shared settings for deploy scripts. Source, don't run.
STACK=${STACK:-airflow-elt-demo}
COST_STACK=${COST_STACK:-airflow-elt-cost}
export AWS_REGION=${AWS_REGION:-us-east-1}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

# shared/TAGGING.md: CloudFormation copies stack tags to every taggable resource.
TAGS=(project=airflow-elt environment=dev owner=williemaize cost-center=personal
      managed-by=cloudformation component=lab repository=github.com/godot107/airflow-elt)

require_iam_user() {
  local arn
  arn=$(aws sts get-caller-identity --query Arn --output text) || {
    echo "No AWS session: run 'aws login' first." >&2; exit 1; }
  case "$arn" in
    *:root) echo "Refusing to deploy as the root user. 'aws login' as WillieMaize." >&2; exit 1 ;;
  esac
}

out() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

# Run a shell command on the instance through SSM and print its stdout.
on_instance() {
  local instance=$1; shift
  local cmd status
  cmd=$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
    --parameters "commands=[\"$*\"]" --query Command.CommandId --output text)
  while :; do
    status=$(aws ssm get-command-invocation --command-id "$cmd" --instance-id "$instance" \
      --query Status --output text 2>/dev/null || echo Pending)
    case "$status" in Pending|InProgress|Delayed) sleep 3 ;; *) break ;; esac
  done
  aws ssm get-command-invocation --command-id "$cmd" --instance-id "$instance" \
    --query StandardOutputContent --output text
  [ "$status" = "Success" ]
}
