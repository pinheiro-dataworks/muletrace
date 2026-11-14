# Daily-scoring Lambda image (BuildSnapshot and ScoreAndPublish), arm64.
# It needs the batch libraries (Polars, SciPy) the scoring image leaves out.
#
#   uv export --frozen --no-dev --no-emit-project --extra pipeline --extra aws \
#     -o docker/requirements-batch.txt
#   docker buildx build --platform linux/arm64 -f docker/batch.Dockerfile -t muletrace-batch .
FROM public.ecr.aws/lambda/python:3.12-arm64

RUN dnf install -y libgomp && dnf clean all

COPY docker/requirements-batch.txt /tmp/requirements.txt
# The requirements carry SHA-256 hashes, so pip refuses any package that does not match.
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY src/muletrace ${LAMBDA_TASK_ROOT}/muletrace
COPY configs ${LAMBDA_TASK_ROOT}/configs

# The handler is chosen per function by the CDK stack (image command override).
CMD ["muletrace.pipelines.daily.score_and_publish_handler"]
