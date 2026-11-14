# Olho Público

Painel aberto das contas de prefeituras paulistas: de onde vem o dinheiro, quem gasta, quem recebe, e alertas automáticos de possíveis irregularidades. Cobre o eixo da Anhanguera, de Campinas a Ribeirão Preto (24 cidades), e funciona para qualquer um dos 644 municípios fiscalizados pelo TCE-SP: é só acrescentar o nome da cidade no `cidades.yaml`.

## Como funciona

1. **`coletor/coletar.py`** baixa despesas (empenhos, liquidações, pagamentos) e receitas mês a mês da API aberta do TCE-SP (`transparencia.tce.sp.gov.br/api`). Os dados brutos ficam compactados em `dados/` (no cache do GitHub Actions, fora do git, porque cidades grandes como Campinas passam de 1 GB); o resumo publicado em `site/dados/` fica versionado no git, com histórico auditável.
2. **`coletor/siconfi.py`** baixa do Tesouro Nacional (Siconfi, RREO Anexo 1) os totais oficiais de receita, empenho e pagamento, para conferir os nossos cálculos. Em Leme 2025 os três totais batem centavo por centavo.
3. **`coletor/processar.py`** gera os resumos e os **alertas** em `site/dados/`.
4. **`site/index.html`** é o painel: um arquivo estático, sem servidor.
5. **GitHub Actions** roda tudo todo dia e publica no GitHub Pages. Custo: zero.

## Colocar no ar (cerca de 10 minutos)

1. Envie esta pasta para um repositório no GitHub.
2. No Cloudflare: **Workers & Pages → Create → Pages → Connect to Git**, escolha o repositório. Deixe *Build command* vazio e use `site` como *Build output directory*.
3. No GitHub: **Actions → Atualizar dados → Run workflow** para a primeira coleta.
4. A cada atualização diária o Cloudflare republica o site sozinho em `https://NOME.pages.dev/?cidade=leme`.

Para rodar no seu computador:

```bash
pip install -r requirements.txt
python coletor/coletar.py leme 2026
python coletor/processar.py
cd site && python -m http.server 8000   # abra http://localhost:8000
```

## Alertas (versão 1)

| Alerta | Regra |
|---|---|
| Possível fracionamento | 3 ou mais empenhos abaixo do limite de dispensa, mesmo fornecedor e mesmo mês, que somados passam o limite |
| Concentração | Fornecedor (PJ) com 5% ou mais de tudo que foi pago |
| Anulações | Mais de 30% do valor empenhado para o fornecedor foi anulado |
| Pico de fim de ano | Empenhos de dezembro acima de 2x a média mensal |
| Fornecedor pontual | Aparece em um único mês com valor acima de 5x o limite de dispensa |

Todo alerta é um **indício** e traz o critério e os números dos empenhos para conferência. Nunca chame um alerta de "fraude" no site ou nas redes.

## Próximas fontes (roadmap)

- **PNCP** (`pncp.gov.br/api/consulta`): contratos, aditivos e modalidade de cada compra, para cruzar com os empenhos.
- **Receita Federal (CNPJ)**: data de abertura e sócios dos fornecedores (alerta "empresa nova").
- **TSE**: doadores de campanha × fornecedores.
- **Câmara Municipal**: votações nominais (extraídas das atas em PDF) e despesas da Câmara.
- **Imprensa Oficial do Município**: nomeações, dispensas e decretos (via raspagem ou Querido Diário).
- **Repasses federais** (Portal da Transparência da CGU): FPM, SUS, FNDE.

## Avisos

- Confira o campo `limite_dispensa` no `cidades.yaml`: ele é atualizado por decreto federal todo ano.
- A API do TCE-SP pode mudar nomes de campos. O `processar.py` aceita variações (dicionário `CAMPOS`), mas confira na primeira coleta.
- CPFs são mascarados (LGPD).
