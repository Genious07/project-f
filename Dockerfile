ARG PYTHON_IMAGE=python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /src
COPY pyproject.toml README.md ./
COPY foresee ./foresee
RUN python -m pip wheel --no-deps --wheel-dir /wheels .

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --no-deps /wheels/*.whl
WORKDIR /data
USER 10001:10001
ENTRYPOINT ["foresee"]
CMD ["--help"]
