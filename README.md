# Monitor de preços de consoles (OLX → Telegram)

Sistema que varre anúncios de consoles na OLX (região de Belo Horizonte/MG),
guarda o histórico de preços e **avisa no Telegram** quando surge um anúncio com
preço bem abaixo da mediana do modelo/variante.

## Como funciona

```
collectors/olx.py  →  core/llm_classify.py  →  core/storage.py  →  core/detector.py  →  notify/telegram.py
   (Playwright)         (Claude Haiku:           (SQLite:           (mediana ± IQR        (alerta)
                         modelo + variante)       histórico)         por variante)
```

- **Coleta**: navegador real (Playwright) por causa do anti-bot da OLX (HTTP cru dá 403).
- **Classificação**: Claude Haiku lê o título e define modelo + variante (Slim/Pro/OLED…);
  fallback para regex se faltar API key. Só os anúncios inéditos vão à LLM (economia).
- **Detecção**: um anúncio é "oportunidade" se `preço < mediana − k·IQR`, comparando
  variante-com-variante (com fallback para o modelo inteiro), com mínimo de amostras
  (aquecimento) e piso anti-cilada (ignora barato demais = golpe/peça).
- **Aquecimento**: os primeiros dias só acumulam dados; os alertas ficam confiáveis
  depois que cada modelo/variante tem amostras suficientes (`min_samples` no config).

## Instalação (local)

```bash
cd monitor-consoles
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chrome             # ou: playwright install chromium
cp .env.example .env                  # preencha ANTHROPIC_API_KEY e TELEGRAM_*
```

## Configuração

- `config.yaml`: região, lista de buscas, sensibilidade (`detector`), intervalo do
  scheduler e retenção do banco.
- `.env`: credenciais (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

Telegram: crie um bot com o **@BotFather**, coloque o token no `.env` e rode
`python setup_telegram.py` para descobrir o `chat_id` e testar o envio.

## Uso

```bash
python main.py            # uma varredura (bom para testar)
python main.py --debug    # mostra a estrutura do JSON da OLX (ajuste de parser)
python scheduler.py       # modo 24/7: roda agora e repete a cada interval_minutes
python test_alert.py      # envia um alerta fictício para validar o Telegram
```

## Deploy no VPS

### Opção A — Docker Compose (recomendado)

```bash
git clone <seu-repo> monitor-consoles   # ou copie a pasta via scp/rsync
cd monitor-consoles
cp .env.example .env                     # e preencha as credenciais reais
docker compose up -d --build             # builda e sobe em background

docker compose logs -f                   # acompanha os logs ao vivo
docker compose restart                   # reinicia
docker compose down                      # para
```

- O `.env` injeta as credenciais; o volume `./data` preserva o banco entre reinícios.
- `restart: unless-stopped` faz o serviço voltar sozinho após reboot do VPS.
- `shm_size: 1gb` evita que o Chrome quebre (SIGSEGV) por falta de memória compartilhada.

### Opção B — systemd (sem Docker)

Ver `deploy/monitor-consoles.service`:

```bash
sudo mkdir -p /opt/monitor-consoles && sudo chown $USER /opt/monitor-consoles
rsync -a --exclude .venv --exclude data ./ /opt/monitor-consoles/
cd /opt/monitor-consoles
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chrome

cp .env.example .env                      # preencha as credenciais
sudo cp deploy/monitor-consoles.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-consoles
journalctl -u monitor-consoles -f         # logs ao vivo
```

## Pontos de atenção

- A estrutura do `__NEXT_DATA__` da OLX pode mudar; rode `--debug` se a coleta vier
  vazia e ajuste o mapeamento em `collectors/olx.py`.
- Se o Chrome cair (SIGSEGV) no VPS, é quase sempre memória: o `shm_size` e os
  retries (`collector.max_retries`) ajudam; um VPS com ≥ 1 GB de RAM é recomendado.
- Se começar a tomar 403 mesmo com Playwright, plugue um **proxy residencial** na
  criação do contexto (em `_new_context`, `collectors/olx.py`).
- Scraping contra os Termos de Uso da OLX; mantenha volume baixo e intervalos com folga.
