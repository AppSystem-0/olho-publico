"""Baixa despesas e receitas das cidades configuradas na API aberta do TCE-SP.

Uso:  python coletor/coletar.py            (todas as cidades/anos do cidades.yaml)
      python coletor/coletar.py leme 2026  (uma cidade, um ano)

Saída: dados/<cidade>/<ano>/<tipo>-<mes>.json  (dados brutos, um arquivo por mês)

API documentada em https://transparencia.tce.sp.gov.br/ (menu "APIs").
Formato: /api/json/{despesas|receitas}/{municipio}/{exercicio}/{mes}
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
BASE = "https://transparencia.tce.sp.gov.br/api/json"
TIPOS = ("despesas", "receitas")


def baixar(tipo: str, cidade: str, ano: int, mes: int, tentativas: int = 3):
    url = f"{BASE}/{tipo}/{cidade}/{ano}/{mes}"
    for i in range(tentativas):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": "olho-publico/1.0"})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  ! {url} falhou ({e}); tentativa {i + 1}/{tentativas}")
            time.sleep(5 * (i + 1))
    return None


def meses_do_ano(ano: int):
    hoje = date.today()
    ultimo = 12 if ano < hoje.year else hoje.month
    return range(1, ultimo + 1)


def coletar(cidade: str, ano: int, forcar_meses_recentes: int = 2):
    hoje = date.today()
    for mes in meses_do_ano(ano):
        for tipo in TIPOS:
            destino = RAIZ / "dados" / cidade / str(ano) / f"{tipo}-{mes:02d}.json"
            recente = ano == hoje.year and mes > hoje.month - forcar_meses_recentes
            if destino.exists() and not recente:
                continue  # meses fechados não mudam: não baixa de novo
            print(f"→ {cidade} {tipo} {mes:02d}/{ano}")
            dados = baixar(tipo, cidade, ano, mes)
            if dados is None:
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            time.sleep(1)  # gentileza com o servidor do TCE


def main():
    cfg = yaml.safe_load((RAIZ / "cidades.yaml").read_text(encoding="utf-8"))
    if len(sys.argv) >= 3:
        alvos = [(sys.argv[1], int(sys.argv[2]))]
    else:
        alvos = [(c["slug"], a) for c in cfg["cidades"] for a in cfg["anos"]]
    for cidade, ano in alvos:
        coletar(cidade, ano)


if __name__ == "__main__":
    main()
