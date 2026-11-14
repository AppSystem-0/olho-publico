"""Sonda a API do Siconfi (Tesouro Nacional) para descobrir o formato dos dados. Uso pontual."""
import collections, json, sys, requests
B = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
def get(path, **p):
    r = requests.get(f"{B}/{path}", params=p, timeout=300); print("GET", r.url, r.status_code, flush=True)
    r.raise_for_status(); return r.json()
entes = get("entes")["items"]
sp = [e for e in entes if e.get("uf") == "SP" and "leme" == str(e.get("ente", "")).lower()]
print("ENTE:", json.dumps(sp, ensure_ascii=False))
print("CAMPOS ENTE:", list(entes[0].keys()))
ibge = sp[0]["cod_ibge"]
for ano, per in [(2025, 6), (2026, 4)]:
    for anexo in ["RREO-Anexo 01", "RREO-Anexo 08", "RREO-Anexo 12", "RREO-Anexo 03"]:
        try:
            it = get("rreo", an_exercicio=ano, nr_periodo=per, co_tipo_demonstrativo="RREO", no_anexo=anexo, co_esfera="M", id_ente=ibge)["items"]
        except Exception as e:
            print("ERRO", ano, anexo, e); continue
        print(f"\n===== {ano} bim {per} {anexo}: {len(it)} linhas")
        if it: print("CAMPOS:", list(it[0].keys()))
        print("COLUNAS:", sorted({i.get("coluna") for i in it}))
        for i in it:
            c = str(i.get("conta", "")); col = str(i.get("coluna", ""))
            if any(k in c.upper() for k in ["TOTAL", "RECEITAS (", "DESPESAS (", "PERCENTUAL", "APLICAD", "%"]) or "%" in col:
                print(f"  [{i.get('cod_conta')}] {c[:110]} | {col[:60]} | {i.get('valor')}")
