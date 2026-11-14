# Scoring Lambda image: arm64 (Graviton), runtime dependencies only, no model inside.
#
# The model is downloaded from S3 at the first request (MODEL_URI), so promoting a model never
# requires a new image. Build from the repository root:
#   make image
FROM public.ecr.aws/lambda/python:3.12-arm64

# LightGBM links against the OpenMP runtime, which the base image does not ship.
RUN dnf install -y libgomp && dnf clean all

COPY docker/requirements.txt /tmp/requirements.txt
# The requirements carry SHA-256 hashes, so pip refuses any package that does not match.
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# The package is copied whole so imports are identical to the batch path; only the serving,
# model-artefact and calibration modules are imported at runtime.
COPY src/muletrace ${LAMBDA_TASK_ROOT}/muletrace

CMD ["muletrace.serving.handler.handler"]
