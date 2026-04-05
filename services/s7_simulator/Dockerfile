FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/s7_simulator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY services ./services

EXPOSE 1102

CMD ["python", "-m", "services.s7_simulator.main"]
