from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from core.models import Listing
from core import normalize as regex_normalize

log = logging.getLogger("llm.classify")

_NENHUM = "NENHUM"
_DESCONHECIDO = "DESCONHECIDO"

VARIANTS: Dict[str, List[str]] = {
    "Nintendo 3DS":    ["3DS", "3DS XL", "New 3DS", "New 3DS XL", "2DS", "New 2DS XL"],
    "Nintendo DS":     ["DS", "DS Lite", "DSi", "DSi XL"],
    "Nintendo Switch": ["V1/V2", "OLED", "Lite"],
    "Xbox 360":        ["Fat", "Slim", "Super Slim"],
    "Xbox One":        ["Fat", "One S", "One X"],
    "Xbox Series":     ["Series S", "Series X"],
    "PS5":             ["Fat", "Slim", "Digital", "Pro"],
    "PS4":             ["Fat", "Slim", "Pro"],
    "PS3":             ["Fat", "Slim", "Super Slim"],
    "PS Vita":         ["Fat", "Slim"],
    "PSP":             ["1000", "2000", "3000", "Go"],
}


def _all_variants() -> List[str]:
    seen, out = set(), []
    for vs in VARIANTS.values():
        for v in vs:
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


def _build_system(valid_models: List[str]) -> str:
    linhas = []
    for m in valid_models:
        vs = ", ".join(VARIANTS.get(m, [])) or "(sem variantes)"
        linhas.append(f"  - {m}  ->  variantes: {vs}")
    catalogo = "\n".join(linhas)
    return (
        "Você classifica anúncios de marketplace (OLX) por modelo e variante de "
        "console.\n"
        "Receberá uma lista numerada de TÍTULOS. Para cada um, devolva o console e "
        "a variante. Consoles e variantes possíveis:\n"
        f"{catalogo}\n\n"
        "Regras:\n"
        f"- Se NÃO for um desses consoles, ou for acessório (controle, capa, cabo, "
        f"fonte, headset), JOGO/mídia, peça/conserto ou só a caixa: model = "
        f"\"{_NENHUM}\".\n"
        "- Um console à venda 'com 2 controles', 'com jogos' ou 'com cartão' AINDA É "
        "o console — classifique pelo console.\n"
        f"- VARIANTE: escolha uma da lista do modelo APENAS se o título deixar claro. "
        f"Se o título não disser a variante, use \"{_DESCONHECIDO}\" — isso é comum e "
        f"esperado, não invente.\n"
        "- 'PS4 Slim', 'PS4 Pro', 'PS5 Digital', 'Switch OLED', '3DS XL' são pistas "
        "explícitas de variante. 'PS4' sozinho, sem mais nada, é variante "
        f"\"{_DESCONHECIDO}\".\n"
        "- Cuidado: 'Nintendo DS' ≠ 'Nintendo 3DS'; 'PS4' ≠ 'PS5'.\n"
        "- Cuidado: 'Xbox One X' é Xbox One (variante One X), NÃO é Xbox Series X. "
        "'Xbox Series S/X' é a geração seguinte (Xbox Series).\n"
        "- Responda SEMPRE chamando a ferramenta classify_listings, um item por "
        "índice recebido."
    )


_TOOL_NAME = "classify_listings"


def _build_tool(valid_models: List[str]) -> dict:
    return {
        "name": _TOOL_NAME,
        "description": "Registra modelo e variante de cada anúncio por índice.",
        "input_schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "model": {
                                "type": "string",
                                "enum": valid_models + [_NENHUM],
                            },
                            "variant": {
                                "type": "string",
                                "enum": _all_variants() + [_DESCONHECIDO],
                            },
                        },
                        "required": ["index", "model", "variant"],
                    },
                }
            },
            "required": ["results"],
        },
    }


ClassMap = Dict[str, Tuple[Optional[str], Optional[str]]]


class LLMClassifier:
    def __init__(self, model: str, valid_models: List[str],
                 batch_size: int = 40, api_key: Optional[str] = None):
        self.model = model
        self.valid_models = valid_models
        self.batch_size = batch_size
        self._system = _build_system(valid_models)
        self._tool = _build_tool(valid_models)
        self._client = None
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        except Exception as e:
            log.warning("SDK Anthropic indisponível (%s) — usando fallback regex.", e)

    @property
    def available(self) -> bool:
        return self._client is not None

    def _normalize_variant(self, model: str, variant: Optional[str]) -> Optional[str]:
        if variant and variant != _DESCONHECIDO and variant in VARIANTS.get(model, []):
            return variant
        return None

    def _classify_chunk(self, chunk: List[Listing]) -> ClassMap:
        numbered = "\n".join(f"{i}. {l.title}" for i, l in enumerate(chunk))
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=3072,
            system=[{
                "type": "text",
                "text": self._system,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=[{**self._tool, "cache_control": {"type": "ephemeral"}}],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": numbered}],
        )
        tool_block = next((b for b in resp.content if b.type == "tool_use"), None)
        out: ClassMap = {}
        if not tool_block:
            log.warning("Resposta sem tool_use; lote não classificado.")
            return out
        for item in tool_block.input.get("results", []):
            idx, model = item.get("index"), item.get("model")
            if not (isinstance(idx, int) and 0 <= idx < len(chunk)):
                continue
            if model == _NENHUM or model not in self.valid_models:
                out[chunk[idx].id] = (None, None)
            else:
                variant = self._normalize_variant(model, item.get("variant"))
                out[chunk[idx].id] = (model, variant)
        return out

    def classify(self, listings: List[Listing]) -> ClassMap:
        result: ClassMap = {}
        for start in range(0, len(listings), self.batch_size):
            chunk = listings[start:start + self.batch_size]
            try:
                result.update(self._classify_chunk(chunk))
            except Exception as e:
                log.warning("Erro no lote LLM (%s) — fallback regex neste lote.", e)
                result.update(regex_fallback(chunk))
        return result


def regex_fallback(listings: List[Listing]) -> ClassMap:
    out: ClassMap = {}
    for l in listings:
        n = regex_normalize.normalize(l)
        out[l.id] = (n.model, None) if n else (None, None)
    return out
