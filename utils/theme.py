"""Consulting-style (McKinsey-inspired) visual system shared by text and charts.

Deep-navy / electric-blue palette, serif action titles, no chart junk, one warm
accent reserved for the item in focus (selected field or imported profile).
"""
import plotly.graph_objects as go
import plotly.io as pio

NAVY = "#051C2C"
ELECTRIC = "#2251FF"
SKY = "#00A9F4"
ICE = "#AAE6F0"
STEEL = "#3C96B4"
INDIGO = "#1F40E6"
DEEP_TEAL = "#034B6F"
GREY = "#7F7F7F"
LIGHT_GREY = "#B3B3B3"
RULE = "#E1E4E8"
PAPER = "#FFFFFF"
ACCENT = "#E6791F"      # focus item only (selected field / imported profile)
INK_DARK = "#F2F5F8"
PAPER_DARK = "#0B1A27"
RULE_DARK = "#24364A"

SEQUENCE = [NAVY, ELECTRIC, SKY, STEEL, "#8FA8FF", DEEP_TEAL, ICE, GREY, INDIGO, LIGHT_GREY]
HEADING_FONT = "Georgia, 'Times New Roman', 'Bower', serif"
BODY_FONT = "'Helvetica Neue', Helvetica, Arial, 'McKinsey Sans', sans-serif"

HC_TYPE_COLORS = {
    "OIL": NAVY, "OIL/GAS": ELECTRIC, "GAS": SKY, "GAS/CONDENSATE": STEEL,
    "OIL/CONDENSATE": INDIGO, "Unknown": LIGHT_GREY,
}
DRIVE_COLORS = {
    "Pressure depletion": GREY, "Water injection": ELECTRIC, "Gas injection": SKY,
    "Water & gas injection": DEEP_TEAL, "WAG": INDIGO, "Natural water drive": STEEL,
    "Not stated": LIGHT_GREY,
}
AREA_COLORS = {"NORTH SEA": NAVY, "NORWEGIAN SEA": ELECTRIC, "BARENTS SEA": SKY}


def _template(dark=False):
    ink = INK_DARK if dark else NAVY
    paper = PAPER_DARK if dark else PAPER
    rule = RULE_DARK if dark else RULE
    layout = go.Layout(
        font=dict(family=BODY_FONT, size=13, color=ink),
        title=dict(font=dict(family=HEADING_FONT, size=20, color=ink), x=0, xanchor="left", y=0.98, yanchor="top", pad=dict(l=0)),
        paper_bgcolor=paper, plot_bgcolor=paper, colorway=SEQUENCE,
        margin=dict(l=48, r=24, t=118, b=64),
        hovermode="closest", hoverlabel=dict(font=dict(family=BODY_FONT, size=12), bordercolor=rule),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)", title=dict(text=""), tracegroupgap=0,
                    itemsizing="constant"),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=rule, linewidth=1, ticks="outside",
                   tickcolor=rule, ticklen=4, title=dict(font=dict(size=12, color=GREY), standoff=8),
                   showline=True, automargin=True),
        yaxis=dict(showgrid=True, gridcolor=rule, gridwidth=1, zeroline=False, showline=False,
                   ticks="", title=dict(font=dict(size=12, color=GREY), standoff=8), automargin=True),
        colorscale=dict(sequential=[[0, ICE], [0.5, SKY], [1, NAVY]]),
    )
    data = dict(
        scatter=[go.Scatter(line=dict(width=2), marker=dict(size=8, line=dict(width=0)))],
        bar=[go.Bar(marker=dict(line=dict(width=0)))],
        box=[go.Box(marker=dict(size=4))],
    )
    return go.layout.Template(layout=layout, data=data)


pio.templates["consulting"] = _template(False)
pio.templates["consulting_dark"] = _template(True)


def template_name(dark=False):
    return "consulting_dark" if dark else "consulting"


DEFAULT_SOURCE = "Norwegian Offshore Directorate (SODIR)"


def style(fig, title=None, subtitle=None, source=DEFAULT_SOURCE, dark=False, height=None):
    """Apply the house style: action title, grey subtitle, source line, template.

    Re-styling an already styled figure keeps its specific source line unless a new one is given.
    """
    fig.update_layout(template=template_name(dark), paper_bgcolor=PAPER_DARK if dark else PAPER,
                      plot_bgcolor=PAPER_DARK if dark else PAPER)
    if title is not None:
        text = f"<b>{title}</b>"
        if subtitle:
            text += f"<br><span style='font-size:12px;color:{GREY};font-family:{BODY_FONT}'>{subtitle}</span>"
        fig.update_layout(title=dict(text=text))
    existing = [a for a in (fig.layout.annotations or []) if getattr(a, "name", None) == "source"]
    others = [a for a in (fig.layout.annotations or []) if getattr(a, "name", None) != "source"]
    if source == DEFAULT_SOURCE and existing:
        annotations = others + existing
    else:
        annotations = others
        if source:
            annotations.append(dict(
                name="source", text=f"Source: {source}", xref="paper", yref="paper", x=0, y=-0.18,
                xanchor="left", yanchor="top", showarrow=False, font=dict(size=11, color=GREY),
            ))
    fig.update_layout(annotations=annotations)
    if height:
        fig.update_layout(height=height)
    return fig


def color_map(key):
    return {"HC type": HC_TYPE_COLORS, "Drainage strategy": DRIVE_COLORS, "Area": AREA_COLORS}.get(key, {})


def css_variables(dark=False):
    if dark:
        return dict(bg=PAPER_DARK, surface="#122537", text=INK_DARK, rule=RULE_DARK, muted="#9FB0C0")
    return dict(bg="#F7F8FA", surface=PAPER, text=NAVY, rule=RULE, muted=GREY)
