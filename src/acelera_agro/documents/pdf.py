"""ReportLab PDF generation for BB proposal — layout inspired by BB simplified proposal.

Formal bank document: bordered sections, cover with office banner, blank signature lines.
Optional ``banner_bytes`` is used only for the current generation (never persisted here).
"""

from __future__ import annotations

from io import BytesIO
from typing import Sequence

from django.utils.translation import gettext as _
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from acelera_agro.proposals.models import Proposal
from acelera_agro.proposals.validation import has_error_issues

# A4 geometry
_PAGE_W, _PAGE_H = A4
_LEFT = 36
_RIGHT = 36
_TOP = 36
_BOTTOM = 40
_CONTENT_W = _PAGE_W - _LEFT - _RIGHT

# Accent from typical AT office banner (forest green) — sparse use only
_GREEN = (0.18, 0.45, 0.22)
_GRAY = (0.35, 0.35, 0.35)
_BLACK = (0.08, 0.08, 0.08)
_LINE = (0.15, 0.15, 0.15)

# Ideal banner: full content width, height capped so cover stays balanced (~Adalto).
# Source asset 440×88 → ratio 5:1; at full width ≈ 100pt tall.
_BANNER_MAX_H = 108.0
_BANNER_TARGET_RATIO = 5.0  # width / height


class PdfGenerationError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _set_fill(c: canvas.Canvas, rgb: tuple[float, float, float]) -> None:
    c.setFillColorRGB(*rgb)


def _set_stroke(c: canvas.Canvas, rgb: tuple[float, float, float], width: float = 0.8) -> None:
    c.setStrokeColorRGB(*rgb)
    c.setLineWidth(width)


def _box(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    _set_stroke(c, _LINE, 0.9)
    c.rect(x, y, w, h, stroke=1, fill=0)


def _hline(c: canvas.Canvas, y: float, x0: float | None = None, x1: float | None = None) -> None:
    _set_stroke(c, _LINE, 0.7)
    c.line(x0 if x0 is not None else _LEFT, y, x1 if x1 is not None else _LEFT + _CONTENT_W, y)


def _new_page(c: canvas.Canvas) -> float:
    c.showPage()
    return _PAGE_H - _TOP


def _ensure(c: canvas.Canvas, y: float, need: float) -> float:
    if y < _BOTTOM + need:
        return _new_page(c)
    return y


def _text(c: canvas.Canvas, x: float, y: float, text: str, *, size: int = 9, bold: bool = False) -> None:
    _set_fill(c, _BLACK)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, text[:120])


def _muted(c: canvas.Canvas, x: float, y: float, text: str, *, size: int = 8) -> None:
    _set_fill(c, _GRAY)
    c.setFont("Helvetica", size)
    c.drawString(x, y, text[:120])


def _center(c: canvas.Canvas, y: float, text: str, *, size: int = 11, bold: bool = True) -> None:
    _set_fill(c, _BLACK)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawCentredString(_PAGE_W / 2, y, text[:90])


def _kv_row(
    c: canvas.Canvas,
    y: float,
    pairs: Sequence[tuple[str, str]],
    *,
    col_w: float | None = None,
) -> float:
    """Draw label/value pairs in one row inside the content width."""
    n = max(len(pairs), 1)
    width = col_w or (_CONTENT_W / n)
    for i, (label, value) in enumerate(pairs):
        x = _LEFT + i * width
        _muted(c, x + 4, y, f"{label}:", size=7)
        _text(c, x + 4, y - 11, value or "—", size=9)
    return y - 26


def ideal_banner_size(image_w: float, image_h: float) -> tuple[float, float]:
    """Return (draw_w, draw_h) for A4 content width with balanced cover height."""
    if image_w <= 0 or image_h <= 0:
        return _CONTENT_W, min(_BANNER_MAX_H, _CONTENT_W / _BANNER_TARGET_RATIO)
    ratio = image_w / image_h
    draw_w = _CONTENT_W
    draw_h = draw_w / ratio
    if draw_h > _BANNER_MAX_H:
        draw_h = _BANNER_MAX_H
        draw_w = min(_CONTENT_W, draw_h * ratio)
    # Prefer full width when close (wide banners like 5:1)
    if ratio >= 3.5:
        draw_w = _CONTENT_W
        draw_h = min(_BANNER_MAX_H, draw_w / ratio)
    return draw_w, draw_h


def _draw_banner(c: canvas.Canvas, banner_bytes: bytes | None, y: float) -> float:
    if not banner_bytes:
        return y
    try:
        img = ImageReader(BytesIO(banner_bytes))
        iw, ih = img.getSize()
        draw_w, draw_h = ideal_banner_size(float(iw), float(ih))
        x = _LEFT + (_CONTENT_W - draw_w) / 2
        c.drawImage(
            img,
            x,
            y - draw_h,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
        return y - draw_h - 10
    except Exception:
        return y


def _section_bar(c: canvas.Canvas, title: str, y: float) -> float:
    """Green-tinted section header bar (Adalto-like hierarchy, not scrapbook)."""
    h = 16
    y = _ensure(c, y, h + 8)
    _set_fill(c, _GREEN)
    c.rect(_LEFT, y - h + 4, _CONTENT_W, h, stroke=0, fill=1)
    _set_fill(c, (1, 1, 1))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(_LEFT + 6, y - 7, title[:95])
    return y - h - 6


def _footer(c: canvas.Canvas, page: int, total: int) -> None:
    _muted(c, _LEFT, 22, _("Acelera Agro · pacote técnico"), size=7)
    _muted(c, _PAGE_W - _RIGHT - 50, 22, f"{page} de {total}", size=7)


def _signature_grid(c: canvas.Canvas, y: float, slots: list[tuple[str, str]]) -> float:
    """2-column signature slots without label overlap."""
    gap = 16
    col_w = (_CONTENT_W - gap) / 2
    row_h = 62
    rows = (len(slots) + 1) // 2
    y = _ensure(c, y, row_h * rows + 8)
    for row in range(rows):
        base = y
        for col in range(2):
            idx = row * 2 + col
            if idx >= len(slots):
                break
            title, subtitle = slots[idx]
            x = _LEFT + col * (col_w + gap)
            _set_stroke(c, _LINE, 0.8)
            c.line(x + 6, base - 26, x + col_w - 6, base - 26)
            _text(c, x + 6, base - 38, title, size=8, bold=True)
            if subtitle:
                _muted(c, x + 6, base - 50, subtitle[:42], size=7)
        y -= row_h
        y = _ensure(c, y, row_h if row < rows - 1 else 8)
    return y


def _office_block(proposal: Proposal) -> list[tuple[str, str]]:
    office = getattr(proposal, "office", None)
    org = getattr(proposal, "organization", None)
    mun = getattr(office, "municipality", None) if office else None
    return [
        (_("Empresa"), getattr(org, "name", "") or str(proposal.organization_id)),
        (_("Escritório"), getattr(office, "name", "") or str(proposal.office_id)),
        (_("Município"), f"{mun.name}/{mun.state_uf}" if mun else "—"),
        (_("Telefone"), getattr(office, "phone", "") or "—"),
    ]


def generate_bb_proposal_pdf(
    proposal: Proposal,
    *,
    banner_bytes: bytes | None = None,
) -> bytes:
    if proposal.technician_reviewed_at is None:
        raise PdfGenerationError(
            "not_reviewed",
            "technician_reviewed_at is required before PDF generation.",
        )
    if has_error_issues(proposal):
        raise PdfGenerationError(
            "has_errors",
            "Cannot generate PDF while error Issues remain.",
        )

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    pages: list[int] = []  # filled at end via multi-pass? we number as we go with estimate
    # Simpler: write page numbers in a second concept — use running counter
    page_no = 1
    total_guess = 4

    proponent = proposal.proponent
    prop = proposal.property
    classification = proposal.classification_json or {}
    items = list(proposal.budget_items.all())
    line = proposal.credit_line

    # ---------- Cover (Adalto-like page 1) ----------
    y = _PAGE_H - _TOP
    _center(c, y, "BANCO DO BRASIL", size=12, bold=True)
    y -= 14
    _set_fill(c, (0.75, 0.12, 0.12))
    c.setFont("Helvetica", 7)
    c.drawCentredString(
        _PAGE_W / 2,
        y,
        _("Capa-resumo da proposta. Impressão da capa é opcional. Pode incluir o carimbo da empresa."),
    )
    y -= 12

    y = _draw_banner(c, banner_bytes, y)

    # Company / agent header box
    box_h = 54
    _box(c, _LEFT, y - box_h, _CONTENT_W * 0.48, box_h)
    _box(c, _LEFT + _CONTENT_W * 0.48, y - box_h, _CONTENT_W * 0.52, box_h)
    _text(c, _LEFT + 6, y - 12, _("Agente financeiro"), size=7, bold=True)
    _text(c, _LEFT + 6, y - 26, "Banco do Brasil S.A.", size=9)
    _text(c, _LEFT + _CONTENT_W * 0.48 + 6, y - 12, _("Assistência técnica"), size=7, bold=True)
    office_pairs = _office_block(proposal)
    oy = y - 24
    for label, value in office_pairs[:3]:
        _muted(c, _LEFT + _CONTENT_W * 0.48 + 6, oy, f"{label}: {value}", size=7)
        oy -= 10
    y -= box_h + 14

    _center(c, y, _("PROPOSTA SIMPLIFICADA DE CRÉDITO — INVESTIMENTO"), size=11)
    y -= 10

    # Program / safra box
    prog_h = 36
    _box(c, _LEFT, y - prog_h, _CONTENT_W, prog_h)
    _hline(c, y - 18)
    c.line(_LEFT + _CONTENT_W * 0.62, y, _LEFT + _CONTENT_W * 0.62, y - prog_h)
    _text(c, _LEFT + 6, y - 12, _("PROG. NAC. DE FORT. DA AGRICULTURA FAMILIAR"), size=8, bold=True)
    _text(
        c,
        _LEFT + _CONTENT_W * 0.62 + 6,
        y - 12,
        getattr(proposal.crop_year, "label", None) or _("Safra vigente"),
        size=8,
        bold=True,
    )
    line_name = line.name if line else "Pronaf Investimento"
    _text(c, _LEFT + 6, y - 28, line_name, size=9, bold=True)
    y -= prog_h + 16

    y = _section_bar(c, _("Resumo da proposta"), y)
    prop_name = prop.name if prop else "—"
    prop_mun = ""
    if prop and prop.municipality_id:
        prop_mun = f"{prop.municipality.name}/{prop.municipality.state_uf}"
    y = _kv_row(
        c,
        y,
        [
            (_("Proponente"), proponent.full_name if proponent else "—"),
            (_("CPF/CNPJ"), proponent.document_number if proponent else "—"),
        ],
    )
    y = _kv_row(
        c,
        y,
        [
            (_("Imóvel"), prop_name),
            (_("Município do imóvel"), prop_mun or "—"),
        ],
    )
    y = _kv_row(
        c,
        y,
        [
            (_("Atividade"), proposal.activity_kind or "—"),
            (_("Finalidade"), proposal.credit_purpose or "—"),
        ],
    )
    y = _kv_row(
        c,
        y,
        [
            (_("Valor proposto"), f"R$ {proposal.financed_amount}"),
            (_("Prazo / carência"), f"{proposal.term_years} a / {proposal.grace_years} a"),
        ],
    )
    if proposal.annual_rate is not None:
        y = _kv_row(c, y, [(_("Taxa a.a."), str(proposal.annual_rate)), (_("Grupo"), str(classification.get("group_code", "")))])

    y -= 8
    y = _section_bar(c, _("08 — Local, data e assinaturas (capa)"), y)
    _muted(
        c,
        _LEFT,
        y,
        _("Assinar após imprimir (manuscrito), salvo se a agência aceitar outro meio."),
        size=7,
    )
    y -= 14
    y = _signature_grid(
        c,
        y,
        [
            (_("Proponente"), proponent.full_name if proponent else ""),
            (_("Cônjuge / companheiro(a)"), getattr(proponent, "spouse_name", "") if proponent else ""),
            (_("Técnico responsável (ATER)"), ""),
            (_("Empresa de assistência técnica"), office_pairs[0][1] if office_pairs else ""),
        ],
    )
    _footer(c, page_no, total_guess)

    # ---------- Page 2: identification + property + activity ----------
    y = _new_page(c)
    page_no += 1
    y = _section_bar(c, _("01 — Identificação do proponente"), y)
    if proponent:
        y = _kv_row(c, y, [(_("Nome"), proponent.full_name), (_("Documento"), proponent.document_number)])
        y = _kv_row(
            c,
            y,
            [
                (_("Estado civil"), proponent.marital_status),
                (_("Cônjuge"), proponent.spouse_name or "—"),
            ],
        )
        y = _kv_row(c, y, [(_("Endereço"), proponent.address or "—")])
    else:
        _text(c, _LEFT, y, "—")
        y -= 14

    y = _section_bar(c, _("02 — Imóvel explorado"), y)
    if prop:
        y = _kv_row(c, y, [(_("Nome"), prop.name), (_("Vínculo"), prop.ownership_type)])
        y = _kv_row(
            c,
            y,
            [
                (_("Município"), prop_mun or "—"),
                (_("Matrícula"), prop.matricula or "—"),
            ],
        )
        y = _kv_row(
            c,
            y,
            [
                (_("Área (ha)"), str(prop.area_ha)),
                ("CAR", prop.car_code or "—"),
            ],
        )
    else:
        _text(c, _LEFT, y, "—")
        y -= 14

    y = _section_bar(c, _("03 — Atividade e objetivo"), y)
    y = _kv_row(
        c,
        y,
        [
            (_("Atividade"), proposal.activity_kind or "—"),
            (_("Finalidade"), proposal.credit_purpose or "—"),
        ],
    )
    y = _kv_row(
        c,
        y,
        [
            ("RBA", str(proposal.total_rba)),
            (_("% agropecuária"), str(proposal.agro_revenue_share)),
        ],
    )

    y = _section_bar(c, _("04 — Proposta / orçamento"), y)
    # simple table header
    _box(c, _LEFT, y - 16, _CONTENT_W, 16)
    _text(c, _LEFT + 6, y - 11, _("Descrição"), size=8, bold=True)
    _text(c, _LEFT + _CONTENT_W * 0.62, y - 11, _("Qtd"), size=8, bold=True)
    _text(c, _LEFT + _CONTENT_W * 0.75, y - 11, _("Valor (R$)"), size=8, bold=True)
    y -= 18
    rows = items or []
    if not rows:
        _text(c, _LEFT + 6, y, f"{_('Valor financiado')}: {proposal.financed_amount}", size=9)
        y -= 14
    for item in rows:
        y = _ensure(c, y, 18)
        _hline(c, y + 4)
        _text(c, _LEFT + 6, y - 8, str(item.description)[:55], size=8)
        _text(c, _LEFT + _CONTENT_W * 0.62, y - 8, str(item.quantity), size=8)
        _text(c, _LEFT + _CONTENT_W * 0.75, y - 8, str(item.amount), size=8)
        y -= 16
    y -= 6
    y = _kv_row(
        c,
        y,
        [
            (_("Valor do investimento"), f"R$ {proposal.financed_amount}"),
            (_("Linha"), line.name if line else "—"),
        ],
    )
    y = _kv_row(
        c,
        y,
        [
            (_("Prazo"), f"{proposal.term_years} anos"),
            (_("Carência"), f"{proposal.grace_years} anos"),
        ],
    )
    _footer(c, page_no, total_guess)

    # ---------- Page 3: schedule + capacity ----------
    y = _new_page(c)
    page_no += 1
    y = _section_bar(c, _("05 — Cronograma de pagamento"), y)
    _box(c, _LEFT, y - 16, _CONTENT_W, 16)
    _text(c, _LEFT + 6, y - 11, _("Ano"), size=8, bold=True)
    _text(c, _LEFT + 60, y - 11, _("Juros"), size=8, bold=True)
    _text(c, _LEFT + 150, y - 11, _("Principal"), size=8, bold=True)
    _text(c, _LEFT + 260, y - 11, _("Parcela"), size=8, bold=True)
    _text(c, _LEFT + 370, y - 11, _("Saldo"), size=8, bold=True)
    y -= 18
    for row in proposal.schedule_json or []:
        y = _ensure(c, y, 16)
        _text(c, _LEFT + 6, y - 8, str(row.get("year", "")), size=8)
        _text(c, _LEFT + 60, y - 8, str(row.get("interest", "")), size=8)
        _text(c, _LEFT + 150, y - 8, str(row.get("principal", "")), size=8)
        _text(c, _LEFT + 260, y - 8, str(row.get("payment", "")), size=8)
        _text(c, _LEFT + 370, y - 8, str(row.get("balance", "")), size=8)
        y -= 14

    y -= 8
    y = _section_bar(c, _("06 — Capacidade de pagamento (superávit)"), y)
    for row in proposal.capacity_json or []:
        y = _ensure(c, y, 14)
        _text(
            c,
            _LEFT + 6,
            y - 8,
            f"Ano {row.get('year')}: superávit = {row.get('surplus')}",
            size=8,
        )
        y -= 13

    y -= 6
    y = _section_bar(c, _("07 — Enquadramento"), y)
    y = _kv_row(
        c,
        y,
        [
            (_("Grupo"), str(classification.get("group_code", ""))),
            (_("Regra"), str(classification.get("rule_source", ""))),
        ],
    )
    _footer(c, page_no, total_guess)

    # ---------- Page 4: opinion + signatures ----------
    y = _new_page(c)
    page_no += 1
    y = _section_bar(c, _("09 — Parecer da assistência técnica"), y)
    opinion = getattr(proposal, "technical_opinion", None)
    summary = getattr(opinion, "summary", "") if opinion else ""
    # wrap-ish single block
    text = summary or "—"
    c.setFont("Helvetica", 9)
    _set_fill(c, _BLACK)
    # simple wrap
    words = text.split()
    line_buf: list[str] = []
    for word in words:
        trial = (" ".join(line_buf + [word])).strip()
        if c.stringWidth(trial, "Helvetica", 9) > _CONTENT_W - 12:
            _text(c, _LEFT + 4, y, " ".join(line_buf), size=9)
            y -= 12
            y = _ensure(c, y, 20)
            line_buf = [word]
        else:
            line_buf.append(word)
    if line_buf:
        _text(c, _LEFT + 4, y, " ".join(line_buf), size=9)
        y -= 16
    y = _kv_row(
        c,
        y,
        [
            (
                _("Revisado em"),
                proposal.technician_reviewed_at.isoformat()
                if proposal.technician_reviewed_at
                else "",
            )
        ],
    )

    y -= 10
    y = _section_bar(c, _("Assinaturas finais"), y)
    _muted(
        c,
        _LEFT,
        y,
        _("Espaços em branco para assinatura manuscrita após impressão."),
        size=7,
    )
    y -= 14
    y = _signature_grid(
        c,
        y,
        [
            (_("Proponente"), proponent.full_name if proponent else ""),
            (
                _("Cônjuge / companheiro(a)"),
                getattr(proponent, "spouse_name", "") if proponent else "",
            ),
            (_("Técnico responsável (ATER)"), ""),
            (_("Empresa de assistência técnica"), office_pairs[0][1] if office_pairs else ""),
        ],
    )
    _footer(c, page_no, page_no)

    c.save()
    return buffer.getvalue()


def generate_stub_pdf(title: str, lines: list[str] | None = None) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    y = _PAGE_H - _TOP
    _center(c, y, title, size=12)
    y -= 24
    for line in lines or []:
        _text(c, _LEFT, y, line, size=9)
        y -= 14
    c.save()
    return buffer.getvalue()


def generate_laudo_pdf(proposal: Proposal) -> bytes:
    return generate_stub_pdf(
        _("Technical appraisal (laudo)"),
        [
            f"{_('Proposal ID')}: {proposal.id}",
            proposal.proponent.full_name if proposal.proponent else "",
        ],
    )


def generate_declaracao_atni_pdf(proposal: Proposal) -> bytes:
    return generate_stub_pdf(
        _("ATNI declaration"),
        [f"{_('Proposal ID')}: {proposal.id}"],
    )


def generate_croqui_pdf(proposal: Proposal) -> bytes:
    return generate_stub_pdf(
        _("Property sketch (croqui)"),
        [f"{_('Proposal ID')}: {proposal.id}"],
    )


def generate_anexo2_pdf(proposal: Proposal) -> bytes:
    return generate_stub_pdf(
        _("Annex 2"),
        [f"{_('Proposal ID')}: {proposal.id}"],
    )
