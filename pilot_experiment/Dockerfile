FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY baseline_judge.py traces_50.jsonl ./

# Weights (~5 GB) are downloaded on first run into /data/hf; mount /data to keep them and the results.
VOLUME ["/data"]
ENTRYPOINT ["python", "baseline_judge.py"]
CMD ["run", "--model", "openbmb/MiniCPM5-2B", "--results", "/data/out/baseline_results.jsonl"]
