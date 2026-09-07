FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/scout ./scout
# Prefetch the embedding weights at build time: the bundle boot check fingerprints them,
# so a deploy must never download 79 MB at boot or depend on S3 being reachable.
RUN python -c "from scout.pipeline.embedding import model_fingerprint; print(model_fingerprint())"
COPY data/bundle /data/bundle
ENV BUNDLE_DIR=/data/bundle PORT=8000
EXPOSE 8000
CMD ["python", "-m", "scout.main"]
