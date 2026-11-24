from html import escape
from pathlib import Path

import streamlit as st


MAP_LEGEND_ITEMS = (
    ("#ff0000", "Velame aberto"),
    ("#ffffff", "Queda livre"),
    ("#0000ff", "Arrasto"),
    ("#ffff00", "Dispersão"),
    ("#000000", "Margem"),
)


def _format_value(value, unit=""):
    try:
        return f"{float(value):,.0f}{unit}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _status_card(label, complete, detail):
    status_text = "Concluído" if complete else "Pendente"
    status_class = "is-complete" if complete else "is-pending"
    return (
        f'<article class="slop-status-card {status_class}">'
        f'<span class="slop-status-label">{escape(label)}</span>'
        f'<strong>{status_text}</strong>'
        f'<span class="slop-status-detail">{escape(detail)}</span>'
        "</article>"
    )


def render_mission_header(symbol_path: Path):
    logo_column, title_column = st.columns([0.65, 5], vertical_alignment="center")
    with logo_column:
        st.image(str(symbol_path), width=72)
    with title_column:
        st.markdown(
            '<p class="slop-brand-eyebrow">PLANEJAMENTO OPERACIONAL · SALTO LIVRE</p>'
            '<h1 class="slop-brand-title">Planejamento SLOp</h1>',
            unsafe_allow_html=True,
        )

    locality = str(st.session_state.get("localidade_alvo", "") or "").strip()
    altitude = st.session_state.get("altitude_ft")
    windgram = st.session_state.get("df_windgram")
    windgram_ready = windgram is not None and not getattr(windgram, "empty", True)
    windgram_value = (
        f"Processado · {len(windgram)} camadas" if windgram_ready else "Aguardando processamento"
    )
    dkva = st.session_state.get("dkva_latest")
    va_distance = _format_value(dkva.get("va_m"), " m") if isinstance(dkva, dict) else "—"
    ql_distance = _format_value(dkva.get("ql_m"), " m") if isinstance(dkva, dict) else "—"
    altitude_value = _format_value(altitude, " ft MSL") if locality else "—"
    metrics = (
        ("ZL / alvo", locality or "Não definido"),
        ("Altitude do alvo", altitude_value),
        ("Windgram", windgram_value),
        ("Distância VA", va_distance),
        ("Distância QL", ql_distance),
    )
    metric_markup = "".join(
        '<div class="slop-top-metric">'
        f'<span>{escape(label)}</span><strong>{escape(value)}</strong>'
        "</div>"
        for label, value in metrics
    )
    st.markdown(
        f'<section class="slop-top-metrics" aria-label="Resumo da missão">{metric_markup}</section>',
        unsafe_allow_html=True,
    )


def render_map_legend():
    items = "".join(
        '<span class="slop-map-legend-item">'
        f'<span class="slop-map-swatch" style="--swatch-color:{color}" aria-hidden="true"></span>'
        f"<span>{escape(label)}</span>"
        "</span>"
        for color, label in MAP_LEGEND_ITEMS
    )
    st.markdown(
        f'<div class="slop-map-legend" role="list" aria-label="Legenda do mapa">{items}</div>',
        unsafe_allow_html=True,
    )


def render_mission_dashboard(assets_dir: Path):
    locality = str(st.session_state.get("localidade_alvo", "") or "").strip()
    windgram = st.session_state.get("df_windgram")
    windgram_ready = windgram is not None and not getattr(windgram, "empty", True)
    dkva = st.session_state.get("dkva_latest")
    dkva_ready = isinstance(dkva, dict) and bool(dkva)

    st.markdown("## Painel da Missão")
    st.markdown(
        '<p class="slop-page-intro">Visão rápida do estado do planejamento e acesso às áreas da ferramenta.</p>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<section class="slop-feature-hero" aria-label="Abertura da missão">'
        '<div class="slop-feature-content">'
        '<p class="slop-brand-eyebrow">RAMPA · PLANEJAMENTO OPERACIONAL</p>'
        '<h2>Planejamento claro.<br>Decisão segura.</h2>'
        '<p>Consolide os dados da missão, processe o Windgram e acompanhe os resultados antes de avançar.</p>'
        "</div>"
        '<span class="slop-photo-credit">Foto: Exército Brasileiro</span>'
        "</section>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="slop-dashboard-status">'
        + _status_card("Identificação do alvo", bool(locality), locality or "Informe a ZL na área Planejamento / Windgram")
        + _status_card("Windgram", windgram_ready, "Camadas processadas" if windgram_ready else "Processe o Windgram para começar")
        + _status_card("Salto sobre o alvo", dkva_ready, "Resultado disponível" if dkva_ready else "Aguardando cálculo DKVA")
        + "</div>",
        unsafe_allow_html=True,
    )

    if not windgram_ready:
        st.info("Processe o Windgram para começar. As demais áreas continuam acessíveis pela navegação acima.")

    with st.expander("Referências visuais"):
        freefall_column, canopy_column = st.columns(2)
        with freefall_column:
            st.image(str(assets_dir / "queda_livre.jpg"), width="stretch")
            st.caption("Queda livre com equipamento de oxigênio")
        with canopy_column:
            st.image(str(assets_dir / "velame.jpg"), width="stretch")
            st.caption("Velame aberto")
