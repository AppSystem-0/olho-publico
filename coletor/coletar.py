"""Baixa despesas e receitas das cidades configuradas na API aberta do TCE-SP.

Uso:  python coletor/coletar.py            (todas as cidades/anos do cidades.yaml)
      python coletor/coletar.py leme 2026  (uma cidade, um ano)

Saída: dados/<cidade>/<ano>/<tipo>-<mes>.json.gz  (dados brutos compactados, um por mês)
       dados/cidades.json                         (cidades com o identificador resolvido)

API documentada em https://transparencia.tce.sp.gov.br/ (menu "APIs").
Formato: /api/json/{despesas|receitas}/{municipio}/{exercicio}/{mes}
"""
import gzip
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
BASE = "https://transparencia.tce.sp.gov.br/api/json"
TIPOS = ("despesas", "receitas")
SESSAO = requests.Session()
SESSAO.headers["User-Agent"] = "olho-publico/1.0 (+https://github.com/AppSystem-0/olho-publico)"


def normalizar(txt: str) -> str:
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def slugify(txt: str) -> str:
    return normalizar(txt).replace(" ", "-")


def get_json(url: str, tentativas: int = 4):
    for i in range(tentativas):
        try:
            r = SESSAO.get(url, timeout=180)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  ! {url} falhou ({e}); tentativa {i + 1}/{tentativas}", flush=True)
            time.sleep(5 * (i + 1))
    return None


def resolver_cidades(cfg):
    """Descobre o identificador de cada cidade pela lista oficial de municípios do TCE."""
    lista = get_json(f"{BASE}/municipios") or []
    mapa = {}
    for item in lista if isinstance(lista, list) else []:
        if not isinstance(item, dict):
            continue
        vals = [str(v) for v in item.values() if isinstance(v, str)]
        slug = next((v for v in vals if re.fullmatch(r"[a-z0-9\-]+", v)), None)
        for v in vals:
            if slug:
                mapa[normalizar(v)] = slug
    resolvidas = []
    for c in cfg["cidades"]:
        slug = c.get("slug") or mapa.get(normalizar(c["nome"])) or slugify(c["nome"])
        resolvidas.append({"slug": slug, "nome": c["nome"]})
    print("Cidades:", ", ".join(f"{c['nome']}={c['slug']}" for c in resolvidas), flush=True)
    return resolvidas


def meses_do_ano(ano: int):
    hoje = date.today()
    ultimo = 12 if ano < hoje.year else hoje.month
    return range(1, ultimo + 1)


def coletar(cidade: str, ano: int, forcar_meses_recentes: int = 2):
    hoje = date.today()
    baixados = 0
    for mes in meses_do_ano(ano):
        for tipo in TIPOS:
            destino = RAIZ / "dados" / cidade / str(ano) / f"{tipo}-{mes:02d}.json.gz"
            recente = ano == hoje.year and mes > hoje.month - forcar_meses_recentes
            if destino.exists() and not recente:
                continue  # meses fechados não mudam: não baixa de novo
            dados = get_json(f"{BASE}/{tipo}/{cidade}/{ano}/{mes}")
            if dados is None:
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(destino, "wt", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False)
            baixados += 1
            time.sleep(0.5)  # gentileza com o servidor do TCE
    print(f"→ {cidade} {ano}: {baixados} arquivos novos/atualizados", flush=True)


def main():
    cfg = yaml.safe_load((RAIZ / "cidades.yaml").read_text(encoding="utf-8"))
    cidades = resolver_cidades(cfg)
    (RAIZ / "dados").mkdir(exist_ok=True)
    (RAIZ / "dados" / "cidades.json").write_text(json.dumps(cidades, ensure_ascii=False), encoding="utf-8")
    if len(sys.argv) >= 3:
        alvos = [(sys.argv[1], int(sys.argv[2]))]
    else:
        alvos = [(c["slug"], a) for c in cidades for a in cfg["anos"]]
    for cidade, ano in alvos:
        coletar(cidade, ano)


if __name__ == "__main__":
    main()
