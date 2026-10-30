"""Benchmark exhibits. Every figure returns a plotly Figure styled by utils.theme.style()."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from utils import theme
from utils.benchmark import PRODUCT_UNITS

SOURCE = "SODIR (NCS); NSTA public offshore data (UKCS where included). See coverage and reporting-basis notes."


def category_colors(values, key):
    """Stable colour per category: house map for known keys, palette cycle otherwise."""
    preset = theme.color_map(key)
    colors = {}
    cycle = iter(theme.SEQUENCE * 10)
    for value in sorted({str(v) for v in values if pd.notna(v)}):
        colors[value] = preset.get(value) or next(cycle)
    return colors


def investment_ranking(data, metric, label, unit, color_key, color_column, highlight=None, dark=False):
    ranked = data.dropna(subset=[metric]).sort_values(metric)
    if ranked.empty:
        return None
    colors = category_colors(ranked[color_column], color_key)
    fig = go.Figure()
    for category, part in ranked.groupby(color_column, dropna=False):
        fig.add_bar(
            x=part[metric], y=[f.title() for f in part.index], name=str(category), orientation="h",
            marker_color=[theme.ACCENT if f == highlight else colors.get(str(category), theme.GREY) for f in part.index],
            hovertemplate="<b>%{y}</b><br>%{x:,.2f} " + unit + "<extra>%{fullData.name}</extra>",
        )
    fig.update_layout(
        xaxis_title=unit, yaxis=dict(categoryorder="array", categoryarray=[f.title() for f in ranked.index]),
        barmode="group",
    )
    return theme.style(fig, label, "Colour: " + color_key.lower() + " · selected field in amber",
                       "SODIR nominal field investment; user adjustments where selected", dark=dark,
                       height=max(440, len(ranked) * 23 + 180))


def investment_history(annual, master, metric, label, unit, color_key, color_column, highlight=None, dark=False):
    if annual.empty or annual[metric].notna().sum() == 0:
        return None
    colors = category_colors(master[color_column], color_key)
    fig = go.Figure()
    shown = set()
    for field, part in annual.groupby("fldName"):
        part = part.set_index("year").reindex(range(int(part["year"].min()), int(part["year"].max()) + 1)).rename_axis("year").reset_index()
        category = str(master.loc[field, color_column])
        selected = field == highlight
        fig.add_scatter(
            x=part["year"], y=part[metric], mode="lines+markers" if selected else "lines",
            name=f"{field.title()} (selected)" if selected else category, legendgroup=category,
            showlegend=selected or category not in shown, connectgaps=False,
            line=dict(color=theme.ACCENT if selected else colors.get(category, theme.GREY), width=3 if selected else 1),
            opacity=1 if selected else 0.5,
            hovertemplate=f"<b>{field.title()}</b><br>%{{x:.0f}}: %{{y:,.2f}} {unit}<extra></extra>",
        )
        if not selected:
            shown.add(category)
    fig.update_layout(xaxis=dict(title="Calendar year", tickformat="d"), yaxis_title=unit)
    return theme.style(fig, label, "Missing years are gaps, not zero investment",
                       "SODIR nominal field investment; user adjustments where selected", dark=dark, height=520)


def _label(master, field):
    if isinstance(field, str) and field.startswith(("NCS::", "UKCS::")):
        country, name = field.split("::", 1)
        return f"{name.title()} · {country}"
    return field.title() if isinstance(field, str) else str(field)


def _annual_gaps(part, x_column):
    return part.set_index(x_column).reindex(range(int(part[x_column].min()), int(part[x_column].max()) + 1)).rename_axis(x_column).reset_index()


def _hover_fields(master, field):
    if field not in master.index:
        return ""
    row = master.loc[field]
    parts = []
    for label, column, fmt in (
        ("Country", "country", "{}"), ("HC", "hc_type", "{}"), ("Drive", "drainage_strategy", "{}"), ("Formation", "main_formation", "{}"),
        ("Recoverable", "recoverable_oe", "{:,.0f} MSm³ o.e."), ("Start", "start_year", "{:.0f}"),
    ):
        value = row.get(column)
        if pd.notna(value) and value not in (None, ""):
            parts.append(f"{label}: {fmt.format(value)}")
    return "<br>".join(parts)


def profile_figure(profiles, env, master, color_key="HC type", color_column="hc_type", highlight=None,
                   upload=None, x_mode="years_on", y_label="", title="", subtitle="", dark=False, show_lines=True,
                   log_y=False):
    fig = go.Figure()
    x_col = "years_on" if x_mode == "years_on" else "year"
    colors = category_colors(master[color_column], color_key) if color_column in master else {}
    shown = set()
    if show_lines:
        for field, part in profiles.groupby("fldName"):
            part = _annual_gaps(part, x_col)
            category = str(master.loc[field, color_column]) if field in master.index and color_column in master else "n/a"
            color = colors.get(category, theme.GREY)
            is_focus = field == highlight
            fig.add_scatter(
                x=part[x_col], y=part["value"], mode="lines", name=category, legendgroup=category,
                showlegend=category not in shown and not is_focus,
                line=dict(color=theme.ACCENT if is_focus else color, width=3.2 if is_focus else 1.1),
                opacity=1.0 if is_focus else 0.55,
                hovertemplate=f"<b>{_label(master, field)}</b><br>{_hover_fields(master, field)}<br>%{{x}}: %{{y:,.2f}}<extra></extra>",
            )
            if not is_focus:
                shown.add(category)
    if env is not None and not env.empty and x_mode == "years_on":
        fig.add_scatter(x=env["years_on"], y=env["p90"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(
            x=env["years_on"], y=env["p10"], mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor="rgba(5,28,44,0.10)" if not dark else "rgba(170,230,240,0.15)", name="P10–P90 band",
            hoverinfo="skip",
        )
        fig.add_scatter(
            x=env["years_on"], y=env["p50"], mode="lines", name="P50 (median)",
            line=dict(color=theme.NAVY if not dark else theme.ICE, width=2.6, dash="dash"),
            hovertemplate="Year %{x}: P50 %{y:,.2f}<extra></extra>",
        )
        fig.add_scatter(
            x=env["years_on"], y=env["mean"], mode="lines", name="Mean",
            line=dict(color=theme.SKY, width=1.8, dash="dot"),
            hovertemplate="Year %{x}: mean %{y:,.2f}<extra></extra>",
        )
    if highlight and highlight in set(profiles["fldName"]):
        part = _annual_gaps(profiles.loc[profiles["fldName"] == highlight], x_col)
        fig.add_scatter(
            x=part[x_col], y=part["value"], mode="lines+markers", name=f"{_label(master, highlight)} (selected)",
            line=dict(color=theme.ACCENT, width=3.2), marker=dict(size=5, color=theme.ACCENT),
            hovertemplate=f"<b>{_label(master, highlight)}</b><br>%{{x}}: %{{y:,.2f}}<extra></extra>",
        )
    if upload is not None and not upload.empty:
        fig.add_scatter(
            x=upload["years_on"] if x_mode == "years_on" else upload["year"], y=upload["value"], mode="lines+markers",
            name="Imported profile", line=dict(color=theme.ACCENT, width=3.2, dash="dashdot"),
            marker=dict(size=6, symbol="diamond", color=theme.ACCENT),
        )
    fig.update_layout(xaxis_title="Years since production start" if x_mode == "years_on" else "Calendar year",
                      yaxis=dict(title=y_label, type="log" if log_y else "linear"), hovermode="closest")
    return theme.style(fig, title, subtitle, SOURCE, dark=dark, height=560)


def rf_scatter(master, product="oil", color_key="Drainage strategy", color_column="drainage_strategy",
               highlight=None, dark=False):
    rf_col, inplace_col = f"rf_{product}", f"inplace_{product}"
    data = master.dropna(subset=[rf_col, inplace_col])
    data = data.loc[(data[inplace_col] > 0) & (data[rf_col] > 0)]
    colors = category_colors(data[color_column], color_key)
    fig = go.Figure()
    for category, part in data.groupby(color_column):
        size = part["recoverable_oe"].fillna(1).clip(lower=1)
        fig.add_scatter(
            x=part[inplace_col], y=part[rf_col], mode="markers+text", name=str(category),
            text=[f.title() for f in part.index], textposition="top center", textfont=dict(size=9, color=theme.GREY),
            marker=dict(size=np.sqrt(size) * 2.2 + 6, color=colors.get(str(category), theme.GREY), opacity=0.8,
                        line=dict(width=1, color="white")),
            customdata=np.stack([part["recoverable_oe"].fillna(0), part["drainage_strategy"], part["main_formation"].fillna("n/a")], axis=-1),
            hovertemplate="<b>%{text}</b><br>In place: %{x:,.0f}<br>RF: %{y:.0%}<br>Recoverable: %{customdata[0]:,.0f} MSm³ o.e."
                          "<br>Drive: %{customdata[1]}<br>Formation: %{customdata[2]}<extra></extra>",
        )
    if highlight in data.index:
        row = data.loc[highlight]
        fig.add_scatter(x=[row[inplace_col]], y=[row[rf_col]], mode="markers", name=f"{highlight.title()} (selected)",
                        marker=dict(size=18, symbol="circle-open", color=theme.ACCENT, line=dict(width=3)))
    unit = {"oil": "million Sm³", "gas": "billion Sm³", "oe": "million Sm³ o.e."}[product]
    fig.update_layout(xaxis=dict(type="log", title=f"In-place {product.replace('oe', 'o.e.')} · {unit} (log)"),
                      yaxis=dict(tickformat=".0%", title="Recovery factor (recoverable ÷ in place)"))
    return theme.style(fig, f"Recovery factor versus in-place {product.replace('oe', 'o.e.')} volume",
                       "Bubble size: recoverable o.e. · colour: " + color_key.lower(), SOURCE, dark=dark, height=560)


def rf_bars(master, product="oil", color_key="Drainage strategy", color_column="drainage_strategy", highlight=None, dark=False):
    rf_col = f"rf_{product}"
    data = master.dropna(subset=[rf_col]).sort_values(rf_col)
    data = data.loc[data[rf_col] > 0]
    colors = category_colors(data[color_column], color_key)
    bar_colors = [theme.ACCENT if f == highlight else colors.get(str(c), theme.GREY) for f, c in zip(data.index, data[color_column])]
    fig = go.Figure(go.Bar(
        x=data[rf_col], y=[f.title() for f in data.index], orientation="h", marker_color=bar_colors,
        text=[f"{v:.0%}" for v in data[rf_col]], textposition="outside", textfont=dict(size=10),
        hovertemplate="<b>%{y}</b><br>RF: %{x:.0%}<extra></extra>",
    ))
    median = data[rf_col].median()
    fig.add_vline(x=median, line=dict(color=theme.GREY, width=1, dash="dash"),
                  annotation_text=f"median {median:.0%}", annotation_position="top", annotation_font_color=theme.GREY)
    fig.update_layout(xaxis=dict(tickformat=".0%", title="Recovery factor"), yaxis_title="",
                      showlegend=False, height=max(420, 18 * len(data) + 120))
    for category, color in colors.items():
        fig.add_scatter(x=[None], y=[None], mode="markers", marker=dict(color=color, size=10), name=category, showlegend=True)
    fig.update_layout(showlegend=True)
    return theme.style(fig, f"Recovery factor ranking · {product.replace('oe', 'o.e.')}", f"{len(data)} fields with both reserves and in-place volumes", SOURCE, dark=dark)


def wells_scatter(master, color_key="Drainage strategy", color_column="drainage_strategy", highlight=None, dark=False,
                  active=False):
    p_col, i_col = ("producers_active", "injectors_active") if active else ("producers_drilled", "injectors_drilled")
    data = master.dropna(subset=[p_col]).copy()
    data = data.loc[data[p_col] > 0]
    colors = category_colors(data[color_column], color_key)
    fig = go.Figure()
    for category, part in data.groupby(color_column):
        size = part["recoverable_oe"].fillna(1).clip(lower=1)
        fig.add_scatter(
            x=part[p_col], y=part[i_col].fillna(0), mode="markers", name=str(category),
            text=[f.title() for f in part.index],
            marker=dict(size=np.sqrt(size) * 2.0 + 6, color=colors.get(str(category), theme.GREY), opacity=0.8,
                        line=dict(width=1, color="white")),
            customdata=np.stack([part["recoverable_oe"].fillna(0), part["reserves_per_producer"].fillna(0)], axis=-1),
            hovertemplate="<b>%{text}</b><br>Producers: %{x}<br>Injectors: %{y}<br>Recoverable: %{customdata[0]:,.0f} MSm³ o.e."
                          "<br>Reserves per producer: %{customdata[1]:,.2f} MSm³ o.e.<extra></extra>",
        )
    if highlight in data.index:
        row = data.loc[highlight]
        fig.add_scatter(x=[row[p_col]], y=[row[i_col] if pd.notna(row[i_col]) else 0], mode="markers",
                        name=f"{highlight.title()} (selected)",
                        marker=dict(size=18, symbol="circle-open", color=theme.ACCENT, line=dict(width=3)))
    upper = max(data[p_col].max(), data[i_col].max()) if not data.empty else 10
    for ratio, label in ((0.5, "1 injector per 2 producers"), (1.0, "1 : 1")):
        fig.add_scatter(x=[1, upper], y=[ratio, ratio * upper], mode="lines", line=dict(color=theme.LIGHT_GREY, width=1, dash="dot"),
                        name=label, hoverinfo="skip")
    fig.update_layout(xaxis=dict(type="log", title=f"{'Active' if active else 'Drilled'} production wells (log)"),
                      yaxis=dict(type="log", title=f"{'Active' if active else 'Drilled'} injection wells (log)"))
    return theme.style(fig, "Producers versus injectors", "Bubble size: recoverable o.e. · dotted: reference ratios", SOURCE, dark=dark, height=560)


def box_by_category(master, value_column, category_column, title, y_label, highlight=None, dark=False, log=False,
                    fmt=":.2f", color_key=None):
    data = master.dropna(subset=[value_column, category_column])
    data = data.loc[data[value_column] > 0] if log else data
    order = data.groupby(category_column)[value_column].median().sort_values(ascending=False).index
    colors = category_colors(data[category_column], color_key or category_column)
    fig = go.Figure()
    for category in order:
        part = data.loc[data[category_column] == category]
        fig.add_box(
            y=part[value_column], name=f"{category} (n={len(part)})", boxpoints="all", jitter=0.4, pointpos=0,
            marker=dict(color=colors.get(str(category), theme.GREY), size=6, opacity=0.7), line=dict(width=1.2),
            text=[f.title() for f in part.index], hovertemplate="<b>%{text}</b><br>%{y" + fmt + "}<extra></extra>",
        )
    if highlight in data.index:
        row = data.loc[highlight]
        fig.add_scatter(x=[f"{row[category_column]} (n={int((data[category_column] == row[category_column]).sum())})"],
                        y=[row[value_column]], mode="markers", name=f"{highlight.title()} (selected)",
                        marker=dict(size=16, symbol="diamond", color=theme.ACCENT))
    fig.update_layout(yaxis=dict(title=y_label, type="log" if log else "linear"), showlegend=False, xaxis_title="")
    return theme.style(fig, title, None, SOURCE, dark=dark, height=520)


def ratio_figure(table, metric, master, color_key="HC type", color_column="hc_type", highlight=None, dark=False, x_mode="years_on"):
    labels = {"gor": "GOR · Sm³ gas per Sm³ oil", "water_cut": "Water cut", "gas_share": "Gas share of o.e.", "cgr": "CGR · million Sm³ condensate per billion Sm³ gas"}
    fig = go.Figure()
    colors = category_colors(master[color_column], color_key) if color_column in master else {}
    x_col = "years_on" if x_mode == "years_on" else "year"
    shown = set()
    data = table.dropna(subset=[metric])
    for field, part in data.groupby("fldName"):
        part = _annual_gaps(part, x_col)
        category = str(master.loc[field, color_column]) if field in master.index else "n/a"
        focus = field == highlight
        fig.add_scatter(
            x=part[x_col], y=part[metric], mode="lines", name=category, legendgroup=category,
            showlegend=category not in shown and not focus,
            line=dict(color=theme.ACCENT if focus else colors.get(category, theme.GREY), width=3.2 if focus else 1.1),
            opacity=1 if focus else 0.55,
            hovertemplate=f"<b>{_label(master, field)}</b><br>%{{x}}: %{{y:,.2f}}<extra></extra>",
        )
        if not focus:
            shown.add(category)
    if highlight in set(data["fldName"]):
        part = _annual_gaps(data.loc[data["fldName"] == highlight], x_col)
        fig.add_scatter(x=part[x_col], y=part[metric], mode="lines+markers", name=f"{_label(master, highlight)} (selected)",
                        line=dict(color=theme.ACCENT, width=3.2), marker=dict(size=5, color=theme.ACCENT))
    median = data.groupby("years_on")[metric].median() if x_mode == "years_on" else None
    if median is not None and len(median) > 2:
        fig.add_scatter(x=median.index, y=median.values, mode="lines", name="Median",
                        line=dict(color=theme.NAVY if not dark else theme.ICE, width=2.6, dash="dash"))
    yaxis = dict(title=labels.get(metric, metric))
    if metric == "water_cut":
        yaxis.update(tickformat=".0%", range=[0, 1])
    if metric == "gor":
        yaxis.update(type="log")
    fig.update_layout(yaxis=yaxis, xaxis_title="Years since production start" if x_mode == "years_on" else "Calendar year")
    return theme.style(fig, f"{labels.get(metric, metric).split(' ·')[0]} development", None, SOURCE, dark=dark, height=520)


def pt_figure(master, highlight=None, dark=False):
    data = master.dropna(subset=["depth_mid_m"]).copy()
    fig = go.Figure()
    conf_colors = {"high": theme.NAVY, "medium": theme.ELECTRIC, "low": theme.SKY, "stated": theme.STEEL, "estimate": theme.LIGHT_GREY}
    for confidence, part in data.groupby(data["pt_confidence"].fillna("n/a")):
        part = part.dropna(subset=["pressure_bar"])
        if part.empty:
            continue
        fig.add_scatter(
            x=part["pressure_bar"], y=part["depth_mid_m"], mode="markers", name=f"{confidence} confidence",
            text=[f.title() for f in part.index],
            customdata=np.stack([part["temperature_c"].fillna(np.nan), part["pt_source"].fillna("")], axis=-1),
            marker=dict(size=9, color=conf_colors.get(confidence, theme.GREY), line=dict(width=1, color="white")),
            hovertemplate="<b>%{text}</b><br>Pressure: %{x:,.0f} bar<br>Depth: %{y:,.0f} m<br>Temperature: %{customdata[0]:,.0f} °C<br>%{customdata[1]}<extra></extra>",
        )
    depth = np.linspace(500, 5500, 20)
    fig.add_scatter(x=0.101 * depth, y=depth, mode="lines", name="Hydrostatic (0.101 bar/m)", line=dict(color=theme.GREY, width=1, dash="dash"))
    if highlight in data.index and pd.notna(data.loc[highlight, "pressure_bar"]):
        fig.add_scatter(x=[data.loc[highlight, "pressure_bar"]], y=[data.loc[highlight, "depth_mid_m"]], mode="markers",
                        name=f"{highlight.title()} (selected)", marker=dict(size=18, symbol="circle-open", color=theme.ACCENT, line=dict(width=3)))
    fig.update_layout(xaxis_title="Initial reservoir pressure · bar", yaxis=dict(title="Reservoir depth · m", autorange="reversed"))
    return theme.style(fig, "Pressure versus depth", "Grey points are hydrostatic estimates, not measurements", "Curated public literature (indicative), SODIR text depth", dark=dark, height=520)


def wells_timeline(wells_field, title="Development wells drilled per year", dark=False):
    data = wells_field.dropna(subset=["wlbCompletionYear"])
    if data.empty:
        return None
    fig = go.Figure()
    colors = {"PRODUCTION": theme.NAVY, "INJECTION": theme.SKY, "OBSERVATION": theme.LIGHT_GREY}
    for purpose, part in data.groupby("wlbPurpose"):
        counts = part.groupby("wlbCompletionYear").size()
        fig.add_bar(x=counts.index, y=counts.values, name=str(purpose).title(), marker_color=colors.get(purpose, theme.GREY))
    year_span = data["wlbCompletionYear"].max() - data["wlbCompletionYear"].min()
    fig.update_layout(
        barmode="stack",
        xaxis=dict(title="Completion year", type="linear", tickformat="d",
                   dtick=max(1, int(np.ceil(year_span / 10)))),
        yaxis_title="Wells",
    )
    return theme.style(fig, title, None, "SODIR wellbore_development_all", dark=dark, height=380)


def yearly_field_figure(yearly_field, dark=False):
    """Annual production split by product for one field, with producing-well count overlay."""
    if yearly_field.empty:
        return None
    fig = go.Figure()
    for column, label, color in (("oil", "Oil", theme.NAVY), ("condensate", "Condensate", theme.STEEL),
                                 ("ngl", "NGL", theme.SKY), ("gas", "Gas (billion Sm³ = MSm³ o.e.)", theme.ICE)):
        if column in yearly_field:
            fig.add_bar(x=yearly_field["year"], y=yearly_field[column], name=label, marker_color=color)
    if "producers" in yearly_field and yearly_field["producers"].notna().any():
        fig.add_scatter(x=yearly_field["year"], y=yearly_field["producers"], name="Producing wells (est.)", yaxis="y2",
                        mode="lines+markers", line=dict(color=theme.ACCENT, width=2), marker=dict(size=5),
                        hovertemplate="%{x:.0f}<br>Producing wells: %{y:.0f}<extra></extra>")
        fig.update_layout(yaxis2=dict(
            title="Wells", overlaying="y", side="right", showgrid=False,
            tickmode="linear", tick0=0, tickformat="d",
            dtick=max(1, int(np.ceil(yearly_field["producers"].max() / 8))),
            rangemode="tozero",
        ))
    fig.update_layout(barmode="stack", xaxis_title="", yaxis_title="million Sm³ o.e. per year", legend=dict(y=1.02))
    well_note = ("Wells: production wells completed and not yet plugged (SODIR wellbore table)"
                 if "producers" in yearly_field and yearly_field["producers"].notna().any()
                 else "Reported annual product volumes; historical producing-well overlay unavailable")
    return theme.style(fig, "Annual production by product", well_note, SOURCE, dark=dark, height=440)
