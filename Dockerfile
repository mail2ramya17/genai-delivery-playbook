FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY copilot ./copilot
COPY data ./data
USER app
ENV LLM_PROVIDER=mock AUDIT_LOG=/tmp/audit.jsonl
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
