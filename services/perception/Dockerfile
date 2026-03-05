FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library
COPY shared/python /app/shared/python
ENV PYTHONPATH=/app/shared/python:$PYTHONPATH

# Copy service
COPY services/perception /app/services/perception

EXPOSE 8730

CMD ["uvicorn", "services.perception.main:app", "--host", "0.0.0.0", "--port", "8730"]
