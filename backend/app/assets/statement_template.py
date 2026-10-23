"""Termo de Responsabilidade: modelo editável em texto simples.

O administrador edita o texto do termo; o sistema só preenche os dados do ativo e do colaborador. O modelo NÃO
é HTML: tudo que o usuário escreve é escapado, e o layout (cores, tabelas, assinaturas) é do sistema. Isso evita
que um modelo malicioso rode script na sessão de quem imprime o termo.

Marcação aceita (uma por linha):
    # Título                  título do documento (centralizado)
    > Subtítulo               linha pequena abaixo do título
    ## Seção                  título de seção
    1. item / - item          lista numerada / lista com marcadores
    **negrito**               negrito dentro de qualquer texto
    qualquer outra linha      parágrafo (linha em branco separa parágrafos)

Campos preenchidos automaticamente (podem aparecer em qualquer lugar do texto):
    {{colaborador}} {{matricula}} {{cargo}} {{setor}} {{unidade}} {{patrimonio}} {{categoria}}
    {{equipamento}} {{empresa}} {{data}}
Blocos prontos (sozinhos na linha):
    {{tabela_colaborador}} {{tabela_equipamento}} {{tabela_especificacoes}} {{assinaturas}}
"""

import re
from dataclasses import dataclass, field
from html import escape

MAX_TEMPLATE_CHARS = 20000

INLINE_FIELDS: dict[str, str] = {
    "colaborador": "Nome do colaborador responsável",
    "matricula": "Matrícula do colaborador",
    "cargo": "Cargo ou função",
    "setor": "Setor do colaborador",
    "unidade": "Unidade onde o ativo está",
    "patrimonio": "Número de patrimônio (etiqueta)",
    "categoria": "Categoria do ativo",
    "equipamento": "Nome/modelo do equipamento",
    "empresa": "Nome da empresa",
    "data": "Data e hora da emissão",
}
BLOCK_FIELDS: dict[str, str] = {
    "tabela_colaborador": "Tabela com os dados do colaborador",
    "tabela_equipamento": "Tabela com a identificação do equipamento",
    "tabela_especificacoes": "Tabela com as especificações técnicas",
    "assinaturas": "Campos de assinatura (colaborador e responsável de TI)",
}

DEFAULT_TEMPLATE = """# Termo de Responsabilidade e Cautela de Equipamento de TI
> Departamento de Tecnologia da Informação — Gestão Patrimonial

## 1. Dados do Colaborador (Responsável)
{{tabela_colaborador}}

## 2. Identificação do Equipamento (Patrimônio)
{{tabela_equipamento}}

## 3. Especificações Técnicas
{{tabela_especificacoes}}

## 4. Declaração e Termos de Uso
1. O colaborador declara haver recebido nesta data o equipamento de TI acima especificado em perfeito estado de conservação, limpeza e pleno funcionamento.
2. O equipamento destina-se **exclusivamente** ao desempenho das atividades profissionais relativas à sua função na empresa.
3. O colaborador compromete-se a guardar e zelar pela conservação do equipamento, responsabilizando-se pelo seu uso adequado e pela observância da Política de Segurança da Informação.
4. É terminantemente vedada a instalação de softwares não autorizados ou licenciados pela equipe de Tecnologia da Informação.
5. Qualquer anomalia, quebra, dano, perda ou furto/roubo deve ser imediatamente comunicado à equipe de TI e às autoridades competentes (com respectivo Boletim de Ocorrência).
6. Em caso de desligamento, transferência de setor ou solicitação da TI, o equipamento deverá ser devolvido imediatamente no mesmo estado em que foi entregue, ressalvado o desgaste natural.

{{assinaturas}}
"""

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.*)$")


@dataclass
class StatementData:
    """Dados já lidos do banco (texto puro; o escape acontece só na renderização)."""

    colaborador: str = "Não atribuído (Em Estoque)"
    matricula: str = "N/A"
    cargo: str = "N/A"
    setor: str = "N/A"
    unidade: str = "N/A"
    patrimonio: str = ""
    categoria: str = "Equipamento de TI"
    equipamento: str = ""
    empresa: str = ""
    data: str = ""
    asset_id: str = ""
    specs: dict = field(default_factory=dict)


def unknown_fields(template: str) -> list[str]:
    """Campos {{...}} que o sistema não conhece (aparecem como estão no documento)."""
    known = set(INLINE_FIELDS) | set(BLOCK_FIELDS)
    return sorted({name for name in _PLACEHOLDER.findall(template) if name not in known})


def validate_template(template: str) -> str:
    text = template.replace("\r\n", "\n").strip("\n")
    if not text.strip():
        raise ValueError("O modelo do termo não pode ficar vazio.")
    if len(text) > MAX_TEMPLATE_CHARS:
        raise ValueError(f"O modelo do termo passou do limite de {MAX_TEMPLATE_CHARS} caracteres.")
    return text


def _inline(text: str, data: StatementData) -> str:
    """Escapa o texto, aplica **negrito** e preenche os campos automáticos (valores também escapados)."""

    def fill(match: re.Match) -> str:
        name = match.group(1)
        if name in INLINE_FIELDS:
            return escape(str(getattr(data, name)))
        return match.group(0)

    escaped = escape(text)
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    return _PLACEHOLDER.sub(fill, escaped)


def _info_table(rows: list[tuple[str, str, str, str]] | list[tuple]) -> str:
    out = ['<table class="info-grid">']
    for row in rows:
        cells = []
        for i in range(0, len(row), 2):
            label, value = row[i], row[i + 1]
            span = ' colspan="3"' if len(row) == 2 else ""
            cells.append(f'<td class="label">{escape(label)}</td><td{span}>{value}</td>')
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _block(name: str, data: StatementData) -> str:
    e = escape
    if name == "tabela_colaborador":
        return _info_table(
            [
                ("Colaborador:", f"<strong>{e(data.colaborador)}</strong>", "Matrícula:", e(data.matricula)),
                ("Cargo / Função:", e(data.cargo), "Setor / Departamento:", e(data.setor)),
                ("Unidade / Localidade:", e(data.unidade)),
            ]
        )
    if name == "tabela_equipamento":
        return _info_table(
            [
                ("Número de Patrimônio:", f'<strong class="tag">{e(data.patrimonio)}</strong>', "Categoria:", e(data.categoria)),
                ("Equipamento / Modelo:", e(data.equipamento)),
            ]
        )
    if name == "tabela_especificacoes":
        rows = "".join(
            f'<tr><td class="spec-key">{e(str(k).upper())}</td><td class="spec-value">{e(str(v))}</td></tr>'
            for k, v in (data.specs or {}).items()
        )
        if not rows:
            rows = '<tr><td colspan="2" class="spec-empty">Sem especificações registradas</td></tr>'
        return f"<table>{rows}</table>"
    if name == "assinaturas":
        return (
            '<div class="signatures">'
            f'<div class="sig-block"><div class="sig-line"></div><strong>{e(data.colaborador)}</strong><br>'
            "Colaborador Responsável<br>Data: ____ / ____ / ________</div>"
            '<div class="sig-block"><div class="sig-line"></div><strong>Responsável de TI</strong><br>'
            "Departamento de Tecnologia<br>Data: ____ / ____ / ________</div>"
            "</div>"
        )
    return ""


def render_body(template: str, data: StatementData) -> str:
    html: list[str] = []
    title_open = False  # abre o bloco .header no "# " e fecha ao encontrar outra coisa
    list_kind: str | None = None
    paragraph: list[str] = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            html.append(f"</{list_kind}></div>")
            list_kind = None

    def close_paragraph() -> None:
        if paragraph:
            html.append('<p class="terms">' + "<br>".join(_inline(line, data) for line in paragraph) + "</p>")
            paragraph.clear()

    def close_header() -> None:
        nonlocal title_open
        if title_open:
            html.append("</div>")
            title_open = False

    def close_all(*, paragraph_too: bool = True, list_too: bool = True, header_too: bool = True) -> None:
        if paragraph_too:
            close_paragraph()
        if list_too:
            close_list()
        if header_too:
            close_header()

    for raw in template.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            close_all(header_too=False)
            continue
        if stripped.startswith("## "):
            close_all()
            html.append(f'<div class="section-title">{_inline(stripped[3:], data)}</div>')
        elif stripped.startswith("# "):
            close_all()
            html.append(f'<div class="header"><h1>{_inline(stripped[2:], data)}</h1>')
            title_open = True
        elif stripped.startswith("> "):
            close_all(header_too=False)
            html.append(f'<p class="subtitle">{_inline(stripped[2:], data)}</p>')
        elif (m := _PLACEHOLDER.fullmatch(stripped)) and m.group(1) in BLOCK_FIELDS:
            close_all()
            html.append(_block(m.group(1), data))
        elif (m := _NUMBERED.match(stripped)) or stripped.startswith("- "):
            close_all(list_too=False)
            kind = "ol" if m else "ul"
            if list_kind != kind:
                close_list()
                html.append(f'<div class="terms"><{kind}>')
                list_kind = kind
            html.append(f"<li>{_inline(m.group(1) if m else stripped[2:], data)}</li>")
        else:
            close_all(paragraph_too=False)
            paragraph.append(stripped)
    close_all()
    return "\n".join(html)


STYLE = """
body { font-family: Arial, Helvetica, sans-serif; color: #1e293b; margin: 40px; font-size: 13px; line-height: 1.5; }
.header { text-align: center; border-bottom: 2px solid #0f172a; padding-bottom: 12px; margin-bottom: 24px; }
.header h1 { font-size: 18px; text-transform: uppercase; margin: 0; letter-spacing: 0.5px; }
.subtitle { margin: 4px 0 0; color: #64748b; font-size: 11px; text-align: center; }
.section-title { font-size: 13px; font-weight: bold; text-transform: uppercase; color: #0f172a; background: #e2e8f0;
  padding: 6px 10px; margin-top: 18px; margin-bottom: 8px; border-left: 4px solid #2563eb; }
table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
.info-grid td { padding: 6px 10px; border: 1px solid #cbd5e1; }
.label { font-weight: bold; background-color: #f8fafc; width: 25%; }
.tag { font-size: 14px; color: #2563eb; }
.spec-key { padding: 6px 12px; font-weight: 600; border: 1px solid #cbd5e1; background: #f8fafc; width: 35%; }
.spec-value { padding: 6px 12px; border: 1px solid #cbd5e1; }
.spec-empty { padding: 8px 12px; border: 1px solid #cbd5e1; color: #64748b; }
.terms { margin-top: 16px; text-align: justify; font-size: 12px; }
.terms ol, .terms ul { padding-left: 20px; margin: 6px 0; }
.terms li { margin-bottom: 6px; }
.signatures { margin-top: 50px; display: flex; justify-content: space-between; }
.sig-block { width: 45%; text-align: center; }
.sig-line { border-top: 1px solid #334155; margin-bottom: 6px; }
.footer { margin-top: 35px; text-align: center; font-size: 10px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 8px; }
.no-print { position: fixed; top: 20px; right: 20px; background: #2563eb; color: white; border: none; padding: 10px 18px;
  font-size: 14px; font-weight: bold; border-radius: 6px; cursor: pointer; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
@media print { .no-print { display: none; } body { margin: 20px; } }
"""


def render_document(template: str, data: StatementData) -> str:
    """Página HTML completa, pronta para imprimir ou salvar em PDF."""
    e = escape
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Termo de Responsabilidade - Patrimônio {e(data.patrimonio)}</title>
    <style>{STYLE}</style>
</head>
<body>
    <button class="no-print" onclick="window.print()">🖨️ Imprimir / Salvar PDF</button>
{render_body(template, data)}
    <div class="footer">
        Documento gerado eletronicamente em {e(data.data)} pela Plataforma de Gestão de TI • ID Ativo: {e(data.asset_id)}
    </div>
</body>
</html>"""
