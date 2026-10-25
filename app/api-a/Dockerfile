FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
USER 65534
EXPOSE 8080
# keep-alive 接続の終了待ちで Pod の停止が 30 秒かかるため、待ちを短くする
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--timeout-graceful-shutdown", "5"]
