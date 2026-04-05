FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY services ./services

EXPOSE 4840

CMD ["python", "-m", "services.gateway.main"]
