FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && useradd --uid 1000 --create-home masp && mkdir /data && chown masp /data
USER masp
ENV MASP_HOME=/data
EXPOSE 3080
CMD ["uvicorn", "masp.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "3080"]
