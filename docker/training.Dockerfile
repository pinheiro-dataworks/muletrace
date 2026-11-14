# SageMaker training image: runs muletrace.pipelines.train_entry on the "snapshots" channel.
#
#   uv export --frozen --no-dev --no-emit-project --extra pipeline --extra aws \
#     -o docker/requirements-batch.txt
#   docker buildx build --platform linux/amd64 -f docker/training.Dockerfile -t muletrace-train .
FROM public.ecr.aws/docker/library/python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY docker/requirements-batch.txt /tmp/requirements.txt
# The requirements carry SHA-256 hashes, so pip refuses any package that does not match.
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

WORKDIR /opt/ml/code
COPY src/muletrace ./muletrace
COPY configs ./configs
ENV PYTHONPATH=/opt/ml/code \
    MULETRACE_CONFIG_DIR=/opt/ml/code/configs \
    PYTHONUNBUFFERED=1

# SageMaker starts training containers with the argument "train".
ENTRYPOINT ["python", "-m", "muletrace.pipelines.train_entry"]
