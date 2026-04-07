"""Generate branded PDF production reports for Sa Relvas Tapecarias."""

from __future__ import annotations

import base64
import io
import re
import tempfile
from datetime import datetime
from pathlib import Path

from fpdf import FPDF


# Brand colours
_INK = (24, 24, 27)       # #18181B
_STEEL = (113, 113, 122)  # #71717A
_MUTED = (161, 161, 170)  # #A1A1AA
_BORDER = (228, 228, 231)  # #E4E4E7
_ACCENT = (24, 24, 27)    # #18181B (ink black)
_SURFACE = (255, 255, 255)
_BG = (250, 250, 251)     # #FAFAFA


def _hex_to_rgb(hex_val: str | None) -> tuple[int, int, int]:
    if not hex_val or not re.match(r"^#[0-9a-fA-F]{6}$", hex_val):
        return (204, 204, 204)
    return (int(hex_val[1:3], 16), int(hex_val[3:5], 16), int(hex_val[5:7], 16))


class _Report(FPDF):
    def header(self):
        # Red accent bar at top
        self.set_fill_color(*_ACCENT)
        self.rect(0, 0, 210, 3, "F")

        # Brand name
        self.set_y(10)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, "SA RELVAS TAPECARIAS", align="L")

        # Date right-aligned
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_STEEL)
        self.cell(0, 6, datetime.now().strftime("%d/%m/%Y"), align="R", new_x="LMARGIN", new_y="NEXT")

        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 8, f"Sa Relvas Tapecarias  |  Analise de Vetorizacao  |  Pagina {self.page_no()}", align="C")

        # Bottom accent bar
        self.set_fill_color(*_ACCENT)
        self.rect(0, 294, 210, 3, "F")


def generate_pdf(pd: dict) -> bytes:
    """Generate a branded PDF report from production data.

    Args:
        pd: Production data dict (same structure as the email/download export).

    Returns:
        PDF file bytes.
    """
    pdf = _Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=15, top=15, right=15)
    pdf.add_page()

    dims = pd.get("dimensions", {})
    totals = pd.get("totals", {})
    colours = pd.get("colours", [])
    yarn_params = pd.get("yarn_params", {})
    consumo_g_m2 = yarn_params.get("consumo_g_m2", 0)
    desperdicio = yarn_params.get("desperdicio_pct", 0)
    has_yarn = consumo_g_m2 > 0 and any(c.get("yarn_kg", 0) > 0 for c in colours)
    has_modo = any(c.get("loop_cut_mode") for c in colours)

    # --- Title ---
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 10, "Dados de Producao", new_x="LMARGIN", new_y="NEXT")

    # Source file + type
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_STEEL)
    source = pd.get("source_file", "")
    stype = pd.get("source_type", "").upper()
    pdf.cell(0, 6, f"{source}  |  {stype}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)

    # --- Design preview image ---
    preview_b64 = pd.get("preview")
    if preview_b64 and preview_b64.startswith("data:image/png;base64,"):
        raw_b64 = preview_b64.split(",", 1)[1]
        png_bytes = base64.b64decode(raw_b64)

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(png_bytes)
        tmp.close()
        try:
            from PIL import Image as PILImage
            with PILImage.open(tmp.name) as pimg:
                img_w, img_h = pimg.size

            # Fit within 80mm max height, centred, max 180mm wide
            max_h = 80
            max_w = 180
            aspect = img_w / img_h
            if aspect >= max_w / max_h:
                draw_w = max_w
                draw_h = max_w / aspect
            else:
                draw_h = max_h
                draw_w = max_h * aspect

            x_img = 15 + (180 - draw_w) / 2
            pdf.set_fill_color(*_BG)
            pdf.rect(15, pdf.get_y(), 180, draw_h + 12, "F")
            pdf.image(tmp.name, x=x_img, y=pdf.get_y() + 6, w=draw_w, h=draw_h)
            pdf.set_y(pdf.get_y() + draw_h + 16)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    # --- Separator ---
    pdf.set_draw_color(*_BORDER)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    # --- Metrics row ---
    metrics = [
        ("Dimensoes", f"{dims.get('width_m', 0):.2f} x {dims.get('height_m', 0):.2f} m"),
        ("Area Total", f"{totals.get('design_area_m2', 0):.4f} m2"),
        ("Cores", str(totals.get("colour_count", 0))),
    ]
    if has_yarn:
        metrics.append(("Consumo fio", f"{float(consumo_g_m2):.0f} g/m2 (+{float(desperdicio):.0f}%)"))
        metrics.append(("Peso Total", f"{totals.get('total_yarn_kg', 0):.3f} kg"))

    col_w = 180 / len(metrics)
    y_start = pdf.get_y()
    x = 15

    for label, value in metrics:
        pdf.set_xy(x, y_start)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w, 4, label.upper())
        pdf.set_xy(x, y_start + 5)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*_INK)
        pdf.cell(col_w, 7, value)
        x += col_w

    pdf.set_y(y_start + 18)

    # --- Separator ---
    pdf.set_draw_color(*_BORDER)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    # --- Colour distribution bar ---
    bar_y = pdf.get_y()
    bar_x = 15
    bar_w = 180
    bar_h = 4
    for c in colours:
        seg_w = bar_w * (c.get("percentage", 0) / 100)
        if seg_w < 0.5:
            continue
        rgb = _hex_to_rgb(c.get("colour_hex"))
        pdf.set_fill_color(*rgb)
        pdf.rect(bar_x, bar_y, seg_w, bar_h, "F")
        bar_x += seg_w

    pdf.set_y(bar_y + bar_h + 6)

    # --- Table ---
    # Build columns
    cols = [("Cor", 40, "L")]
    if has_yarn:
        cols.append(("Codigo Fio", 28, "L"))
    cols.append(("Area (m2)", 24, "R"))
    cols.append(("%", 14, "R"))
    if has_yarn:
        cols.append(("Peso (kg)", 22, "R"))
    if has_modo:
        cols.append(("Comprimento", 26, "R"))
        cols.append(("Pontos", 22, "R"))
        cols.append(("Modo", 18, "L"))

    # Adjust widths to fill 180mm
    total_w = sum(w for _, w, _ in cols)
    scale = 180 / total_w
    cols = [(name, w * scale, align) for name, w, align in cols]

    # Table header
    pdf.set_fill_color(*_BG)
    pdf.set_draw_color(*_BORDER)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*_MUTED)

    for name, w, align in cols:
        pdf.cell(w, 7, name.upper(), border="B", align=align, fill=True)
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_INK)

    for i, c in enumerate(colours):
        y_row = pdf.get_y()

        # Zebra striping
        if i % 2 == 1:
            pdf.set_fill_color(*_BG)
            pdf.rect(15, y_row, 180, 8, "F")

        x = 15
        row_data = []

        # Colour swatch + name
        rgb = _hex_to_rgb(c.get("colour_hex"))
        pdf.set_fill_color(*rgb)
        pdf.rect(x + 1, y_row + 2, 3.5, 3.5, "F")
        # Border around swatch
        pdf.set_draw_color(*_BORDER)
        pdf.rect(x + 1, y_row + 2, 3.5, 3.5, "D")

        name_text = c.get("name", "")
        col_w_name = cols[0][2]
        pdf.set_xy(x + 6, y_row)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(cols[0][1] - 6, 8, name_text[:25])
        x += cols[0][1]

        col_idx = 1

        if has_yarn:
            pdf.set_xy(x, y_row)
            pdf.set_font("Courier", "", 8)
            pdf.set_text_color(*_STEEL)
            pdf.cell(cols[col_idx][1], 8, c.get("yarn_code", ""), align="L")
            x += cols[col_idx][1]
            col_idx += 1

        # Area
        pdf.set_xy(x, y_row)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(cols[col_idx][1], 8, f"{c.get('area_m2', 0):.4f}", align="R")
        x += cols[col_idx][1]
        col_idx += 1

        # Percentage
        pdf.set_xy(x, y_row)
        pdf.cell(cols[col_idx][1], 8, f"{c.get('percentage', 0):.1f}%", align="R")
        x += cols[col_idx][1]
        col_idx += 1

        # Peso (kg)
        if has_yarn:
            pdf.set_xy(x, y_row)
            pdf.set_font("Helvetica", "B", 9)
            kg = c.get("yarn_kg", 0)
            pdf.cell(cols[col_idx][1], 8, f"{kg:.3f}" if kg > 0 else "\u2014", align="R")
            x += cols[col_idx][1]
            col_idx += 1

        if has_modo:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_INK)
            # Comprimento
            pdf.set_xy(x, y_row)
            pdf.cell(cols[col_idx][1], 8, f"{c.get('tuft_length_m', 0):.1f} m", align="R")
            x += cols[col_idx][1]
            col_idx += 1
            # Pontos
            pdf.set_xy(x, y_row)
            pdf.cell(cols[col_idx][1], 8, f"{c.get('stitch_count', 0):,}".replace(",", "."), align="R")
            x += cols[col_idx][1]
            col_idx += 1
            # Modo
            pdf.set_xy(x, y_row)
            pdf.set_text_color(*_STEEL)
            pdf.cell(cols[col_idx][1], 8, c.get("loop_cut_mode", "") or "\u2014", align="L")
            x += cols[col_idx][1]
            col_idx += 1

        pdf.set_y(y_row + 8)

        # Row border
        pdf.set_draw_color(*_BORDER)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())

    # --- Totals row ---
    if has_yarn:
        y_row = pdf.get_y()
        pdf.set_fill_color(*_BG)
        pdf.rect(15, y_row, 180, 8, "F")

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_INK)
        pdf.set_xy(15, y_row)
        span_w = cols[0][1] + (cols[1][1] if has_yarn else 0)
        pdf.cell(span_w, 8, "Total")

        # Area total
        x = 15 + span_w
        col_idx = 2 if has_yarn else 1
        pdf.set_xy(x, y_row)
        pdf.cell(cols[col_idx][1], 8, f"{totals.get('design_area_m2', 0):.4f}", align="R")
        x += cols[col_idx][1]
        col_idx += 1

        # 100%
        pdf.set_xy(x, y_row)
        pdf.cell(cols[col_idx][1], 8, "100%", align="R")
        x += cols[col_idx][1]
        col_idx += 1

        # Total kg
        pdf.set_xy(x, y_row)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(cols[col_idx][1], 8, f"{totals.get('total_yarn_kg', 0):.3f}", align="R")

        pdf.set_y(y_row + 8)
        pdf.set_draw_color(*_ACCENT)
        pdf.set_line_width(0.5)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.set_line_width(0.2)

    # --- Output ---
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
