# One image, three services: `python -m agent_stack {gateway,agent,mockllm}`.
FROM python:3.11-slim AS build
# Override to build behind a corporate package mirror.
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.11-slim
ARG GIT_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GIT_SHA=${GIT_SHA}
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
# Numeric non-root user so runAsNonRoot works on Kubernetes. Group 0 so
# OpenShift's arbitrary UID (always in group 0) can run it unchanged.
RUN useradd --uid 10001 --gid 0 --no-create-home --shell /usr/sbin/nologin app
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "agent_stack"]
CMD ["gateway"]
