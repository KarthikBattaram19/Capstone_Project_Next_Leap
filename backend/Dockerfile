FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/scout ./scout
COPY data/bundle /data/bundle
ENV BUNDLE_DIR=/data/bundle PORT=8000
EXPOSE 8000
CMD ["python", "-m", "scout.main"]
