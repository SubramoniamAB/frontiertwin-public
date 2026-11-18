# FrontierTwin: tiny stdlib-only image (works on arm64 DGX Spark and x86_64)
FROM python:3.12-slim
LABEL org.opencontainers.image.title="FrontierTwin" \
      org.opencontainers.image.authors="Subramoniam AB (SAB)"
WORKDIR /app
COPY . /app
RUN rm -rf /app/backups
EXPOSE 8080
VOLUME ["/app/data"]
CMD ["python3", "ft.py", "serve", "--host", "0.0.0.0", "--port", "8080"]
