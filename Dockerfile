# Imagem oficial do Playwright já traz dependências de sistema do navegador.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# tzdata: necessário para TZ=America/Sao_Paulo resolver (zoneinfo).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala o Google Chrome (canal "chrome"), pois o config.yaml usa
# collector.browser_channel: "chrome". Assim o comportamento no VPS é idêntico
# ao da máquina local.
RUN playwright install chrome

COPY . .

# O banco fica em /app/data — monte um volume aqui para persistir o histórico.
VOLUME ["/app/data"]

CMD ["python", "scheduler.py"]
