"""Upload feature snapshots and start the Spot training job in SageMaker.

Run after deployment, with an AWS profile that may use the training role. The job trains the
same model as ``muletrace models train-final`` and writes ``model.tar.gz`` under
``s3://<bucket>/models/``; register it with ``--register`` once the job has finished.

Usage:
    uv run python scripts/start_training_job.py --bucket <data-bucket> --role-arn <sagemaker-role>
        --image-uri <training-image> [--dataset HI-Small]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import boto3
import yaml

from muletrace.pipelines.sagemaker_training import TrainingJobSpec, start_training


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--image-uri", required=True)
    parser.add_argument("--dataset", default="HI-Small")
    args = parser.parse_args()

    s3 = boto3.client("s3")
    snapshots = sorted(Path("artifacts/features").glob(f"{args.dataset}-*/*.parquet"))
    if not snapshots:
        raise SystemExit("No cached snapshots: run `muletrace features build` first.")
    for path in snapshots:
        s3.upload_file(str(path), args.bucket, f"snapshots/{args.dataset}/training/{path.name}")

    backtest = yaml.safe_load(
        Path(f"docs/generated/backtest_{args.dataset}.yaml").read_text("utf-8")
    )
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    spec = TrainingJobSpec(
        job_name=f"muletrace-{args.dataset.lower()}-{stamp}",
        image_uri=args.image_uri,
        role_arn=args.role_arn,
        snapshots_s3_uri=f"s3://{args.bucket}/snapshots/{args.dataset}/training/",
        output_s3_uri=f"s3://{args.bucket}/models/",
        checkpoint_s3_uri=f"s3://{args.bucket}/checkpoints/{stamp}/",
        hyperparameters=backtest["chosen_params"]["lgbm_tabular_graph"],
    )
    print(start_training(boto3.client("sagemaker"), spec))


if __name__ == "__main__":
    main()
