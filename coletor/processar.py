"""Transforma os dados brutos em um resumo por cidade + alertas automáticos.

Uso:  python coletor/processar.py
Saída: site/dados/<cidade>.json  (lido pelo painel)  e  site/dados/cidades.json

IMPORTANTE: os alertas são INDÍCIOS para orientar a fiscalização cidadã.
Não provam irregularidade: cada um traz o motivo e os empenhos de origem
para que qualquer pessoa confira no documento oficial.
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "site" / "dados"

# A API do TCE-SP usa estes nomes de campo; os alternativos cobrem variações.
CAMPOS = {
    "orgao": ["orgao", "ds_orgao"],
    "mes": ["mes", "mes_referencia"],
    "evento": ["evento", "tp_evento", "ds_evento"],
    "empenho": ["nr_empenho", "numero_empenho"],
    "doc": ["id_fornecedor", "cpf_cnpj", "nr_documento"],
    "fornecedor": ["nm_fornecedor", "fornecedor", "nome_fornecedor"],
    "data": ["dt_emissao_despesa", "data", "dt_despesa"],
    "valor": ["vl_despesa", "valor", "vl_evento"],
    # receitas
    "fonte": ["ds_fonte_recurso", "fonte_recurso"],
    "categoria": ["ds_alinea", "ds_categoria", "alinea"],
    "valor_receita": ["vl_arrecadacao", "valor_arrecadado", "vl_receita"],
}

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def campo(reg: dict, nome: str, padrao=""):
    for k in CAMPOS[nome]:
        if k in reg and reg[k] not in (None, ""):
            return reg[k]
    return padrao


def num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    if "," in s:  # formato brasileiro 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def mes_num(v) -> int:
    if isinstance(v, int):
        return v
    s = str(v).strip().lower()
    if s.isdigit():
        return int(s)
    for i, m in enumerate(MESES):
        if s.startswith(m):
            return i + 1
    return 0


def tipo_evento(ev: str) -> str:
    e = str(ev).lower()
    if "anula" in e or "estorno" in e:
        return "anulacao"
    if "pag" in e:
        return "pago"
    if "liquid" in e:
        return "liquidado"
    if "empenh" in e or "refor" in e:
        return "empenhado"
    return "outro"


def mascarar(doc: str) -> str:
    d = re.sub(r"\D", "", str(doc))
    if len(d) == 11:  # CPF: pessoa física, LGPD -> mascara
        return f"***.{d[3:6]}.{d[6:9]}-**"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return str(doc)


def ler_lista(arquivo: Path):
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if isinstance(dados, dict):  # algumas respostas vêm embrulhadas
        for v in dados.values():
            if isinstance(v, list):
                return v
        return []
    return dados


def processar_cidade(slug: str, nome: str, limites: dict):
    pasta = RAIZ / "dados" / slug
    desp, rec = [], []
    for arq in sorted(pasta.glob("*/despesas-*.json")):
        ano = int(arq.parent.name)
        for r in ler_lista(arq):
            desp.append({
                "ano": ano,
                "mes": mes_num(campo(r, "mes")) or int(arq.stem.split("-")[1]),
                "orgao": str(campo(r, "orgao", "Não informado")).strip(),
                "tipo": tipo_evento(campo(r, "evento")),
                "empenho": str(campo(r, "empenho")).strip(),
                "doc": re.sub(r"\D", "", str(campo(r, "doc"))),
                "fornecedor": str(campo(r, "fornecedor", "Não informado")).strip().upper(),
                "data": str(campo(r, "data")),
                "valor": num(campo(r, "valor", 0)),
            })
    for arq in sorted(pasta.glob("*/receitas-*.json")):
        ano = int(arq.parent.name)
        for r in ler_lista(arq):
            rec.append({
                "ano": ano,
                "mes": mes_num(campo(r, "mes")) or int(arq.stem.split("-")[1]),
                "fonte": str(campo(r, "fonte", "Não informada")).strip(),
                "categoria": str(campo(r, "categoria", "Não informada")).strip(),
                "valor": num(campo(r, "valor_receita", 0)),
            })

    anos = sorted({d["ano"] for d in desp} | {r["ano"] for r in rec})
    por_ano = {}
    for ano in anos:
        d_ano = [d for d in desp if d["ano"] == ano]
        r_ano = [r for r in rec if r["ano"] == ano]
        por_ano[str(ano)] = resumo_ano(d_ano, r_ano, limites.get(ano, 62725.59))

    return {
        "slug": slug,
        "nome": nome,
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "fonte": "Tribunal de Contas do Estado de São Paulo — Portal da Transparência Municipal (Audesp)",
        "fonte_url": "https://transparencia.tce.sp.gov.br/",
        "anos": por_ano,
    }


def soma(itens, chave="valor"):
    return round(sum(i[chave] for i in itens), 2)


def resumo_ano(desp, rec, limite):
    emp = [d for d in desp if d["tipo"] == "empenhado"]
    anul = [d for d in desp if d["tipo"] == "anulacao"]
    pago = [d for d in desp if d["tipo"] == "pago"]

    por_mes = []
    for m in range(1, 13):
        por_mes.append({
            "mes": MESES[m - 1],
            "empenhado": round(soma([d for d in emp if d["mes"] == m]) - sum(abs(d["valor"]) for d in anul if d["mes"] == m), 2),
            "pago": soma([d for d in pago if d["mes"] == m]),
            "receita": soma([r for r in rec if r["mes"] == m]),
        })

    forn = defaultdict(lambda: {"pago": 0.0, "empenhado": 0.0, "anulado": 0.0, "n": 0, "nome": "", "orgaos": set()})
    for d in desp:
        chave = d["doc"] or d["fornecedor"]
        f = forn[chave]
        f["nome"] = d["fornecedor"]
        f["orgaos"].add(d["orgao"])
        if d["tipo"] == "pago":
            f["pago"] += d["valor"]
        elif d["tipo"] == "empenhado":
            f["empenhado"] += d["valor"]
            f["n"] += 1
        elif d["tipo"] == "anulacao":
            f["anulado"] += abs(d["valor"])
    total_pago = soma(pago) or 1.0
    top = sorted(forn.items(), key=lambda kv: kv[1]["pago"], reverse=True)[:50]
    top_fornecedores = [{
        "doc": mascarar(k), "nome": v["nome"], "pago": round(v["pago"], 2),
        "empenhado": round(v["empenhado"], 2), "empenhos": v["n"],
        "participacao": round(100 * v["pago"] / total_pago, 2),
        "pessoa_fisica": len(k) == 11,
    } for k, v in top]

    orgaos = defaultdict(float)
    for d in pago:
        orgaos[d["orgao"]] += d["valor"]
    por_orgao = sorted(({"orgao": k, "pago": round(v, 2)} for k, v in orgaos.items()), key=lambda x: -x["pago"])

    fontes = defaultdict(float)
    for r in rec:
        fontes[r["fonte"]] += r["valor"]
    categorias = defaultdict(float)
    for r in rec:
        categorias[r["categoria"]] += r["valor"]

    return {
        "totais": {
            "empenhado": round(soma(emp) - sum(abs(d["valor"]) for d in anul), 2),
            "pago": soma(pago),
            "receita": soma(rec),
            "fornecedores": len(forn),
            "empenhos": len(emp),
        },
        "por_mes": por_mes,
        "top_fornecedores": top_fornecedores,
        "por_orgao": por_orgao,
        "receita_por_fonte": sorted(({"fonte": k, "valor": round(v, 2)} for k, v in fontes.items()), key=lambda x: -x["valor"]),
        "receita_por_categoria": sorted(({"categoria": k, "valor": round(v, 2)} for k, v in categorias.items()), key=lambda x: -x["valor"])[:30],
        "alertas": gerar_alertas(desp, forn, por_mes, limite, total_pago),
    }


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_alertas(desp, forn, por_mes, limite, total_pago):
    alertas = []
    emp = [d for d in desp if d["tipo"] == "empenhado"]

    # 1) Possível fracionamento: vários empenhos pequenos, mesmo fornecedor, mesmo mês,
    #    que somados passam o limite de dispensa.
    grupos = defaultdict(list)
    for d in emp:
        if 0 < d["valor"] < limite:
            grupos[(d["doc"] or d["fornecedor"], d["mes"])].append(d)
    for (chave, mes), itens in grupos.items():
        total = soma(itens)
        if len(itens) >= 3 and total > limite:
            alertas.append({
                "tipo": "fracionamento", "gravidade": "media" if total < 2 * limite else "alta",
                "titulo": f"{len(itens)} empenhos abaixo do limite de dispensa somam {brl(total)}",
                "fornecedor": itens[0]["fornecedor"], "doc": mascarar(chave), "mes": MESES[mes - 1],
                "explicacao": (f"No mesmo mês, este fornecedor recebeu {len(itens)} empenhos, cada um abaixo de "
                               f"{brl(limite)} (limite de dispensa), mas que somados passam do limite. "
                               "Pode ser normal (ex.: entregas de uma ata de registro de preços já licitada) "
                               "ou indicar divisão de compra para evitar licitação. Confira a modalidade de cada empenho."),
                "empenhos": sorted({i["empenho"] for i in itens})[:20],
                "valor": total,
            })

    # 2) Concentração: um fornecedor com fatia grande de tudo que foi pago.
    for chave, f in forn.items():
        part = 100 * f["pago"] / total_pago
        if part >= 5 and len(chave) != 11:
            alertas.append({
                "tipo": "concentracao", "gravidade": "alta" if part >= 15 else "media",
                "titulo": f"{f['nome']} recebeu {str(round(part, 1)).replace('.', ',')}% de tudo que foi pago",
                "fornecedor": f["nome"], "doc": mascarar(chave), "valor": round(f["pago"], 2),
                "explicacao": ("Concentração alta não é irregular por si só (folha, INSS, concessionárias e "
                               "contratos de saúde costumam liderar), mas merece olhar o contrato e a licitação de origem."),
            })

    # 3) Anulações altas: muito empenho cancelado depois.
    for chave, f in forn.items():
        if f["empenhado"] > limite and f["anulado"] / f["empenhado"] > 0.3:
            alertas.append({
                "tipo": "anulacoes", "gravidade": "baixa",
                "titulo": f"{100 * f['anulado'] / f['empenhado']:.0f}% do valor empenhado para {f['nome']} foi anulado",
                "fornecedor": f["nome"], "doc": mascarar(chave), "valor": round(f["anulado"], 2),
                "explicacao": "Anulações frequentes podem indicar planejamento ruim ou empenhos 'reservando' dinheiro sem uso real.",
            })

    # 4) Pico de fim de ano: dezembro muito acima da média dos outros meses.
    meses_com_dado = [m["empenhado"] for m in por_mes[:11] if m["empenhado"] > 0]
    if meses_com_dado and por_mes[11]["empenhado"] > 0:
        media = sum(meses_com_dado) / len(meses_com_dado)
        if por_mes[11]["empenhado"] > 2 * media:
            alertas.append({
                "tipo": "pico_dezembro", "gravidade": "media",
                "titulo": f"Empenhos de dezembro foram {str(round(por_mes[11]['empenhado'] / media, 1)).replace('.', ',')}x a média do ano",
                "valor": por_mes[11]["empenhado"],
                "explicacao": "Gasto concentrado no fim do ano pode indicar pressa para 'usar o orçamento'. Vale ver o que foi comprado.",
            })

    # 5) Fornecedor que só aparece em um mês e leva valor alto.
    meses_forn = defaultdict(set)
    valor_forn = defaultdict(float)
    for d in emp:
        k = d["doc"] or d["fornecedor"]
        meses_forn[k].add(d["mes"])
        valor_forn[k] += d["valor"]
    for k, ms in meses_forn.items():
        if len(ms) == 1 and valor_forn[k] > 5 * limite and len(k) != 11:
            alertas.append({
                "tipo": "fornecedor_pontual", "gravidade": "baixa",
                "titulo": f"{forn[k]['nome']} aparece em um único mês com {brl(valor_forn[k])}",
                "fornecedor": forn[k]["nome"], "doc": mascarar(k), "valor": round(valor_forn[k], 2),
                "explicacao": "Contratação pontual de valor alto. Confira na Receita Federal a data de abertura e a atividade da empresa (CNPJ).",
            })

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    alertas.sort(key=lambda a: (ordem[a["gravidade"]], -a.get("valor", 0)))
    return alertas[:200]


def main():
    cfg = yaml.safe_load((RAIZ / "cidades.yaml").read_text(encoding="utf-8"))
    limites = {int(k): float(v) for k, v in cfg.get("limite_dispensa", {}).items()}
    SAIDA.mkdir(parents=True, exist_ok=True)
    indice = []
    for c in cfg["cidades"]:
        if not (RAIZ / "dados" / c["slug"]).exists():
            print(f"(sem dados ainda para {c['nome']})")
            continue
        res = processar_cidade(c["slug"], c["nome"], limites)
        (SAIDA / f"{c['slug']}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        indice.append({"slug": c["slug"], "nome": c["nome"]})
        print(f"✓ {c['nome']}: {sum(len(a['alertas']) for a in res['anos'].values())} alertas")
    (SAIDA / "cidades.json").write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
