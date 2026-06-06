FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chrome

COPY . .

VOLUME ["/app/data"]

CMD ["python", "scheduler.py"]
