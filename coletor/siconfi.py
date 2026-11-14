"""Baixa os totais oficiais do Tesouro Nacional (Siconfi / RREO Anexo 01 - Balanço Orçamentário)
para conferir os totais calculados a partir dos dados detalhados do TCE-SP.

Uso:  python coletor/siconfi.py
Saída: dados/<cidade>/siconfi-<ano>.json

API: https://apidatalake.tesouro.gov.br/ords/siconfi/tt/ (documentação em apidatalake.tesouro.gov.br/docs/siconfi)
"""
import json
import time
from pathlib import Path

import requests
import yaml

from coletar import RAIZ, normalizar

BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
SESSAO = requests.Session()
SESSAO.headers["User-Agent"] = "olho-publico/1.0 (+https://github.com/AppSystem-0/olho-publico)"

# (cod_conta, coluna) do RREO Anexo 01 que correspondem aos nossos totais
ALVOS = {
    "receita": ("SubtotalDasReceitas", "Até o Bimestre (c)"),
    "empenhado": ("SubtotalDasDespesas", "DESPESAS EMPENHADAS ATÉ O BIMESTRE (f)"),
    "liquidado": ("SubtotalDasDespesas", "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)"),
    "pago": ("SubtotalDasDespesas", "DESPESAS PAGAS ATÉ O BIMESTRE (j)"),
}


def get(path, **params):
    for i in range(3):
        try:
            r = SESSAO.get(f"{BASE}/{path}", params=params, timeout=300)
            r.raise_for_status()
            return r.json().get("items", [])
        except (requests.RequestException, ValueError) as e:
            print(f"  ! Siconfi {path} {params} falhou ({e}); tentativa {i + 1}/3", flush=True)
            time.sleep(10 * (i + 1))
    return None


def totais_rreo(ibge: int, ano: int):
    """Procura o bimestre mais recente publicado e devolve os totais do Balanço Orçamentário."""
    for periodo in range(6, 0, -1):
        itens = get("rreo", an_exercicio=ano, nr_periodo=periodo, co_tipo_demonstrativo="RREO",
                    no_anexo="RREO-Anexo 01", co_esfera="M", id_ente=ibge)
        if not itens:
            continue
        res = {"periodo": periodo, "mes_final": 2 * periodo}
        for nome, (conta, coluna) in ALVOS.items():
            v = next((i["valor"] for i in itens if i.get("cod_conta") == conta and i.get("coluna") == coluna), None)
            res[nome] = v
        res["populacao"] = itens[0].get("populacao")
        if res["receita"] is not None or res["pago"] is not None:
            return res
    return None


def main():
    cfg = yaml.safe_load((RAIZ / "cidades.yaml").read_text(encoding="utf-8"))
    arq_cidades = RAIZ / "dados" / "cidades.json"
    cidades = json.loads(arq_cidades.read_text(encoding="utf-8")) if arq_cidades.exists() else []
    entes = get("entes") or []
    mapa = {normalizar(e["ente"]): e["cod_ibge"] for e in entes if e.get("uf") == "SP" and e.get("esfera") == "M"}
    for c in cidades:
        ibge = mapa.get(normalizar(c["nome"]))
        if not ibge:
            print(f"(Siconfi: {c['nome']} não encontrado)", flush=True)
            continue
        for ano in cfg["anos"]:
            destino = RAIZ / "dados" / c["slug"] / f"siconfi-{ano}.json"
            if destino.exists() and json.loads(destino.read_text()).get("periodo") == 6:
                continue  # ano fechado já conferido
            t = totais_rreo(ibge, ano)
            if not t:
                print(f"(Siconfi: sem RREO de {c['nome']} {ano})", flush=True)
                continue
            t["cod_ibge"] = ibge
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
            print(f"✓ Siconfi {c['nome']} {ano}: {t['periodo']}º bimestre", flush=True)


if __name__ == "__main__":
    main()
