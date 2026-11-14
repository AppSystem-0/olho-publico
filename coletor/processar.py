"""Transforma os dados brutos em um resumo por cidade + alertas automáticos.

Uso:  python coletor/processar.py
Saída: site/dados/<cidade>.json  (lido pelo painel)  e  site/dados/cidades.json

IMPORTANTE: os alertas são INDÍCIOS para orientar a fiscalização cidadã.
Não provam irregularidade: cada um traz o motivo e os empenhos de origem
para que qualquer pessoa confira no documento oficial.
"""
import gzip
import html
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


# Entes públicos, previdência, encargos e bancos: aparecem como "fornecedor" mas são
# folha, repasses ou tributos. Ficam fora dos alertas de concentração/fracionamento.
ENTES_PUBLICOS = re.compile(
    r"PREFEITURA|MUNICIPIO DE|CAMARA MUNICIPAL|C[ÂA]MARA MUNICIPAL|PREVID|RPPS|INSS|I\.N\.S\.S|"
    r"SEGURIDADE|CAIXA EC|BANCO DO BRASIL|TRIBUNAL|MINIST[EÉ]RIO|RECEITA FEDERAL|FGTS|PASEP|"
    r"SUPERINT|SAECIL|SAAE|CONS[OÓ]RCIO INTERMUN|CONS\.INTERMUN|FUNDO MUNICIPAL|FUNDO NACIONAL|"
    r"SECRETARIA DA FAZENDA|ESTADO DE S[AÃ]O PAULO|UNI[AÃ]O FEDERAL|DEPARTAMENTO ESTADUAL|DETRAN",
    re.I,
)


# Concessionárias de serviço público (tarifa regulada, contratação sem licitação por natureza).
CONCESSIONARIAS = re.compile(
    r"ELEKTRO|CPFL|ENEL|SABESP|COMG[AÁ]S|TELEF[OÔ]NICA|TELEFONICA|VIVO|CLARO S|\bOI S|EMBRATEL|CORREIOS|EMPRESA BRASILEIRA DE CORREIOS",
    re.I,
)


def eh_ente_publico(nome: str) -> bool:
    return bool(ENTES_PUBLICOS.search(nome or ""))


def eh_concessionaria(nome: str) -> bool:
    return bool(CONCESSIONARIAS.search(nome or ""))


def chave_doc(bruto: str) -> str:
    """TCE-SP manda 'CNPJ - PESSOA JURÍDICA - 46362661000168' ou 'PESSOA FÍSICA - 761326'
    (para pessoa física o número é um identificador interno do TCE, não o CPF)."""
    b = str(bruto).upper()
    dig = re.sub(r"\D", "", b)
    if "FÍSICA" in b or "FISICA" in b:
        return "PF" + dig
    return dig


def mascarar(doc: str) -> str:
    if str(doc).startswith("PF"):
        return "Pessoa física"
    d = re.sub(r"\D", "", str(doc))
    if len(d) == 11:  # CPF: pessoa física, LGPD -> mascara
        return f"***.{d[3:6]}.{d[6:9]}-**"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return str(doc)


def ler_lista(arquivo: Path):
    if arquivo.suffix == ".gz":
        with gzip.open(arquivo, "rt", encoding="utf-8") as f:
            dados = json.load(f)
    else:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if isinstance(dados, dict):  # algumas respostas vêm embrulhadas
        for v in dados.values():
            if isinstance(v, list):
                return v
        return []
    return dados


def arquivos(pasta: Path, tipo: str):
    """Um arquivo por mês; prefere o .json.gz quando existem os dois formatos."""
    por_mes = {}
    for arq in sorted(pasta.glob(f"*/{tipo}-*.json*")):
        chave = (arq.parent.name, arq.name.split(".")[0])
        if chave not in por_mes or arq.suffix == ".gz":
            por_mes[chave] = arq
    return [por_mes[k] for k in sorted(por_mes)]


DESATIVADOS: set = set()


def processar_cidade(slug: str, nome: str, limites: dict):
    pasta = RAIZ / "dados" / slug
    desp, rec = [], []
    for arq in arquivos(pasta, "despesas"):
        ano = int(arq.parent.name)
        for r in ler_lista(arq):
            desp.append({
                "ano": ano,
                "mes": mes_num(campo(r, "mes")) or int(arq.name.split("-")[1][:2]),
                "orgao": str(campo(r, "orgao", "Não informado")).strip(),
                "tipo": tipo_evento(campo(r, "evento")),
                "empenho": str(campo(r, "empenho")).strip(),
                "doc": chave_doc(campo(r, "doc")),
                "fornecedor": html.unescape(str(campo(r, "fornecedor", "Não informado"))).strip().upper(),
                "data": str(campo(r, "data")),
                "valor": num(campo(r, "valor", 0)),
            })
    for arq in arquivos(pasta, "receitas"):
        ano = int(arq.parent.name)
        for r in ler_lista(arq):
            rec.append({
                "ano": ano,
                "mes": mes_num(campo(r, "mes")) or int(arq.name.split("-")[1][:2]),
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
        por_ano[str(ano)]["oficial"] = conferir_tesouro(pasta / f"siconfi-{ano}.json", por_ano[str(ano)]["por_mes"])

    return {
        "slug": slug,
        "nome": nome,
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "fonte": "Tribunal de Contas do Estado de São Paulo — Portal da Transparência Municipal (Audesp)",
        "fonte_url": "https://transparencia.tce.sp.gov.br/",
        "anos": por_ano,
    }


def conferir_tesouro(arq: Path, por_mes):
    """Compara os totais calculados a partir do TCE com os totais oficiais do Tesouro (RREO),
    no mesmo período (até o último bimestre publicado)."""
    if not arq.exists():
        return None
    of = json.loads(arq.read_text(encoding="utf-8"))
    ate = of["mes_final"]
    nosso = {k: round(sum(m[k] for m in por_mes[:ate]), 2) for k in ("receita", "empenhado", "pago")}
    itens = {}
    for k in ("receita", "empenhado", "pago"):
        o = of.get(k)
        if o is None:
            continue
        dif = round(100 * (nosso[k] - o) / o, 3) if o else None
        itens[k] = {"tesouro": o, "calculado": nosso[k], "diferenca_pct": dif}
    ok = bool(itens) and all(v["diferenca_pct"] is not None and abs(v["diferenca_pct"]) < 1 for v in itens.values())
    return {"periodo": of["periodo"], "mes_final": ate, "populacao": of.get("populacao"),
            "cod_ibge": of.get("cod_ibge"), "liquidado": of.get("liquidado"), "itens": itens, "conferido": ok}


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
        "doc": mascarar(k), "nome": "PESSOA FÍSICA (nome não exibido)" if (k.startswith("PF") or len(k) == 11) else v["nome"], "pago": round(v["pago"], 2),
        "empenhado": round(v["empenhado"], 2), "empenhos": v["n"],
        "participacao": round(100 * v["pago"] / total_pago, 2),
        "pessoa_fisica": k.startswith("PF") or len(k) == 11,
        "ente_publico": eh_ente_publico(v["nome"]),
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


def privado(chave, nome):
    """Fornecedor privado pessoa jurídica (exclui PF e entes públicos/encargos)."""
    return (not str(chave).startswith("PF") and len(str(chave)) != 11
            and not eh_ente_publico(nome) and not eh_concessionaria(nome))


def gerar_alertas(desp, forn, por_mes, limite, total_pago):
    alertas = []
    emp = [d for d in desp if d["tipo"] == "empenhado"]
    # base para participação: só o que foi pago a fornecedores privados
    pago_privado = sum(f["pago"] for k, f in forn.items() if privado(k, f["nome"])) or 1.0

    # 1) Possível fracionamento, agrupado por fornecedor: meses em que houve 3+ empenhos
    #    abaixo do limite de dispensa que, somados, passam o limite.
    grupos = defaultdict(list)
    for d in emp:
        k = d["doc"] or d["fornecedor"]
        if 0 < d["valor"] < limite and privado(k, d["fornecedor"]):
            grupos[(k, d["mes"])].append(d)
    por_forn = defaultdict(list)
    for (k, mes), itens in grupos.items():
        if len(itens) >= 3 and soma(itens) > limite:
            por_forn[k].append((mes, itens))
    for k, meses in por_forn.items():
        meses.sort()
        total = sum(soma(it) for _, it in meses)
        n_emp = sum(len(it) for _, it in meses)
        nome = meses[0][1][0]["fornecedor"]
        if len(meses) >= 3 and total >= 5 * limite:
            grav = "alta"
        elif len(meses) >= 2 or total >= 3 * limite:
            grav = "media"
        else:
            grav = "baixa"
        lista_meses = ", ".join(MESES[m - 1] for m, _ in meses)
        alertas.append({
            "tipo": "fracionamento", "gravidade": grav,
            "titulo": f"{n_emp} empenhos abaixo do limite de dispensa somam {brl(total)} em {len(meses)} {'mês' if len(meses) == 1 else 'meses'}",
            "fornecedor": nome, "doc": mascarar(k), "mes": lista_meses if len(meses) <= 3 else f"{len(meses)} meses",
            "explicacao": (f"Dado estatístico: em {lista_meses}, houve vários empenhos para este fornecedor no mesmo mês, "
                           f"cada um abaixo de {brl(limite)}, que somados passam desse valor. Isso é comum em entregas "
                           "parceladas de contratos e atas de registro de preços. A modalidade de cada compra pode ser "
                           "consultada no PNCP ou solicitada à prefeitura."),
            "empenhos": sorted({i["empenho"] for _, it in meses for i in it})[:25],
            "valor": round(total, 2),
        })

    # 2) Concentração entre fornecedores privados.
    for k, f in forn.items():
        if not privado(k, f["nome"]):
            continue
        part = 100 * f["pago"] / pago_privado
        if part >= 3:
            alertas.append({
                "tipo": "concentracao", "gravidade": "alta" if part >= 10 else "media",
                "titulo": f"{f['nome']} recebeu {str(round(part, 1)).replace('.', ',')}% de todo o dinheiro que a prefeitura pagou a empresas",
                "fornecedor": f["nome"], "doc": mascarar(k), "valor": round(f["pago"], 2),
                "explicacao": ("É uma das empresas que mais receberam no ano. Isso é comum em serviços que funcionam "
                               "o ano inteiro, como hospital, merenda, ônibus e limpeza. Se quiser saber o que foi contratado, "
                               "você pode pedir o contrato à prefeitura."),
            })

    # 3) Anulações altas.
    for k, f in forn.items():
        if privado(k, f["nome"]) and f["empenhado"] > 2 * limite and f["anulado"] / f["empenhado"] > 0.3:
            alertas.append({
                "tipo": "anulacoes", "gravidade": "baixa",
                "titulo": f"A prefeitura cancelou {round(100 * f['anulado'] / f['empenhado'])}% do valor que tinha prometido a {f['nome']}",
                "fornecedor": f["nome"], "doc": mascarar(k), "valor": round(f["anulado"], 2),
                "explicacao": ("A prefeitura separou um dinheiro para pagar esta empresa e depois cancelou parte dele. "
                               "Isso é normal: acontece, por exemplo, quando se compra menos do que o previsto."),
            })

    # 4) Pico de fim de ano.
    meses_com_dado = [m["empenhado"] for m in por_mes[:11] if m["empenhado"] > 0]
    if meses_com_dado and por_mes[11]["empenhado"] > 0:
        media = sum(meses_com_dado) / len(meses_com_dado)
        if por_mes[11]["empenhado"] > 2 * media:
            alertas.append({
                "tipo": "pico_dezembro", "gravidade": "media",
                "titulo": f"Em dezembro a prefeitura prometeu {str(round(por_mes[11]['empenhado'] / media, 1)).replace('.', ',')} vezes mais dinheiro que nos outros meses",
                "valor": por_mes[11]["empenhado"],
                "explicacao": ("É comum as prefeituras fecharem muitas compras no fim do ano, antes de o ano do orçamento acabar."),
            })

    # 5) Fornecedor privado que só aparece em um mês, com valor alto.
    meses_forn = defaultdict(set)
    valor_forn = defaultdict(float)
    for d in emp:
        k = d["doc"] or d["fornecedor"]
        meses_forn[k].add(d["mes"])
        valor_forn[k] += d["valor"]
    for k, ms in meses_forn.items():
        if len(ms) == 1 and valor_forn[k] > 5 * limite and privado(k, forn[k]["nome"]):
            alertas.append({
                "tipo": "fornecedor_pontual", "gravidade": "baixa",
                "titulo": f"{forn[k]['nome']} recebeu {brl(valor_forn[k])}, tudo em um único mês",
                "fornecedor": forn[k]["nome"], "doc": mascarar(k), "valor": round(valor_forn[k], 2),
                "mes": MESES[next(iter(ms)) - 1],
                "explicacao": ("Todas as compras desta empresa no ano aconteceram no mesmo mês. Isso é comum em compras "
                               "feitas de uma vez só, como equipamentos, obras ou eventos."),
            })

    alertas = [a for a in alertas if a["tipo"] not in DESATIVADOS]
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    alertas.sort(key=lambda a: (ordem[a["gravidade"]], -a.get("valor", 0)))
    return alertas[:150]


def main():
    cfg = yaml.safe_load((RAIZ / "cidades.yaml").read_text(encoding="utf-8"))
    limites = {int(k): float(v) for k, v in cfg.get("limite_dispensa", {}).items()}
    DESATIVADOS.update(cfg.get("alertas_desativados") or [])
    resolvidas = RAIZ / "dados" / "cidades.json"
    cidades = (json.loads(resolvidas.read_text(encoding="utf-8")) if resolvidas.exists()
               else [{"slug": c["slug"], "nome": c["nome"]} for c in cfg["cidades"] if c.get("slug")])
    SAIDA.mkdir(parents=True, exist_ok=True)
    indice = []
    for c in cidades:
        if not any((RAIZ / "dados" / c["slug"]).glob("*/despesas-*")):
            print(f"(sem dados para {c['nome']} — confira o identificador '{c['slug']}')")
            continue
        try:
            res = processar_cidade(c["slug"], c["nome"], limites)
        except Exception as e:  # uma cidade com problema não derruba as outras
            print(f"! erro ao processar {c['nome']}: {e}")
            continue
        (SAIDA / f"{c['slug']}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        indice.append({"slug": c["slug"], "nome": c["nome"]})
        print(f"✓ {c['nome']}: {sum(len(a['alertas']) for a in res['anos'].values())} alertas", flush=True)
    indice.sort(key=lambda c: c["nome"])
    (SAIDA / "cidades.json").write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
