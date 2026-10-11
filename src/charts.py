"""Plotly figure builders. Each function returns a ``go.Figure``; app.py displays it.

Color rules (so charts read as one system and stay colorblind-friendly):
  * Each ETF always has the same color, and each profile always has the same color,
    in every chart (color follows the entity, never its position).
  * Colors come from a validated categorical palette, with separate steps for light
    and dark mode. The ticker-to-color mapping was chosen so neighboring donut
    slices stay distinguishable even when some weights are 0; slices are also
    direct-labeled and separated by a thin gap, so color is never the only cue.
  * ETFs in the risk/return scatter are neutral gray with text labels so the
    three portfolios stand out.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.portfolios import ETF_INFO

# Categorical palette: light / dark steps of the same hues.
PALETTE = {
    "light": {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a",
              "yellow": "#eda100", "magenta": "#e87ba4", "green": "#008300"},
    "dark":  {"blue": "#3987e5", "orange": "#d95926", "aqua": "#199e70",
              "yellow": "#c98500", "magenta": "#d55181", "green": "#008300"},
}
TICKER_HUE = {"VTI": "blue", "VXUS": "magenta", "VNQ": "green",
              "BND": "yellow", "BNDX": "aqua", "SHY": "orange"}
PROFILE_HUE = {"Conservative": "aqua", "Moderate": "orange", "Aggressive": "blue"}

# Chart chrome per mode. Surface matches Streamlit's own background.
CHROME = {
    "light": {"surface": "#ffffff", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "neutral": "#898781"},
    "dark":  {"surface": "#0e1117", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
              "grid": "#2c2c2a", "neutral": "#898781"},
}
FONT = dict(family="Inter, system-ui, sans-serif", size=13)


def ticker_color(ticker: str, mode: str = "light") -> str:
    return PALETTE[mode][TICKER_HUE[ticker]]


def profile_color(profile: str, mode: str = "light") -> str:
    return PALETTE[mode][PROFILE_HUE[profile]]


def _base_layout(fig: go.Figure, mode: str, title: str, height: int = 420) -> go.Figure:
    """Shared, recessive styling: transparent background, hairline grid, legend on top."""
    c = CHROME[mode]
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=c["ink"]), x=0, xanchor="left"),
        height=height,
        margin=dict(l=10, r=10, t=60, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(**FONT, color=c["ink2"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(color=c["ink2"])),
        hoverlabel=dict(font=dict(family=FONT["family"])),
    )
    axis = dict(gridcolor=c["grid"], linecolor=c["grid"], zeroline=False,
                tickfont=dict(color=c["muted"]), title_font=dict(color=c["ink2"]))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


# --------------------------------------------------------------- allocation

def allocation_donut(weights: dict[str, float], mode: str = "light", title: str = "Allocation") -> go.Figure:
    """Donut chart of portfolio weights (zero weights omitted), labeled on each slice."""
    items = [(t, w) for t, w in weights.items() if w > 1e-9]
    tickers = [t for t, _ in items]
    fig = go.Figure(go.Pie(
        labels=tickers,
        values=[w for _, w in items],
        hole=0.55,
        sort=False,  # keep config order so each ticker's position and color are stable
        direction="clockwise",
        marker=dict(colors=[ticker_color(t, mode) for t in tickers],
                    line=dict(color=CHROME[mode]["surface"], width=2)),  # 2px gap between slices
        texttemplate="%{label}<br>%{percent:.0%}",
        textposition="outside",
        textfont=dict(color=CHROME[mode]["ink2"]),
        customdata=[[ETF_INFO[t]["name"], ETF_INFO[t]["asset_class"]] for t in tickers],
        hovertemplate="<b>%{label}</b> — %{customdata[0]}<br>%{customdata[1]}"
                      "<br>Weight: %{percent:.1%}<extra></extra>",
    ))
    fig = _base_layout(fig, mode, title, height=380)
    fig.update_layout(showlegend=False, margin=dict(l=40, r=40, t=60, b=30))
    return fig


# --------------------------------------------------------------- growth

def growth_chart(
    backtests: dict[str, pd.Series],
    highlight: set[str] | None = None,
    mode: str = "light",
    title: str = "Historical growth of $10,000 (monthly rebalancing)",
    extra: dict[str, pd.Series] | None = None,
) -> go.Figure:
    """Line chart of backtested portfolio value for each profile.

    Args:
        backtests: {profile name: value series}.
        highlight: profiles to emphasize; the rest are drawn faded.
        extra: additional series (e.g. the user's tilted portfolio), drawn in primary ink.
    """
    highlight = highlight or set(backtests)
    fig = go.Figure()
    for name, series in backtests.items():
        on = name in highlight
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values, mode="lines", name=name,
            line=dict(color=profile_color(name, mode), width=2.5 if on else 1.5),
            opacity=1.0 if on else 0.5,
            hovertemplate=f"{name}: $%{{y:,.0f}}<extra></extra>",
        ))
        # Direct label at the line's end for highlighted series only.
        if on:
            fig.add_annotation(x=series.index[-1], y=series.values[-1], text=f"${series.values[-1]:,.0f}",
                               showarrow=False, xanchor="left", xshift=6,
                               font=dict(color=CHROME[mode]["ink2"], size=12))
    for name, series in (extra or {}).items():
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values, mode="lines", name=name,
            line=dict(color=CHROME[mode]["ink"], width=2),
            hovertemplate=f"{name}: $%{{y:,.0f}}<extra></extra>",
        ))
    fig = _base_layout(fig, mode, title)
    fig.update_layout(hovermode="x unified", margin=dict(l=10, r=70, t=60, b=10))
    fig.update_yaxes(title="Portfolio value", tickprefix="$", tickformat=",.0f")
    return fig


# --------------------------------------------------------------- risk vs return

def risk_return_scatter(
    asset_stats: pd.DataFrame,
    portfolios: dict[str, tuple[float, float]],
    risk_free: float | None = None,
    highlight: str | None = None,
    mode: str = "light",
    extra: dict[str, tuple[float, float]] | None = None,
) -> go.Figure:
    """Annual volatility (x) vs expected return (y) for each ETF and portfolio.

    Args:
        asset_stats: DataFrame indexed by ticker with "Annual Return" and "Annual Volatility".
        portfolios: {profile: (volatility, expected return)}.
        risk_free: if given, plotted at zero volatility.
        highlight: the user's profile, drawn larger.
        extra: other points (e.g. the user's tilted portfolio), drawn in primary ink.
    """
    c = CHROME[mode]
    # Alternate labels above/below in order of volatility so neighbors (e.g. BND/BNDX) don't collide.
    order = asset_stats["Annual Volatility"].rank(method="first").astype(int)
    positions = ["top center" if r % 2 else "bottom center" for r in order]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=asset_stats["Annual Volatility"], y=asset_stats["Annual Return"],
        mode="markers+text", name="Individual ETFs",
        text=list(asset_stats.index), textposition=positions, textfont=dict(color=c["ink2"], size=11),
        marker=dict(size=10, color=c["neutral"], line=dict(color=c["surface"], width=2)),
        customdata=[ETF_INFO.get(t, {}).get("name", t) for t in asset_stats.index],
        hovertemplate="<b>%{text}</b> — %{customdata}<br>Volatility: %{x:.1%}"
                      "<br>Return: %{y:.1%}<extra></extra>",
    ))
    for name, (vol, ret) in portfolios.items():
        big = name == highlight
        fig.add_trace(go.Scatter(
            x=[vol], y=[ret], mode="markers+text", name=f"{name} portfolio",
            text=[f"{name}{' (you)' if big else ''}"], textposition="middle right",
            textfont=dict(color=c["ink"], size=12),
            marker=dict(size=18 if big else 13, symbol="diamond", color=profile_color(name, mode),
                        line=dict(color=c["surface"], width=2)),
            hovertemplate=f"<b>{name} portfolio</b><br>Volatility: %{{x:.1%}}"
                          f"<br>Expected return: %{{y:.1%}}<extra></extra>",
        ))
    for name, (vol, ret) in (extra or {}).items():
        fig.add_trace(go.Scatter(
            x=[vol], y=[ret], mode="markers+text", name=name, text=[name], textposition="bottom right",
            textfont=dict(color=c["ink"], size=12),
            marker=dict(size=14, symbol="star", color=c["ink"], line=dict(color=c["surface"], width=2)),
            hovertemplate=f"<b>{name}</b><br>Volatility: %{{x:.1%}}<br>Expected return: %{{y:.1%}}<extra></extra>",
        ))
    if risk_free is not None:
        fig.add_trace(go.Scatter(
            x=[0], y=[risk_free], mode="markers+text", name="Risk-free rate",
            text=["Risk-free"], textposition="middle right", textfont=dict(color=c["ink2"], size=11),
            marker=dict(size=9, symbol="square", color=c["neutral"], line=dict(color=c["surface"], width=2)),
            hovertemplate="<b>Risk-free (T-bill)</b><br>Return: %{y:.2%}<extra></extra>",
        ))
    fig = _base_layout(fig, mode, "Risk vs. return (annualized, historical)", height=460)
    fig.update_xaxes(title="Volatility (risk)", tickformat=".0%", rangemode="tozero")
    fig.update_yaxes(title="Expected annual return", tickformat=".0%")
    return fig


# --------------------------------------------------------------- projection

def projection_fan(
    proj: pd.DataFrame, initial: float, mode: str = "light", profile: str | None = None,
    title: str | None = None,
) -> go.Figure:
    """Fan chart: shaded 10th–90th percentile band with the median line.

    Args:
        proj: output of analytics.monte_carlo_projection (columns p10, p50, p90).
        profile: used to pick the color so it matches the profile elsewhere.
    """
    c = CHROME[mode]
    color = profile_color(profile, mode) if profile else PALETTE[mode]["blue"]
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    years = list(proj.index)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=proj["p90"], mode="lines", line=dict(width=0),
                             name="90th percentile", showlegend=False,
                             hovertemplate="Year %{x} — 90th pct: $%{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=years, y=proj["p10"], mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor=f"rgba({r},{g},{b},0.22)",
                             name="10th–90th percentile range",
                             hovertemplate="Year %{x} — 10th pct: $%{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=years, y=proj["p50"], mode="lines", line=dict(color=color, width=2.5),
                             name="Median outcome",
                             hovertemplate="Year %{x} — median: $%{y:,.0f}<extra></extra>"))
    fig.add_hline(y=initial, line=dict(color=c["muted"], width=1),
                  annotation_text=f"Starting amount ${initial:,.0f}", annotation_position="bottom right",
                  annotation_font=dict(color=c["muted"], size=11))
    # Direct labels at the horizon for the three percentiles.
    end = proj.iloc[-1]
    for col, lab in (("p90", "90th"), ("p50", "Median"), ("p10", "10th")):
        fig.add_annotation(x=years[-1], y=end[col], text=f"{lab}: ${end[col]:,.0f}", showarrow=False,
                           xanchor="left", xshift=6, font=dict(color=c["ink2"], size=12))
    fig = _base_layout(fig, mode, title or f"Projected value over {years[-1]} years (Monte Carlo)")
    # Legend below the plot: in narrow side-by-side columns a top legend collides with the title.
    fig.update_layout(hovermode="x unified", margin=dict(l=10, r=120, t=50, b=10),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0))
    fig.update_xaxes(title="Years from today", range=[0, years[-1]])
    fig.update_yaxes(title="Portfolio value", tickprefix="$", tickformat=",.0f", rangemode="tozero")
    return fig
