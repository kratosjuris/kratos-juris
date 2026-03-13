from __future__ import annotations

import os
from io import BytesIO
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _safe_str(v: object, fallback: str = "") -> str:
    s = (str(v) if v is not None else "").strip()
    return s if s else fallback


def build_hearing_orientations_pdf(
    *,
    client_name: str,
    process_number: str,
    promovido: str,
    starts_at: Optional[datetime],
    modalidade: str,
    extension_code: str,
    static_dir: str,
) -> bytes:
    """
    Gera PDF (bytes) com orientações e imagens do Lifesize.

    Espera imagens em:
      {static_dir}/img/audiencias/lifesize_01.jpg
      {static_dir}/img/audiencias/lifesize_02.jpg
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Paths das imagens
    img1_path = os.path.join(static_dir, "img", "audiencias", "lifesize_01.jpg")
    img2_path = os.path.join(static_dir, "img", "audiencias", "lifesize_02.jpg")

    # Dados
    nome = _safe_str(client_name, "Cliente").upper()
    proc = _safe_str(process_number, "Não informado")
    reu = _safe_str(promovido, "Não informado")
    mod = _safe_str(modalidade, "Não informada")
    code = _safe_str(extension_code, "Não informado")

    data = "Não informada"
    hora = "Não informado"
    if starts_at:
        try:
            data = starts_at.strftime("%d/%m/%Y")
            hora = starts_at.strftime("%H:%M")
        except Exception:
            pass

    # Layout helpers
    x = 2.0 * cm
    y = h - 2.0 * cm
    line = 14

    def draw_title(text: str):
        nonlocal y
        c.setFont("Helvetica-Bold", 15)
        c.drawString(x, y, text)
        y -= 22

    def draw_text(text: str, bold: bool = False):
        nonlocal y
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, 11)

        max_width = w - 4 * cm

        for paragraph in text.split("\n"):
            p = paragraph.strip()
            if not p:
                y -= line
                continue

            words = p.split()
            cur = ""
            for word in words:
                test = (cur + " " + word).strip()
                if c.stringWidth(test, font, 11) > max_width:
                    c.drawString(x, y, cur)
                    y -= line
                    cur = word
                else:
                    cur = test
            if cur:
                c.drawString(x, y, cur)
                y -= line

    def draw_image(path: str, caption: str):
        nonlocal y
        if not os.path.exists(path):
            draw_text(f"[Imagem não encontrada] {caption}")
            y -= 6
            return

        max_w = w - 4 * cm
        max_h = 10.5 * cm

        img = ImageReader(path)
        iw, ih = img.getSize()

        scale = min(max_w / iw, max_h / ih)
        dw = iw * scale
        dh = ih * scale

        if y - dh < 2.0 * cm:
            c.showPage()
            y = h - 2.0 * cm

        c.drawImage(img, x, y - dh, width=dw, height=dh, preserveAspectRatio=True, anchor="nw")
        y = y - dh - 10

        c.setFont("Helvetica-Oblique", 10)
        c.drawString(x, y, caption)
        y -= 18

    # PDF
    draw_title("ORIENTAÇÕES PARA AUDIÊNCIA (TELEPRESENCIAL)")
    draw_text(f"Prezado(a) Sr.(a) {nome},")
    draw_text(
        f"O escritório Clementino & Silva Lopes vem, por meio desta, INTIMÁ-LO(A) para comparecimento em audiência "
        f"referente ao processo nº {proc}, movido em face de {reu}."
    )
    y -= 6
    draw_text(f"Data: {data}", bold=True)
    draw_text(f"Horário: {hora}", bold=True)
    draw_text(f"Modalidade: {mod}", bold=True)
    y -= 10

    draw_text("PASSO A PASSO (LIFESIZE)", bold=True)
    draw_text("1) Acesse a Play Store ou Apple Store e baixe o aplicativo 'LIFESIZE'.")
    draw_image(img1_path, "Imagem 1 — Baixar e instalar o aplicativo Lifesize.")

    draw_text("2) Abra o aplicativo e preencha:", bold=True)
    draw_text("   - Insira seu nome e sobrenome.")
    draw_text(f"   - Insira o código de acesso à sala: {code}")
    draw_text("   - Clique em 'ENTRAR NA REUNIÃO' para ser direcionado(a) à sala.")
    draw_image(img2_path, "Imagem 2 — Onde inserir nome e código de acesso.")

    draw_text("ORIENTAÇÕES IMPORTANTES", bold=True)
    draw_text("- Pontualidade obrigatória: não pode atrasar.")
    draw_text("- Conexão antecipada: acesse com 10 minutos de antecedência.")
    draw_text("- Documento com foto: esteja com documento oficial em mãos.")
    draw_text("- Não falte: ausência sem justificativa pode gerar consequências processuais.")
    y -= 8
    draw_text("Em caso de impossibilidade de comparecimento, entre em contato com o escritório com máxima urgência.")
    y -= 10
    draw_text("Atenciosamente,")
    draw_text("Equipe Clementino & Silva Lopes – Advocacia")

    c.showPage()
    c.save()

    return buf.getvalue()