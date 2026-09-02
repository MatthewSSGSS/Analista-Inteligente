"""Encabezados de sección y piezas pequeñas de texto (`.section-intro`,
`.data-badge`, `.decision-strip`) repetidas al inicio de casi cada bloque
de cada vista.
"""
from __future__ import annotations

from ui.assets import image_data_uri


def section_header(title, eyebrow=None, subtitle=None, badge=None, compact: bool = False) -> str:
    """Encabezado `.section-intro` (título + subtítulo opcional a la
    izquierda, badge opcional a la derecha). El `eyebrow` se conserva por
    compatibilidad con las vistas existentes aunque el CSS actual lo
    oculta (`.eyebrow{display:none}`, ver ui/styles/theme.py)."""
    classes = "section-intro" + (" compact" if compact else "")
    eyebrow_html = f'<span class="eyebrow">{eyebrow}</span>' if eyebrow else ""
    subtitle_html = f'<div class="chart-subtitle">{subtitle}</div>' if subtitle else ""
    badge_html = f'<span class="data-badge">{badge}</span>' if badge else ""
    return f'<div class="{classes}"><div>{eyebrow_html}<h2>{title}</h2>{subtitle_html}</div>{badge_html}</div>'


def banner_header(title, subtitle=None, image: str | None = None) -> str:
    """Encabezado de vista con foto de fondo (`.view-banner`) — variante de
    `section_header` para un puñado de vistas donde una de las 4 fotos de
    `assets/images/` tiene sentido temático (Georreferenciación, Asistente
    IA...), no un reemplazo general: `section_header` se sigue usando en
    el resto de la app, sin tocar.

    El texto va siempre en blanco fijo, no en `var(--text)`: se apoya en
    un velo oscuro (`rgba(9,12,18,...)`) sobre la foto, no en el panel del
    tema — por eso funciona igual en Claro y en Oscuro sin necesitar dos
    versiones."""
    cover = image_data_uri(image) if image else None
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    style = f' style="background-image:url({cover})"' if cover else ""
    return (
        f'<div class="view-banner"{style}>'
        f'<div class="view-banner-content"><h2>{title}</h2>{subtitle_html}</div>'
        f'</div>'
    )


def data_badge(text) -> str:
    return f'<span class="data-badge">{text}</span>'


def decision_strip(text, tone: str = "neutral", dot: bool = False) -> str:
    """Línea `.decision-strip`. `dot` reproduce el punto de color que
    algunas vistas anteponen al texto (p. ej. la lectura rápida de
    crecimiento en app.py/dashboard.py); la mayoría de los usos existentes
    no lo llevan."""
    dot_html = '<span class="decision-dot"></span>' if dot else ""
    return f'<div class="decision-strip {tone}">{dot_html}{text}</div>'
