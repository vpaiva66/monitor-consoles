# Monitor de preços de consoles (OLX → Telegram)

Sistema que varre anúncios de consoles na OLX (região de Belo Horizonte/MG),
guarda o histórico de preços e **avisa no Telegram** quando surge um anúncio com
preço bem abaixo da mediana do modelo.

## Como funciona

```
collectors/olx.py  →  core/normalize.py  →  core/storage.py  →  core/detector.py  →  notify/telegram.py
   (Playwright)         (classifica         (SQLite:           (mediana ± IQR)        (alerta)
                         modelo, filtra      histórico de
                         acessórios)         preços)
```

- **Coleta**: navegador real (Playwright) por causa do anti-bot da OLX (HTTP cru dá 403).
- **Detecção**: um anúncio é "oportunidade" se `preço < mediana − k·IQR`, com mínimo
  de amostras (aquecimento) e piso anti-cilada (ignora barato demais = golpe/peça).
- **Aquecimento**: os primeiros dias só acumulam dados; os alertas ficam confiáveis
  depois que cada modelo tem amostras suficientes (`min_samples` no config).

## Instalação (local)

```bash
cd monitor-consoles
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # baixa o navegador
```

## Configuração

Edite `config.yaml`: região, lista de buscas, sensibilidade (`detector`) e o
Telegram. Para ativar os alertas:

1. Crie um bot com o **@BotFather** → copie o `bot_token`.
2. Descubra seu `chat_id` com o **@userinfobot**.
3. Preencha `telegram.bot_token` / `telegram.chat_id` e ponha `telegram.enabled: true`.

## Uso

```bash
python main.py            # uma varredura (bom para testar)
python main.py --debug    # mostra a estrutura do JSON da OLX (ajuste de parser)
python scheduler.py       # modo 24/7: roda agora e repete a cada interval_minutes
```

## Deploy no VPS

### Opção A — Docker Compose (recomendado)

No VPS, com Docker + Docker Compose instalados:

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
- A imagem instala o Google Chrome (`playwright install chrome`) para casar com
  `collector.browser_channel: "chrome"`.

### Opção B — systemd (sem Docker)

Se preferir rodar direto no host (ver `deploy/monitor-consoles.service`):

```bash
sudo mkdir -p /opt/monitor-consoles && sudo chown $USER /opt/monitor-consoles
rsync -a --exclude .venv --exclude data ./ /opt/monitor-consoles/
cd /opt/monitor-consoles
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chrome                 # ou: playwright install chromium

cp .env.example .env                      # preencha as credenciais
sudo cp deploy/monitor-consoles.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-consoles
journalctl -u monitor-consoles -f         # logs ao vivo
```

## Pontos de atenção

- A estrutura do `__NEXT_DATA__` da OLX pode mudar; rode `--debug` se a coleta vier
  vazia e ajuste o mapeamento em `collectors/olx.py`.
- Se começar a tomar 403 mesmo com Playwright, o próximo passo é plugar um **proxy
  residencial** na criação do `context` (em `_fetch_html`).
- Scraping contra os Termos de Uso da OLX; mantenha volume baixo e intervalos com folga.
```
