FROM python:3.12-slim

WORKDIR /app

COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/python /tmp/shared
RUN pip install --no-cache-dir /tmp/shared && rm -rf /tmp/shared

COPY services/gateway/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
