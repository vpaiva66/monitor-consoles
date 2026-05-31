"""Ajuda a configurar o Telegram: descobre seu chat_id e testa o envio.

Pré-requisitos:
  1. Crie um bot com o @BotFather e copie o token.
  2. Coloque o token em TELEGRAM_BOT_TOKEN no arquivo .env.
  3. No Telegram, ABRA seu bot e mande qualquer mensagem (ex: "oi").
  4. Rode:  python setup_telegram.py

O script lê as mensagens recentes do bot (getUpdates), mostra o chat_id de
quem falou com ele, e envia uma mensagem de teste para confirmar.
"""
from __future__ import annotations

import os
import sys

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, **params):
    r = httpx.get(API.format(token=token, method=method), params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data["result"]


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN não está no .env. Preencha e rode de novo.")
        sys.exit(1)

    # Confirma que o token é válido e mostra o nome do bot.
    try:
        me = _call(token, "getMe")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Token inválido ou erro de rede: {e}")
        sys.exit(1)
    print(f"✅ Bot conectado: @{me['username']} ({me['first_name']})")

    # Descobre o chat_id a partir das mensagens recebidas.
    chat_env = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    updates = _call(token, "getUpdates")
    chats = {}
    for u in updates:
        msg = u.get("message") or u.get("edited_message")
        if msg and "chat" in msg:
            c = msg["chat"]
            nome = c.get("title") or " ".join(
                filter(None, [c.get("first_name"), c.get("last_name")])
            ) or c.get("username") or "?"
            chats[c["id"]] = nome

    if not chats and not chat_env:
        print("\n⚠️  Nenhuma conversa encontrada.")
        print("   Abra seu bot no Telegram, mande uma mensagem (ex: 'oi') e rode de novo.")
        sys.exit(1)

    if chats:
        print("\nConversas encontradas (use o chat_id no .env):")
        for cid, nome in chats.items():
            print(f"   chat_id = {cid}   ({nome})")

    # Define o destino do teste: .env tem prioridade; senão o 1º descoberto.
    target = chat_env or str(next(iter(chats)))
    print(f"\nEnviando mensagem de teste para chat_id={target} ...")
    try:
        _call(token, "sendMessage", chat_id=target,
              text="✅ Monitor de consoles conectado! Você receberá os alertas aqui.")
        print("✅ Mensagem enviada! Confira seu Telegram.")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Falha ao enviar: {e}")
        print("   Verifique se você JÁ mandou uma mensagem ao bot primeiro.")
        sys.exit(1)

    if not chat_env:
        print(f"\n👉 Agora adicione no .env:  TELEGRAM_CHAT_ID={target}")


if __name__ == "__main__":
    main()
