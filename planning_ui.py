from io import BytesIO
import math

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from calc_dkva import (
    AIRCRAFT,
    CANOPY_CATALOG,
    azimuth_and_distance,
    calculate_launch_geometry,
    coordinate_to_gms,
    destination,
    dispersion_distance,
    free_fall_distance,
    launch_entry_headings,
    launch_segment_specs,
    magnetic_to_true_azimuth,
    mean_wind,
    navigation_axis_magnetic,
    normalize_azimuth,
    opposite_azimuth,
    one_minute_out,
    round_heading_to_five,
    true_to_magnetic_azimuth,
    va_distance,
    va_sensitivity,
    vertical_speed_fps,
    vertical_speed_mps,
)
from daa import (
    altimeter_adjustment,
    cypres_adjustment,
    isa_pressure_hpa,
    round_qnh_to_even,
    round_vigil_military_ps_altitude,
    vigil_adjustment,
)
from equipes import (
    CANOPY_SCALE,
    CATEGORY_MINIMUMS,
    WORK_SCALE,
    assign_command_heights,
    minimum_command_height,
    sort_team,
    validate_command_height_edits,
)
from kml_export import export_kmz, export_kmz_folders
from mission_dashboard import render_map_legend


SEGMENT_COLORS = {
    "velame": "#ff0000",
    "queda": "#ffffff",
    "arrasto": "#0000ff",
    "dispersao": "#ffff00",
    "margem": "#000000",
    "pouso": "#00ff00",
}

LAUNCH_TYPES = ["Nariz", "Cauda", "Boca do Cone"]


def _round_heading(value):
    return round_heading_to_five(value)


CANOPY_EDITOR_KEY = "canopy_catalog_editor"
CANOPY_DATA_KEY = "dkva_canopy_catalog_data"


def _initial_canopy_frame():
    rows = []
    for canopy in CANOPY_CATALOG:
        speed = canopy["speed_kt"]
        glide = canopy["glide"]
        rows.append({
            "Modelo": canopy["model"],
            "Uso na Divisão": canopy["team_label"],
            "Tamanho (ft²)": str(canopy["size_ft2"]),
            "V (kt)": "[A CONFIRMAR]" if speed is None else f"{speed:g}",
            "G": "[A CONFIRMAR]" if glide is None else f"{glide:g}",
            "Vv (ft/s)": "[A CONFIRMAR]",
            "Vv (m/s)": "[A CONFIRMAR]",
            "Razão de avanço": "[A CONFIRMAR]",
            "Fonte": canopy["source"],
            "Link da fonte": canopy["source_url"],
            "Consulta": canopy["consulted_on"],
        })
    return pd.DataFrame(rows)


def _catalog_number(value, model, label):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", ".")
    if not text or text.upper() == "[A CONFIRMAR]":
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{model}: {label} deve ser numérico ou [A CONFIRMAR].") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{model}: {label} deve ser maior que zero.")
    return number


def _refresh_canopy_frame(frame):
    refreshed = frame.copy()
    errors = []
    values = {}
    for index, row in refreshed.iterrows():
        model = str(row["Modelo"])
        try:
            speed = _catalog_number(row["V (kt)"], model, "V (kt)")
            glide = _catalog_number(row["G"], model, "G")
        except ValueError as exc:
            errors.append(str(exc))
            speed = None
            glide = None
        if speed is None or glide is None:
            refreshed.at[index, "Vv (ft/s)"] = "[A CONFIRMAR]"
            refreshed.at[index, "Vv (m/s)"] = "[A CONFIRMAR]"
            refreshed.at[index, "Razão de avanço"] = "[A CONFIRMAR]"
        else:
            refreshed.at[index, "Vv (ft/s)"] = f"{vertical_speed_fps(speed, glide):.2f}"
            refreshed.at[index, "Vv (m/s)"] = f"{vertical_speed_mps(speed, glide):.2f}"
            refreshed.at[index, "Razão de avanço"] = f"{glide:.2f}"
        values[model] = {"speed_kt": speed, "glide": glide}
    return refreshed, values, errors


def _migrate_legacy_canopy_catalog(frame):
    migrated = frame.copy()
    for canopy in CANOPY_CATALOG:
        rows = migrated.index[migrated["Modelo"].astype(str) == canopy["model"]]
        if not len(rows):
            continue

        index = rows[0]
        if (
            canopy["size_ft2"] != "[A CONFIRMAR]"
            and str(migrated.at[index, "Tamanho (ft²)"]).strip().upper()
            == "[A CONFIRMAR]"
        ):
            migrated.at[index, "Tamanho (ft²)"] = str(canopy["size_ft2"])
            migrated.at[index, "Fonte"] = canopy["source"]

        if canopy["model"] == "VP 300":
            old_source = str(migrated.at[index, "Fonte"])
            old_glide = str(migrated.at[index, "G"]).strip().replace(",", ".")
            if (
                old_glide == "3.2"
                and "G da planilha mantido como referência de cálculo" in old_source
            ):
                migrated.at[index, "G"] = f"{canopy['glide']:g}"
                migrated.at[index, "Fonte"] = canopy["source"]
    return migrated


def _render_canopy_catalog_editor():
    st.markdown("#### Tabela técnica única de velames")
    st.caption(
        "Vv (ft/s) = V × 1,68781 / G; Vv (m/s) = Vv × 0,3048. "
        "Razão de avanço = G é uma premissa de distância horizontal sem vento por unidade de altura; "
        "não foi localizada definição CSL pública. Valores sem fonte permanecem [A CONFIRMAR]."
    )
    st.caption(
        "VP 300: base de cálculo G=3.5 e área de 372 ft² conforme a imagem 3; "
        "a planilha anterior indicava G=3.2."
    )
    existing = st.session_state.get(CANOPY_DATA_KEY)
    if not isinstance(existing, pd.DataFrame):
        existing, _, _ = _refresh_canopy_frame(_initial_canopy_frame())
    else:
        existing = _migrate_legacy_canopy_catalog(existing)
    st.session_state[CANOPY_DATA_KEY] = existing

    edited = st.data_editor(
        existing,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=CANOPY_EDITOR_KEY,
        disabled=[
            "Modelo",
            "Uso na Divisão",
            "Vv (ft/s)",
            "Vv (m/s)",
            "Razão de avanço",
        ],
        column_config={
            "Modelo": st.column_config.TextColumn(),
            "Uso na Divisão": st.column_config.TextColumn(),
            "Tamanho (ft²)": st.column_config.TextColumn(),
            "V (kt)": st.column_config.TextColumn(),
            "G": st.column_config.TextColumn(),
            "Vv (ft/s)": st.column_config.TextColumn(),
            "Vv (m/s)": st.column_config.TextColumn(),
            "Razão de avanço": st.column_config.TextColumn(),
            "Fonte": st.column_config.TextColumn(),
            "Link da fonte": st.column_config.LinkColumn(
                display_text="Abrir fonte",
            ),
            "Consulta": st.column_config.TextColumn(),
        },
    )
    refreshed, values, errors = _refresh_canopy_frame(edited)
    st.session_state[CANOPY_DATA_KEY] = refreshed
    st.session_state.dkva_parachute_config = values
    if errors:
        st.error("Tabela de velames inválida: " + " ".join(errors))
    return values, bool(errors)


def _north_cutoff(altitudes_ft, target_ft):
    raw_cutoff = target_ft + 750
    altitudes = sorted(set(float(value) for value in altitudes_ft))
    for lower, upper in zip(altitudes, altitudes[1:]):
        if lower <= raw_cutoff <= upper:
            midpoint = (lower + upper) / 2.0
            return lower if raw_cutoff > midpoint else lower - 1
    return raw_cutoff


def _layer_options(wind_df, target_ft, command_ft, launch_ft):
    if wind_df is None or wind_df.empty:
        return [], [], pd.DataFrame()
    frame = wind_df.copy()
    cutoff = _north_cutoff(frame["Altitude NOAA ft"].tolist(), target_ft)
    command_msl = target_ft + command_ft
    launch_msl = target_ft + launch_ft
    frame["Camada DKVA"] = "Fora da camada"
    frame.loc[
        (frame["Altitude NOAA ft"] > cutoff)
        & (frame["Altitude NOAA ft"] <= command_msl),
        "Camada DKVA",
    ] = "Velame"
    frame.loc[
        (frame["Altitude NOAA ft"] > command_msl)
        & (frame["Altitude NOAA ft"] <= launch_msl),
        "Camada DKVA",
    ] = "Queda livre"
    va = (
        frame.loc[frame["Camada DKVA"] == "Velame", "Pressão mb"]
        .astype(int)
        .tolist()
    )
    ql = (
        frame.loc[frame["Camada DKVA"] == "Queda livre", "Pressão mb"]
        .astype(int)
        .tolist()
    )
    return va, ql, frame


def _wind_summary(frame, selected_mb):
    selected = frame[frame["Pressão mb"].isin(selected_mb)].copy()
    if selected.empty:
        return None, selected
    result = mean_wind(
        selected["Direção °"].astype(float).tolist(),
        selected["Velocidade kt"].astype(float).tolist(),
    )
    return result, selected


def _segment_defaults(launch_type, va_m, ql_m, va_dir, ql_dir, dispersion, drag, margin):
    return launch_segment_specs(
        launch_type,
        va_m,
        ql_m,
        va_dir,
        ql_dir,
        dispersion,
        drag,
        safety_m=margin,
    )


def _overrides_from_editor(editor_frame):
    return {
        row["segment_id"]: {
            "distance_m": float(row["distance_m"]),
            "azimuth": float(row["azimuth_deg"]),
        }
        for _, row in editor_frame.iterrows()
    }


def _ps_description(point, direction_context):
    landing = direction_context["landing_direction_true"]
    landing_magnetic = direction_context["landing_direction_magnetic"]
    landing_text = (
        "Sem eixo de pouso calculado"
        if landing is None
        else f"{landing:.0f}° V / {landing_magnetic:03.0f}° M"
    )
    return "\n".join([
        f"Entrada da aeronave: {point['entry_heading_magnetic']:03.0f}° M / "
        f"{point['entry_heading_true']:03.0f}° V",
        f"Vento médio de velame: {direction_context['va_direction_true']:.0f}° V / "
        f"{direction_context['va_direction_magnetic']:03.0f}° M",
        f"Vento médio de queda livre: {direction_context['ql_direction_true']:.0f}° V / "
        f"{direction_context['ql_direction_magnetic']:03.0f}° M",
        f"Vento de superfície, de onde vem (V/M): {landing_text}",
        f"Proa de pouso contra o vento (V/M): {landing_text}",
        f"Eixo de navegação magnético: {direction_context['navigation_magnetic']:03.0f}°",
        f"Posição alvo→PS: {point['distance_to_target_m']:.0f} m, "
        f"{point['target_to_ps_true']:.0f}° V / {point['target_to_ps_magnetic']:03.0f}° M",
        f"Azimute PS→alvo magnético: {point['ps_to_target_magnetic']:03.0f}°",
        f"Coordenada PS (GMS): {point['ps_gms']}",
        f"Coordenada PS (GD): {point['ps_gd']}",
        f"Coordenada 1' fora (GMS): {point['one_minute_out_gms']}",
        f"Coordenada 1' fora (GD): {point['one_minute_out_gd']}",
    ])


def _placemarks_for_geometry(
    launch_type,
    lat,
    lon,
    segments,
    gdh,
    ps_records,
    direction_context,
    landing_direction=None,
    landing_speed=None,
):
    def named_time(name):
        return f"{name} {gdh}Z" if gdh.strip() else name

    placemarks = [{
        "type": "point",
        "name": "ALVO",
        "coordinates": (lat, lon),
    }]
    if landing_direction is not None:
        landing_end = destination(lat, lon, 500, landing_direction)
        placemarks.extend([
            {
                "type": "line",
                "name": "Eixo de Pouso (500m)",
                "style": "pouso",
                "coordinates": ((lat, lon), landing_end),
            },
            {
                "type": "point",
                "name": f"Provável direção de pouso — {landing_speed:.1f} kt",
                "coordinates": landing_end,
            },
        ])
    terminal_names = {
        "Nariz": {"drag": named_time("PS NARIZ")},
        "Cauda": {"drag": named_time("PS CAUDA")},
        "Boca do Cone": {
            "drag_1": named_time("PS BC 1"),
            "drag_2": named_time("PS BC 2"),
        },
    }
    for segment in segments:
        name = segment["name"]
        if segment["id"] == "va":
            name = named_time("VELAME ABERTO")
        placemarks.append({
            "type": "line",
            "name": name,
            "style": segment["style"],
            "coordinates": (segment["start_coord"], segment["end_coord"]),
        })
    for segment_id, name in terminal_names[launch_type].items():
        point = next(item for item in ps_records if item["segment_id"] == segment_id)
        placemarks.append({
            "type": "point",
            "name": name,
            "coordinates": point["coordinates"],
            "description": _ps_description(point, direction_context),
        })
        placemarks.append({
            "type": "point",
            "name": f"1' FORA — {launch_type} — {point['name']}",
            "coordinates": point["one_minute_out"],
            "description": (
                f"Distância PS–1' fora: {point['one_minute_out_distance_m']:.0f} m\n"
                f"GMS: {point['one_minute_out_gms']}\nGD: {point['one_minute_out_gd']}"
            ),
        })
        placemarks.append({
            "type": "line",
            "name": f"Reta 1' fora–PS — {point['name']}",
            "style": "minuto_fora",
            "coordinates": (point["one_minute_out"], point["coordinates"]),
        })
    if launch_type == "Nariz":
        terminal = next(segment for segment in segments if segment["id"] == "limit")
        placemarks.append({
            "type": "point",
            "name": "Limite",
            "coordinates": terminal["end_coord"],
        })
    elif launch_type == "Cauda":
        terminal = next(segment for segment in segments if segment["id"] == "last_drag")
        placemarks.append({
            "type": "point",
            "name": "Limite LÇMTO CAUDA",
            "coordinates": terminal["end_coord"],
        })
    return placemarks


def _kmz_for_geometry(
    launch_type,
    lat,
    lon,
    segments,
    gdh,
    ps_records,
    direction_context,
    folder_name,
    landing_direction=None,
    landing_speed=None,
):
    placemarks = _placemarks_for_geometry(
        launch_type,
        lat,
        lon,
        segments,
        gdh,
        ps_records,
        direction_context,
        landing_direction,
        landing_speed,
    )
    return export_kmz(folder_name, placemarks)


def _launch_folder_name(launch_type, entry_headings):
    headings = entry_headings[launch_type]
    if launch_type == "Boca do Cone":
        return (
            f"Lançamento Boca do Cone — ENTRADAS {headings[0]:03.0f}° (PS 1) / "
            f"{headings[1]:03.0f}° (PS 2)"
        )
    return f"Lançamento {launch_type} — ENTRADA {headings[0]:03.0f}°"


def _ps_records_for_geometry(
    launch_type,
    segments,
    target,
    entry_headings,
    aircraft_speed_ms,
    declination,
):
    terminal_specs = {
        "Nariz": [("drag", "PS NARIZ")],
        "Cauda": [("drag", "PS CAUDA")],
        "Boca do Cone": [("drag_1", "PS BC 1"), ("drag_2", "PS BC 2")],
    }
    segment_by_id = {segment["id"]: segment for segment in segments}
    records = []
    for (segment_id, name), entry_magnetic in zip(
        terminal_specs[launch_type],
        entry_headings[launch_type],
    ):
        ps = segment_by_id[segment_id]["end_coord"]
        target_to_ps_true, distance_m = azimuth_and_distance(
            target[0],
            target[1],
            ps[0],
            ps[1],
        )
        ps_to_target_true, _ = azimuth_and_distance(
            ps[0],
            ps[1],
            target[0],
            target[1],
        )
        one_out = one_minute_out(
            ps[0],
            ps[1],
            aircraft_speed_ms,
            entry_magnetic,
            declination,
        )
        one_out_lat, one_out_lon = one_out["coordinate"]
        records.append({
            "segment_id": segment_id,
            "name": name,
            "coordinates": ps,
            "entry_heading_magnetic": entry_magnetic,
            "entry_heading_true": one_out["entry_heading_true"],
            "ps_to_target_true": ps_to_target_true,
            "ps_to_target_magnetic": true_to_magnetic_azimuth(
                ps_to_target_true,
                declination,
            ),
            "target_to_ps_true": target_to_ps_true,
            "target_to_ps_magnetic": true_to_magnetic_azimuth(
                target_to_ps_true,
                declination,
            ),
            "distance_to_target_m": distance_m,
            "one_minute_out": one_out["coordinate"],
            "one_minute_out_distance_m": one_out["distance_m"],
            "ps_gms": coordinate_to_gms(*ps),
            "ps_gd": f"{ps[0]:.7f}, {ps[1]:.7f}",
            "one_minute_out_gms": coordinate_to_gms(one_out_lat, one_out_lon),
            "one_minute_out_gd": f"{one_out_lat:.7f}, {one_out_lon:.7f}",
        })
    return records


def _geometry_table(segments):
    rows = []
    for segment in segments:
        start_lat, start_lon = segment["start_coord"]
        end_lat, end_lon = segment["end_coord"]
        rows.append({
            "Segmento": segment["name"],
            "Azimute (°)": round(segment["azimuth"], 1),
            "Distância (m)": round(segment["distance_m"], 1),
            "Lat início": round(start_lat, 7),
            "Lon início": round(start_lon, 7),
            "Lat fim": round(end_lat, 7),
            "Lon fim": round(end_lon, 7),
        })
    return pd.DataFrame(rows)


def render_dkva(create_base_map, location_search, terrain_lookup, weighted_direction):
    st.subheader("SALTO SOBRE O ALVO (DKVA)")
    st.warning(
        "Ferramenta de apoio ao MSL. Confira os dados meteorológicos oficiais, "
        "a doutrina e cada segmento antes de qualquer decisão."
    )
    wind_df = st.session_state.get("df_windgram")
    if wind_df is None or wind_df.empty:
        st.info("Processe o Windgram na aba Planejamento / Windgram para habilitar o DKVA.")
        return

    st.markdown("#### Parâmetros de entrada")
    with st.expander("Tabela técnica única de velames — DKVA e Divisão das Equipes"):
        catalog_values, catalog_invalid = _render_canopy_catalog_editor()
    if catalog_invalid:
        return
    parachute_config = {
        model: data
        for model, data in catalog_values.items()
        if data["speed_kt"] is not None and data["glide"] is not None
    }
    if not parachute_config:
        st.error("Cadastre V e G para pelo menos um velame.")
        return
    st.session_state.dkva_parachute_config = parachute_config
    parachute_names = list(catalog_values)
    selected_parachute_index = (
        parachute_names.index("VP 300") if "VP 300" in parachute_names else 0
    )
    if st.session_state.get("dkva_parachute") not in parachute_names:
        st.session_state.dkva_parachute = parachute_names[selected_parachute_index]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        target_ft = st.number_input(
            "Altitude da área de salto (ft MSL)",
            min_value=0.0,
            value=float(st.session_state.get("altitude_ft", 0.0)),
            step=50.0,
            key="dkva_alt_area",
        )
    with c2:
        default_command = float(st.session_state.get("altura_comandamento_ft", 5500.0))
        command_ft = st.number_input(
            "Altura de comandamento / abertura (ft AGL)",
            min_value=0.0,
            value=default_command,
            step=100.0,
            key="dkva_command_ft",
        )
    with c3:
        default_launch = float(st.session_state.get("altura_saida_ft", 10300.0))
        launch_ft = st.number_input(
            "Altura de lançamento (ft AGL)",
            min_value=0.0,
            value=default_launch,
            step=100.0,
            key="dkva_launch_ft",
        )
    with c4:
        parachute = st.selectbox(
            "Paraquedas",
            parachute_names,
            index=selected_parachute_index,
            key="dkva_parachute",
        )

    st.session_state.altitude_ft = float(target_ft)
    st.session_state.altura_comandamento_ft = float(command_ft)
    st.session_state.altura_saida_ft = float(launch_ft)
    parachute_data = catalog_values[parachute]
    if parachute_data["speed_kt"] is None or parachute_data["glide"] is None:
        st.error(
            f"V ou G de {parachute} está [A CONFIRMAR]. "
            "Atualize a tabela técnica ou selecione um velame com valores disponíveis."
        )
        return
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        va_speed = float(parachute_data["speed_kt"])
        st.metric("Velocidade do velame V (kt)", f"{va_speed:.2f}")
    with c6:
        glide = float(parachute_data["glide"])
        st.metric("Razão de planeio G", f"{glide:.2f}")
    with c7:
        st.metric("Vv (ft/s)", f"{vertical_speed_fps(va_speed, glide):.2f}")
    with c8:
        st.metric("Vv (m/s)", f"{vertical_speed_mps(va_speed, glide):.2f}")
    c9, c10 = st.columns(2)
    with c9:
        minimum_over_target = st.number_input(
            "Altura mínima sobre o alvo (ft)",
            min_value=0.0,
            value=1500.0,
            step=100.0,
            key="dkva_min_over_target",
        )
    with c10:
        margin_factor = st.number_input(
            "Fator de margem",
            min_value=0.0,
            max_value=1.5,
            value=0.75,
            step=0.05,
            key="dkva_margin_factor",
            help="0,75 aplica a margem de 25% indicada na planilha.",
        )

    va_layers, ql_layers, classified = _layer_options(
        wind_df, target_ft, command_ft, launch_ft
    )
    st.caption(
        "Camadas DKVA: sem perda no comandamento; o corte do vento de solo usa "
        "a regra da metade do intervalo já aplicada pelo app."
    )
    if not va_layers:
        st.error("Não há níveis Windgram classificados na camada de velame para esses parâmetros.")
        return
    if not ql_layers:
        st.error("Não há níveis Windgram classificados na camada de queda livre para esses parâmetros.")
        return

    st.markdown("#### Seleção das camadas NOAA")
    l1, l2 = st.columns(2)
    with l1:
        selected_va = st.multiselect(
            "Camadas do velame (mb)",
            va_layers,
            default=va_layers,
            key="dkva_selected_va",
        )
    with l2:
        selected_ql = st.multiselect(
            "Camadas da queda livre (mb)",
            ql_layers,
            default=ql_layers,
            key="dkva_selected_ql",
        )
    va_summary, va_frame = _wind_summary(classified, selected_va)
    ql_summary, ql_frame = _wind_summary(classified, selected_ql)
    if va_summary is None or ql_summary is None:
        st.error("Selecione ao menos um nível válido para velame e queda livre.")
        return

    declination = float(
        st.session_state.get(
            "dkva_declination",
            st.session_state.get(
                "declinacao_usada",
                st.session_state.get("declinacao", 0.0),
            ),
        ) or 0.0
    )
    landing_data = wind_df[wind_df["Fase"] == "Velame aberto"].copy()
    landing_data = landing_data.sort_values("Altitude NOAA ft", ascending=True).head(2)
    landing_direction = None
    landing_speed = None
    if not landing_data.empty:
        landing_directions = landing_data["Direção °"].astype(float).tolist()
        landing_speeds = landing_data["Velocidade kt"].astype(float).tolist()
        landing_direction = weighted_direction(landing_directions, landing_speeds)
        landing_speed = sum(landing_speeds) / len(landing_speeds)

    for phase, summary, frame in (
        ("Velame", va_summary, va_frame),
        ("Queda livre", ql_summary, ql_frame),
    ):
        with st.expander(f"Camadas usadas — {phase}"):
            st.dataframe(
                frame[["Pressão mb", "Altitude NOAA ft", "Direção °", "Velocidade kt"]],
                hide_index=True,
                use_container_width=True,
            )
            magnetic_direction = true_to_magnetic_azimuth(
                summary["arithmetic_direction"],
                declination,
            )
            st.write(
                f"Vento médio: **{summary['speed_kt']:.2f} kt** · "
                f"Média aritmética: **{summary['raw_arithmetic_direction']}°** · "
                f"Direção usada verdadeira/magnética: "
                f"**{summary['arithmetic_direction']:.0f}° / {magnetic_direction:03.0f}°**"
            )
            if summary["crosses_north"]:
                st.warning("Camadas cruzam o norte: a média aritmética foi substituída pela média circular.")

    try:
        va_m = va_distance(
            command_ft,
            minimum_over_target,
            va_summary["speed_kt"],
            va_speed,
            glide,
            margin_factor,
        )
        ql_m = free_fall_distance(
            ql_summary["speed_kt"],
            launch_ft,
            command_ft,
        )
        dispersion_full = dispersion_distance(
            int(st.session_state.get("nb_dkva", 7)),
            float(st.session_state.get("ib_dkva", 3.0)),
            70.0,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    st.markdown("#### Aeronave e processo")
    p1, p2, p3, p4 = st.columns(4)
    aircraft_names = list(AIRCRAFT)
    with p1:
        aircraft = st.selectbox("Aeronave", aircraft_names, index=aircraft_names.index("C-105"), key="dkva_aircraft")
    with p2:
        aircraft_speed = st.number_input(
            "Velocidade de lançamento (m/s)",
            min_value=1.0,
            value=float(AIRCRAFT[aircraft]["speed_ms"]),
            step=1.0,
            key=f"dkva_air_speed_{aircraft}",
        )
    with p3:
        drag_m = st.number_input(
            "Arrasto da aeronave (m)",
            min_value=0.0,
            value=float(AIRCRAFT[aircraft]["drag_m"]),
            step=10.0,
            key=f"dkva_drag_{aircraft}",
        )
    with p4:
        blocks = st.number_input("NB — número de blocos", min_value=1, value=7, step=1, key="nb_dkva")
    p5, p6, p7, p8 = st.columns(4)
    with p5:
        interval = st.number_input("I — intervalo entre blocos (s)", min_value=0.0, value=3.0, step=0.5, key="ib_dkva")
    with p6:
        declination = st.number_input(
            "Declinação magnética WMM / manual (°)",
            value=declination,
            step=0.1,
            key="dkva_declination",
            help="Oeste negativo. A proa magnética é calculada como verdadeiro − declinação.",
        )
        st.caption(
            "Fonte: declinação geomag salva pelo app ou sobrescrita manualmente. "
            "O pacote instalado contém WMM-2015; a comparação com o NCEI não foi concluída "
            "(o endpoint exige chave). Nenhum modelo foi atualizado."
        )
    with p7:
        gdh = st.text_input("GDH da missão (Zulu, opcional)", key="dkva_gdh")
    with p8:
        launch_type = st.radio(
            "Tipo de lançamento",
            LAUNCH_TYPES,
            horizontal=False,
            key="tipo_lanc_dkva_radio",
        )
    st.session_state.ae_dkva = aircraft
    st.session_state.declinacao_usada = declination
    dispersion_full = dispersion_distance(blocks, interval, aircraft_speed)

    try:
        margin_rules_default = pd.DataFrame([
            {"Até (m)": 1000, "Margem (m)": 200},
            {"Até (m)": 2000, "Margem (m)": 400},
            {"Até (m)": 3000, "Margem (m)": 800},
            {"Até (m)": 4000, "Margem (m)": 1000},
        ])
        with st.expander("Tabela editável de margem de segurança Boca do Cone"):
            margin_rules = st.data_editor(
                margin_rules_default,
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                key="dkva_margin_rules",
            )
        thresholds = margin_rules["Até (m)"].astype(float).tolist()
        if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
            st.error("Os limites da tabela de margem devem ser crescentes e sem duplicatas.")
            return
        if any(float(value) < 0 for value in margin_rules["Margem (m)"]):
            st.error("A margem de segurança não pode ser negativa.")
            return
        margin_m = None
        for _, row in margin_rules.iterrows():
            if va_m < float(row["Até (m)"]):
                margin_m = float(row["Margem (m)"])
                break
    except (ValueError, KeyError) as exc:
        st.error(f"Tabela de margem inválida: {exc}")
        return

    va_direction = float(va_summary["arithmetic_direction"])
    ql_direction = float(ql_summary["arithmetic_direction"])
    declination = float(declination)
    va_direction_magnetic = true_to_magnetic_azimuth(va_direction, declination)
    ql_direction_magnetic = true_to_magnetic_azimuth(ql_direction, declination)
    landing_direction_magnetic = (
        None
        if landing_direction is None
        else true_to_magnetic_azimuth(landing_direction, declination)
    )
    entry_headings = launch_entry_headings(va_direction, declination)
    heading_nose = entry_headings["Nariz"][0]
    heading_tail = entry_headings["Cauda"][0]
    heading_bc, reverse_heading_bc = entry_headings["Boca do Cone"]
    navigation_magnetic = navigation_axis_magnetic(va_direction, declination)
    st.markdown("#### Resultado e azimutes auxiliares")
    metrics = st.columns(4)
    metrics[0].metric("Velame aberto", f"{va_m} m")
    metrics[1].metric("Queda livre", f"{ql_m} m")
    metrics[2].metric("Dispersão total", f"{dispersion_full:.0f} m")
    metrics[3].metric("Arrasto", f"{drag_m:.0f} m")
    direction_columns = st.columns(4)
    direction_columns[0].metric(
        "Vento médio — velame (V/M)",
        f"{va_direction:.0f}° / {va_direction_magnetic:03.0f}°",
    )
    direction_columns[1].metric(
        "Vento médio — queda livre (V/M)",
        f"{ql_direction:.0f}° / {ql_direction_magnetic:03.0f}°",
    )
    direction_columns[2].metric(
        "Vento superfície — de onde vem (V/M)",
        "—"
        if landing_direction is None
        else f"{landing_direction:.0f}° / {landing_direction_magnetic:03.0f}°",
    )
    direction_columns[3].metric(
        "Proa de pouso contra o vento (V/M)",
        "—"
        if landing_direction is None
        else f"{landing_direction:.0f}° / {landing_direction_magnetic:03.0f}°",
    )
    entry_text = {
        "Nariz": f"PS: {heading_nose:03.0f}°",
        "Cauda": f"PS: {heading_tail:03.0f}°",
        "Boca do Cone": (
            f"PS 1: {heading_bc:03.0f}° · PS 2: {reverse_heading_bc:03.0f}°"
        ),
    }[launch_type]
    axis_columns = st.columns(3)
    axis_columns[0].metric("Eixo de navegação (mag)", f"{navigation_magnetic:03.0f}°")
    axis_columns[1].metric(f"Proa de entrada (mag) — {launch_type}", entry_text)
    axis_columns[2].metric("Declinação aplicada", f"{declination:+.1f}°")
    st.write({
        "Contra-azimute VA": f"{opposite_azimuth(va_direction):.0f}°",
        "Perpendiculares BC": f"{normalize_azimuth(va_direction + 90):03.0f}° / {normalize_azimuth(va_direction - 90):03.0f}°",
        "Entrada Nariz (mag)": f"{heading_nose:03.0f}°",
        "Entrada Cauda (mag)": f"{heading_tail:03.0f}°",
        "Entrada Boca do Cone (mag)": f"{heading_bc:03.0f}° / {reverse_heading_bc:03.0f}°",
        "Navegação magnética": f"{navigation_magnetic:03.0f}°",
        "Conversões": f"{va_m * 3.281:.0f} ft · {va_m / 1852:.3f} NM",
    })
    if va_summary["speed_kt"] >= va_speed:
        st.error("W ≥ Va → sem progressão")
        return

    with st.expander("Sensibilidade do velame — vento de 0 a 20 kt"):
        st.dataframe(
            pd.DataFrame(va_sensitivity(command_ft, minimum_over_target, va_speed, glide)),
            hide_index=True,
            use_container_width=True,
        )

    try:
        if launch_type == "Boca do Cone" and margin_m is None:
            st.error("Velame aberto fora da tabela de margem: cálculo Boca do Cone bloqueado; decisão do MSL necessária.")
            return
        margin_for_specs = margin_m if margin_m is not None else 0
        specs = _segment_defaults(
            launch_type,
            va_m,
            ql_m,
            va_direction,
            ql_direction,
            dispersion_full,
            drag_m,
            margin_for_specs,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    all_overrides = dict(st.session_state.get("dkva_segment_overrides", {}))
    editor_key = f"dkva_segments_editor_{launch_type}"
    saved_for_type = all_overrides.get(launch_type, {})
    editor_initial = pd.DataFrame([
        {
            "segment_id": spec["id"],
            "Segmento": spec["name"],
            "azimuth_deg": saved_for_type.get(spec["id"], {}).get("azimuth", spec["azimuth"]),
            "distance_m": saved_for_type.get(spec["id"], {}).get("distance_m", spec["distance_m"]),
        }
        for spec in specs
    ])
    with st.expander("Editar todos os segmentos antes de calcular as coordenadas", expanded=True):
        edited = st.data_editor(
            editor_initial,
            hide_index=True,
            use_container_width=True,
            key=editor_key,
            disabled=["segment_id", "Segmento"],
            column_config={
                "azimuth_deg": st.column_config.NumberColumn("Azimute (°)", min_value=0.0, max_value=359.9, step=1.0),
                "distance_m": st.column_config.NumberColumn("Comprimento (m)", min_value=0.0, step=10.0),
            },
        )
    current_overrides = _overrides_from_editor(edited)
    all_overrides[launch_type] = current_overrides
    st.session_state.dkva_segment_overrides = all_overrides

    lat = float(st.session_state.get("lat", 0.0))
    lon = float(st.session_state.get("lon", 0.0))
    all_geometries = {}
    for kind in LAUNCH_TYPES:
        if kind == "Boca do Cone" and margin_m is None:
            continue
        kind_specs = _segment_defaults(
            kind,
            va_m,
            ql_m,
            va_direction,
            ql_direction,
            dispersion_full,
            drag_m,
            margin_for_specs,
        )
        segments, anchors = calculate_launch_geometry(
            lat, lon, kind_specs, all_overrides.get(kind, {})
        )
        all_geometries[kind] = {"segments": segments, "anchors": anchors}
    segments = all_geometries[launch_type]["segments"]
    st.dataframe(_geometry_table(segments), hide_index=True, use_container_width=True)
    point_records_by_type = {
        kind: _ps_records_for_geometry(
            kind,
            geometry["segments"],
            (lat, lon),
            entry_headings,
            aircraft_speed,
            declination,
        )
        for kind, geometry in all_geometries.items()
    }
    selected_point_records = point_records_by_type[launch_type]
    if launch_type == "Boca do Cone":
        bc_ps = st.radio(
            "Ponto BC integrado ao Folder/DAA",
            ["PS BC 1", "PS BC 2"],
            horizontal=True,
            key="dkva_bc_ps_selected",
        )
        selected_ps_id = "drag_1" if bc_ps == "PS BC 1" else "drag_2"
        selected_point = next(
            point for point in selected_point_records
            if point["segment_id"] == selected_ps_id
        )
    elif launch_type == "Cauda":
        selected_point = selected_point_records[0]
    else:
        selected_point = selected_point_records[0]
    point_rows = []
    landing_true_text = (
        "—"
        if landing_direction is None
        else f"{landing_direction:.0f}° V / {landing_direction_magnetic:03.0f}° M"
    )
    for point in selected_point_records:
        point_rows.append({
            "Ponto": point["name"],
            "Vento VA (V/M)": f"{va_direction:.0f}° / {va_direction_magnetic:03.0f}°",
            "Vento QL (V/M)": f"{ql_direction:.0f}° / {ql_direction_magnetic:03.0f}°",
            "Vento superfície (V/M)": landing_true_text,
            "Proa pouso (V/M)": landing_true_text,
            "Navegação (mag)": f"{navigation_magnetic:03.0f}°",
            "Entrada aeronave (mag)": f"{point['entry_heading_magnetic']:03.0f}°",
            "Azimute PS→alvo (mag)": f"{point['ps_to_target_magnetic']:03.0f}°",
            "Posição alvo→PS": (
                f"{point['distance_to_target_m']:.0f} m · "
                f"{point['target_to_ps_true']:.0f}° V / "
                f"{point['target_to_ps_magnetic']:03.0f}° M"
            ),
            "Coordenada PS (GMS)": point["ps_gms"],
            "Coordenada PS (GD)": point["ps_gd"],
            "1' fora (GMS)": point["one_minute_out_gms"],
            "1' fora (GD)": point["one_minute_out_gd"],
        })
    st.markdown("#### Pontos de saída e azimutes")
    st.dataframe(pd.DataFrame(point_rows), hide_index=True, use_container_width=True)
    selected_ps = selected_point["coordinates"]
    st.session_state.ps_lat, st.session_state.ps_lon = selected_ps
    st.session_state.ps_origem = f"PS DKVA ({launch_type})"
    if st.button("Consultar altitude/QFE do PS selecionado", key="dkva_query_ps_weather"):
        with st.spinner("Consultando altitude e pressão do PS..."):
            ps_altitude, ps_qfe = terrain_lookup(*selected_ps)
        if ps_altitude is not None:
            st.session_state.altitude_consulta_ft = float(ps_altitude)
        if ps_qfe is not None:
            st.session_state.qfe_consulta_hpa = float(ps_qfe)
        if ps_altitude is None and ps_qfe is None:
            st.error("A consulta do PS não retornou altitude nem QFE.")
        else:
            st.success("Dados do PS atualizados para a aba Ajuste de DAA.")
    st.session_state.dkva_latest = {
        "launch_type": launch_type,
        "va_m": va_m,
        "ql_m": ql_m,
        "va_direction": va_direction,
        "ql_direction": ql_direction,
        "va_direction_magnetic": va_direction_magnetic,
        "ql_direction_magnetic": ql_direction_magnetic,
        "landing_direction_true": landing_direction,
        "landing_direction_magnetic": landing_direction_magnetic,
        "navigation_magnetic": navigation_magnetic,
        "entry_headings": entry_headings,
        "declination": declination,
        "aircraft_speed_ms": aircraft_speed,
        "points_by_type": point_records_by_type,
        "segments": segments,
        "ps_lat": selected_ps[0],
        "ps_lon": selected_ps[1],
        "selected_ps_id": selected_point["segment_id"],
    }

    st.markdown("#### Mapa satelital")
    map_type = st.selectbox("Geometria exibida no mapa", ["Todos"] + LAUNCH_TYPES, key="dkva_map_type")
    map_object = create_base_map([lat, lon], zoom=12)
    folium.Marker([lat, lon], tooltip="ALVO", popup="ALVO").add_to(map_object)
    visible_kinds = list(all_geometries) if map_type == "Todos" else [map_type]
    if map_type != "Todos" and map_type not in all_geometries:
        st.warning("Essa geometria está bloqueada pela regra de margem de segurança.")
    for kind in visible_kinds:
        if kind not in all_geometries:
            continue
        for segment in all_geometries[kind]["segments"]:
            folium.PolyLine(
                [segment["start_coord"], segment["end_coord"]],
                color=SEGMENT_COLORS[segment["style"]],
                weight=4,
                tooltip=f"{kind}: {segment['name']} — {segment['distance_m']:.0f} m / {segment['azimuth']:.0f}°",
            ).add_to(map_object)
    if landing_direction is not None:
        landing_end = destination(lat, lon, 500, landing_direction)
        folium.PolyLine(
            [(lat, lon), landing_end],
            color=SEGMENT_COLORS["pouso"],
            weight=4,
            tooltip=f"Eixo de pouso — {landing_direction:.0f}° / {landing_speed:.1f} kt",
        ).add_to(map_object)
    st_folium(map_object, width=None, height=500, key="mapa_dkva_novo", returned_objects=[])
    render_map_legend()
    st.caption("Cores: velame vermelho · queda livre branca · arrasto azul · dispersão amarela · margem preta · eixo de pouso verde.")

    st.markdown("#### Exportar KMZ por tipo de lançamento")
    direction_context = {
        "va_direction_true": va_direction,
        "va_direction_magnetic": va_direction_magnetic,
        "ql_direction_true": ql_direction,
        "ql_direction_magnetic": ql_direction_magnetic,
        "landing_direction_true": landing_direction,
        "landing_direction_magnetic": landing_direction_magnetic,
        "navigation_magnetic": navigation_magnetic,
    }
    if all(kind in all_geometries for kind in LAUNCH_TYPES):
        combined_folders = []
        for kind in LAUNCH_TYPES:
            folder_name = _launch_folder_name(kind, entry_headings)
            placemarks = _placemarks_for_geometry(
                kind,
                lat,
                lon,
                all_geometries[kind]["segments"],
                gdh,
                point_records_by_type[kind],
                direction_context,
                landing_direction,
                landing_speed,
            )
            combined_folders.append({
                "name": folder_name,
                "placemarks": placemarks,
            })
        combined_kmz = export_kmz_folders(
            "Todos os lançamentos",
            combined_folders,
        )
        st.download_button(
            "Baixar KMZ — todos os lançamentos",
            data=combined_kmz,
            file_name="Lancamentos_Nariz_Cauda_Boca_do_Cone.kmz",
            mime="application/vnd.google-earth.kmz",
            key="download_kmz_all_launches",
        )
    else:
        st.info(
            "O KMZ combinado depende das três geometrias. Boca do Cone permanece "
            "bloqueado até que a margem de segurança esteja definida."
        )
    st.caption("A reta do 1' fora ao PS usa a cor magenta no KMZ.")
    kmz_columns = st.columns(3)
    for column, kind in zip(kmz_columns, LAUNCH_TYPES):
        if kind not in all_geometries:
            column.button(
                f"KMZ — {kind} bloqueado",
                disabled=True,
                key=f"download_kmz_{kind}_blocked",
            )
            continue
        kmz_data = _kmz_for_geometry(
            kind,
            lat,
            lon,
            all_geometries[kind]["segments"],
            gdh,
            point_records_by_type[kind],
            direction_context,
            _launch_folder_name(kind, entry_headings),
            landing_direction,
            landing_speed,
        )
        column.download_button(
            f"Baixar KMZ — {kind}",
            data=kmz_data,
            file_name=f"Lancamento_{kind.replace(' ', '_')}.kmz",
            mime="application/vnd.google-earth.kmz",
            key=f"download_kmz_{kind}",
        )
    _render_departure_field(create_base_map, location_search, terrain_lookup)


def _render_departure_field(create_base_map, location_search, terrain_lookup):
    st.divider()
    st.markdown("### Aeródromo de partida e ajuste altimétrico")
    saved_aerodromes = {
        "Personalizado / Outro": None,
        "Aeródromo de Goiânia": {"lat": -16.630929, "lon": -49.217527},
        "Skydive Cerrado": {"lat": -16.362042, "lon": -48.928371},
    }
    selected = st.selectbox(
        "Aeródromo conhecido",
        list(saved_aerodromes),
        key="dkva_known_airfield",
    )
    if selected != "Personalizado / Outro" and st.session_state.get("dkva_last_airfield") != selected:
        coordinates = saved_aerodromes[selected]
        st.session_state.lat_aerodromo_partida = coordinates["lat"]
        st.session_state.lon_aerodromo_partida = coordinates["lon"]
        st.session_state.dkva_last_airfield = selected
        st.session_state.mapa_aerodromo_rev = int(
            st.session_state.get("mapa_aerodromo_rev", 0)
        ) + 1
        st.rerun()
    if selected == "Personalizado / Outro":
        st.session_state.dkva_last_airfield = selected

    with st.form("dkva_airfield_search"):
        query = st.text_input("Buscar aeródromo/localidade de partida", key="dkva_airfield_query")
        search_clicked = st.form_submit_button("Buscar local do aeródromo")
    if search_clicked and query.strip():
        result = location_search(query)
        if result:
            st.session_state.lat_aerodromo_partida = float(result["lat"])
            st.session_state.lon_aerodromo_partida = float(result["lon"])
            st.session_state.dkva_last_airfield = "Personalizado / Outro"
            st.session_state.mapa_aerodromo_rev = int(
                st.session_state.get("mapa_aerodromo_rev", 0)
            ) + 1
            st.rerun()
        else:
            st.error("Aeródromo/localidade não encontrado.")

    revision = int(st.session_state.get("mapa_aerodromo_rev", 0))
    default_lat = float(st.session_state.get("lat_aerodromo_partida", st.session_state.get("lat", 0.0)))
    default_lon = float(st.session_state.get("lon_aerodromo_partida", st.session_state.get("lon", 0.0)))
    a1, a2 = st.columns(2)
    with a1:
        airfield_lat = st.number_input(
            "Latitude do aeródromo",
            value=default_lat,
            step=0.0001,
            format="%.6f",
            key=f"dkva_airfield_lat_{revision}",
        )
    with a2:
        airfield_lon = st.number_input(
            "Longitude do aeródromo",
            value=default_lon,
            step=0.0001,
            format="%.6f",
            key=f"dkva_airfield_lon_{revision}",
        )
    st.session_state.lat_aerodromo_partida = airfield_lat
    st.session_state.lon_aerodromo_partida = airfield_lon
    airfield_map = create_base_map([airfield_lat, airfield_lon], zoom=12)
    folium.Marker(
        [airfield_lat, airfield_lon],
        tooltip="Aeródromo de partida",
        icon=folium.Icon(color="blue", icon="flag"),
    ).add_to(airfield_map)
    map_result = st_folium(
        airfield_map,
        width=None,
        height=360,
        key=f"dkva_airfield_map_{revision}",
        returned_objects=["last_clicked"],
    )
    if map_result and map_result.get("last_clicked"):
        clicked = map_result["last_clicked"]
        new_coordinates = [round(float(clicked["lat"]), 7), round(float(clicked["lng"]), 7)]
        if st.session_state.get("dkva_airfield_last_click") != new_coordinates:
            st.session_state.dkva_airfield_last_click = new_coordinates
            st.session_state.lat_aerodromo_partida, st.session_state.lon_aerodromo_partida = new_coordinates
            st.session_state.mapa_aerodromo_rev = revision + 1
            st.rerun()

    if st.button("Calcular diferença altimétrica", key="dkva_airfield_altitude"):
        altitude, _ = terrain_lookup(airfield_lat, airfield_lon)
        st.session_state.altitude_aerodromo_partida_ft = altitude
        if altitude is None:
            st.session_state.altimetro_aerodromo_alvo_ft = None
            st.error("Não foi possível consultar a altitude do aeródromo.")
        else:
            target_altitude = float(st.session_state.get("altitude_ft", 0.0))
            st.session_state.altimetro_aerodromo_alvo_ft = altitude - target_altitude
    r1, r2 = st.columns(2)
    altitude_airfield = st.session_state.get("altitude_aerodromo_partida_ft")
    difference = st.session_state.get("altimetro_aerodromo_alvo_ft")
    r1.metric("Altitude do aeródromo (ft MSL)", "—" if altitude_airfield is None else f"{altitude_airfield:.0f}")
    r2.metric("Diferença altimétrica (ft)", "—" if difference is None else f"{difference:+.0f}")
    if difference is not None:
        st.caption("Diferença altimétrica = altitude do aeródromo de partida − altitude do alvo.")


def _member_minimum(member, jump_situation):
    category = member.get("categoria", "")
    parachute = str(member.get("velame", "")).upper()
    return minimum_command_height(
        category,
        tandem=bool(member.get("tandem", False)),
        operational=jump_situation == "Operacional",
        armed_equipped=jump_situation == "Operacional armado e equipado",
        canopy_operational=parachute == "OPERACIONAL VP 300",
        training_bda=jump_situation == "Desportivo — adestramento Bda Inf Pqdt",
        csl_team="equipe sl" in category.lower() or "instrução csl" in category.lower(),
    )


def _rationale(member, launch_type, previous=None):
    if bool(member.get("tandem")):
        return "TANDEM: último da equipe e destinado à última passagem."
    work = member.get("trabalho_ql", "—")
    canopy = member.get("velame", "—")
    weight = float(member.get("peso_kg", 0) or 0)
    if previous is not None and previous.get("trabalho_ql") == work and previous.get("velame") == canopy:
        return f"Desempate por peso ({weight:g} kg) no mesmo trabalho e velame."
    if launch_type == "Nariz":
        return f"Prioridade próxima ao alvo: trabalho {work}; velame {canopy}."
    if launch_type == "Cauda":
        return f"Ordem inversa ao afundamento: trabalho {work}; velame {canopy}."
    return f"Posição central por trabalho {work} e desempenho do velame {canopy}."


def render_teams():
    st.subheader("DIVISÃO DAS EQUIPES")
    st.warning("A ordenação é uma sugestão para revisão do MSL; confirme os critérios, mínimos e restrições da ZL.")
    with st.expander("Tabela técnica única de velames — DKVA e Divisão das Equipes"):
        _render_canopy_catalog_editor()
    st.caption(
        "OPERACIONAL VP 300 mantém o mínimo de 4.000 ft já configurado para velame operacional; "
        "confirme a regra com a doutrina vigente."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        launch_type = st.selectbox("Tipo de lançamento", LAUNCH_TYPES, key="equipes_tipo_lancamento")
    with c2:
        jump_situation = st.selectbox(
            "Tipo de salto",
            [
                "Desportivo — adestramento Bda Inf Pqdt",
                "Operacional",
                "Operacional armado e equipado",
            ],
            key="equipes_situacao",
        )
    with c3:
        exit_height = st.number_input(
            "Altura de saída (ft AGL)",
            min_value=0,
            value=int(st.session_state.get("altura_saida_ft", 10300)),
            step=100,
            key="equipes_altura_saida",
        )

    st.markdown("#### Saltadores (adicione linhas na tabela)")
    st.caption("O identificador do bloco é usado para não agrupar no mesmo nível mais de uma saída do mesmo bloco.")
    categories = ["AI", "A", "B", "C", "D", "Estagiário ESL/EMSL/Readaptação", "Equipe SL da Bda Inf Pqdt / instrução CSL"]
    initial = pd.DataFrame(columns=[
        "identificacao", "categoria", "trabalho_ql", "velame", "peso_kg", "tandem", "bloco",
    ])
    members_df = st.data_editor(
        initial,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="equipes_membros",
        column_config={
            "identificacao": st.column_config.TextColumn("Nome / identificação", required=True),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=categories, required=True),
            "trabalho_ql": st.column_config.SelectboxColumn("Trabalho em QL", options=WORK_SCALE, required=True),
            "velame": st.column_config.SelectboxColumn("Velame", options=CANOPY_SCALE, required=True),
            "peso_kg": st.column_config.NumberColumn("Peso (kg)", min_value=1.0, step=1.0, required=True),
            "tandem": st.column_config.CheckboxColumn("Tandem", default=False),
            "bloco": st.column_config.TextColumn("Bloco"),
        },
    )
    input_members = members_df.astype(object).where(pd.notna(members_df), None).to_dict("records")
    input_members = [
        member for member in input_members
        if str(member.get("identificacao") or "").strip()
    ]
    identity_counts = {}
    for member in input_members:
        identity = str(member["identificacao"]).strip()
        occurrence = identity_counts.get(identity, 0)
        identity_counts[identity] = occurrence + 1
        member["_member_key"] = (identity, occurrence)
    max_passage_text = st.text_input(
        "Máximo de saltadores por passagem (informado pelo MSL)",
        key="equipes_max_passagem_text",
        placeholder="Obrigatório para atribuir passagens e alturas",
    )
    base_command = st.number_input(
        "Altura-base de comandamento (ft AGL) [A CONFIRMAR]",
        min_value=0,
        value=5500,
        step=500,
        key="equipes_altura_base",
        help="Premissa editável; a altura final nunca será menor que o mínimo individual.",
    )

    st.markdown("#### Orientações de execução")
    st.info(
        "Intervalo orientativo entre saídas: 3–5 s. Track perpendicular ao eixo da aeronave; "
        "padronize a direção quando houver saltadores com o mesmo trabalho. "
        "Até 6 podem usar a mesma altura apenas em blocos diferentes. "
        "Verifique as restrições da ZL e o máximo por passagem informado pelo MSL."
    )
    if launch_type == "Cauda":
        st.warning("Lançamento de Cauda: equipe com mais de 16 saltadores não é aconselhável.")
    if not input_members:
        st.info("Adicione os saltadores na tabela para calcular a ordem.")
        return

    missing = [
        member["identificacao"]
        for member in input_members
        if not member.get("categoria")
        or not member.get("trabalho_ql")
        or not member.get("velame")
        or member.get("peso_kg") is None
    ]
    if missing:
        st.error("Complete categoria, trabalho, velame e peso para: " + ", ".join(missing))
        return

    ordered = sort_team(input_members, launch_type)
    for index, member in enumerate(ordered):
        member["ordem"] = index + 1
        member["_minimum"] = max(
            CATEGORY_MINIMUMS.get(member["categoria"], 0),
            _member_minimum(member, jump_situation),
        )

    try:
        max_per_passage = int(max_passage_text.strip())
        if max_per_passage < 1:
            raise ValueError
    except ValueError:
        max_per_passage = None
        st.error("Informe um máximo por passagem válido para atribuir alturas e passagens.")

    if max_per_passage is not None:
        highest_minimum = max(member["_minimum"] for member in ordered)
        if int(base_command) < highest_minimum:
            st.warning(
                f"A altura-base informada ({int(base_command)} ft) está abaixo do maior "
                f"mínimo aplicável ({highest_minimum} ft); as sugestões partem desse mínimo."
            )
        effective_base = max(int(base_command), highest_minimum)
        placed = assign_command_heights(
            ordered,
            effective_base,
            max_per_passage,
            launch_type,
        )
        for member in placed:
            if member["altura_comandamento_atribuida_ft"] < member["_minimum"]:
                member["altura_comandamento_atribuida_ft"] = member["_minimum"]
        output = []
        keys_by_order = {}
        minimums_by_order = {}
        blocks_by_order = {}
        for member in placed:
            idx = member["ordem"] - 1
            previous = ordered[idx - 1] if idx > 0 else None
            keys_by_order[member["ordem"]] = member["_member_key"]
            minimums_by_order[member["ordem"]] = member["_minimum"]
            blocks_by_order[member["ordem"]] = member.get("bloco", "")
            output.append({
                "Ordem": member["ordem"],
                "Passagem": member["passagem_atribuida"],
                "Bloco": member.get("bloco", ""),
                "Identificação": member["identificacao"],
                "Categoria": member["categoria"],
                "Trabalho QL": member["trabalho_ql"],
                "Velame": member["velame"],
                "Peso (kg)": member["peso_kg"],
                "Sugerido (ft AGL)": member["altura_comandamento_atribuida_ft"],
                "Definido pelo MSL (ft AGL)": st.session_state.get(
                    "equipes_commandamento_edits", {}
                ).get(
                    member["_member_key"],
                    member["altura_comandamento_atribuida_ft"],
                ),
                "Mínimo aplicável (ft)": member["_minimum"],
                "Justificativa": _rationale(member, launch_type, previous),
            })
        result_df = pd.DataFrame(output).sort_values(["Passagem", "Ordem"])
        if st.button(
            "Voltar à sugestão automática",
            key="equipes_reset_commandamento",
        ):
            st.session_state.equipes_commandamento_edits = {}
            if "equipes_commandamento_editor" in st.session_state:
                del st.session_state["equipes_commandamento_editor"]
            st.rerun()

        st.markdown("#### Ordem de saída e comandamento")
        edited_df = st.data_editor(
            result_df,
            hide_index=True,
            use_container_width=True,
            key="equipes_commandamento_editor",
            disabled=[
                "Ordem",
                "Passagem",
                "Bloco",
                "Identificação",
                "Categoria",
                "Trabalho QL",
                "Velame",
                "Peso (kg)",
                "Sugerido (ft AGL)",
                "Mínimo aplicável (ft)",
                "Justificativa",
            ],
            column_config={
                "Definido pelo MSL (ft AGL)": st.column_config.NumberColumn(
                    min_value=0,
                    step=100,
                    required=True,
                ),
            },
        )
        command_edits = dict(st.session_state.get("equipes_commandamento_edits", {}))
        validation_members = []
        for row in edited_df.to_dict("records"):
            order = int(row["Ordem"])
            member_key = keys_by_order[order]
            command_edits[member_key] = row["Definido pelo MSL (ft AGL)"]
            validation_members.append({
                "identificacao": row["Identificação"],
                "altura_comandamento_ft": row["Definido pelo MSL (ft AGL)"],
                "minimum_ft": minimums_by_order[order],
                "bloco": blocks_by_order[order],
            })
        st.session_state.equipes_commandamento_edits = command_edits
        validation_errors = validate_command_height_edits(
            validation_members,
            exit_height,
        )
        if validation_errors:
            with st.expander("Alertas de validação do comandamento", expanded=True):
                for error in validation_errors:
                    st.warning(error)
        else:
            st.success(
                "Sem alertas nas regras configuradas; confirme também a doutrina e as restrições da ZL."
            )

        export_df = edited_df.rename(columns={
            "Definido pelo MSL (ft AGL)": "Altura comandamento (ft AGL)",
        })
        st.session_state.equipes_resultado = export_df.to_dict("records")
        csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Divisão")
        d1, d2 = st.columns(2)
        d1.download_button(
            "Exportar CSV",
            data=csv_bytes,
            file_name="divisao_equipes.csv",
            mime="text/csv",
            key="download_equipes_csv",
        )
        d2.download_button(
            "Exportar XLSX",
            data=excel_buffer.getvalue(),
            file_name="divisao_equipes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_equipes_xlsx",
        )
        st.caption("Para impressão, use a função Imprimir do navegador após conferir a tabela.")
    else:
        st.markdown("#### Ordem preliminar (alturas pendentes do máximo por passagem)")
        st.dataframe(pd.DataFrame([
            {
                "Ordem": index + 1,
                "Identificação": member["identificacao"],
                "Categoria": member["categoria"],
                "Trabalho QL": member["trabalho_ql"],
                "Velame": member["velame"],
                "Peso (kg)": member["peso_kg"],
                "Mínimo aplicável (ft)": member["_minimum"],
            }
            for index, member in enumerate(ordered)
        ]), hide_index=True, use_container_width=True)


def _set_default_state(key, value):
    if key not in st.session_state:
        st.session_state[key] = value


def render_daa(terrain_lookup):
    st.subheader("AJUSTE DE DAA")
    st.warning("Confirme o equipamento, a pressão e os resultados com a calculadora/dados oficiais.")
    dep_default = st.session_state.get("altitude_aerodromo_partida_ft")
    pouso_default = st.session_state.get("altitude_ft")
    ps_default = st.session_state.get("altitude_consulta_ft")
    qfe_default = st.session_state.get("qfe_consulta_hpa")
    if st.session_state.get("ps_lat") is None or st.session_state.get("ps_lon") is None:
        st.caption("O PS será preenchido automaticamente quando um PS for calculado na aba DKVA.")
    refresh = st.button("Consultar novamente altitude/QFE do PS", key="daa_refresh_ps")
    if refresh:
        ps_lat = st.session_state.get("ps_lat")
        ps_lon = st.session_state.get("ps_lon")
        if ps_lat is None or ps_lon is None:
            st.error("Calcule ou selecione um PS na aba DKVA antes da consulta.")
        else:
            with st.spinner("Consultando altitude e pressão do PS..."):
                new_altitude, new_qfe = terrain_lookup(float(ps_lat), float(ps_lon))
            if new_altitude is not None:
                st.session_state.altitude_consulta_ft = float(new_altitude)
                ps_default = float(new_altitude)
                st.session_state.daa_ps_ft = float(new_altitude)
            if new_qfe is not None:
                st.session_state.qfe_consulta_hpa = float(new_qfe)
                qfe_default = float(new_qfe)
                st.session_state.daa_qfe_hpa = float(new_qfe)
            if new_altitude is None and new_qfe is None:
                st.error("A consulta não retornou altitude nem QFE. Informe valores manualmente.")

    for key, value in (
        ("daa_dep_ft", dep_default),
        ("daa_pouso_ft", pouso_default),
        ("daa_ps_ft", ps_default),
        ("daa_qfe_hpa", qfe_default),
    ):
        _set_default_state(key, None if value is None else float(value))

    c1, c2, c3 = st.columns(3)
    with c1:
        dep_ft = st.number_input(
            "Altitude do aeródromo de decolagem — Dep (ft AMSL)",
            step=10.0,
            key="daa_dep_ft",
        )
        source_dep = "app (aeródromo)" if dep_default is not None else "digitado"
    with c2:
        pouso_ft = st.number_input(
            "Altitude da área de pouso (ft AMSL)",
            step=10.0,
            key="daa_pouso_ft",
        )
        source_pouso = "app (alvo)" if pouso_default is not None else "digitado"
    with c3:
        ps_ft = st.number_input(
            "Altitude do ponto de saída — PS (ft AMSL)",
            step=10.0,
            key="daa_ps_ft",
        )
        source_ps = "consulta do app" if ps_default is not None else "digitado"
    st.caption(f"Fontes preenchidas: Dep — {source_dep}; Pouso — {source_pouso}; PS — {source_ps}.")

    equipment = st.selectbox(
        "Equipamento",
        ["Cypres", "Vigil", "Cypres Militar", "Vigil Militar"],
        key="daa_equipment",
    )
    qfe = st.number_input(
        "QFE do PS (hPa), opcional",
        min_value=0.0,
        step=0.1,
        key="daa_qfe_hpa",
        help="Se vazio, será usada a estimativa ISA e exibido um aviso.",
    )
    effective_qfe = qfe
    if effective_qfe is None or effective_qfe <= 0:
        if ps_ft is not None:
            effective_qfe = float(isa_pressure_hpa(ps_ft))
            st.warning("Estimativa ISA — confirmar com a calculadora Cypres ou dado de pressão real.")
        else:
            effective_qfe = None
            st.warning("Informe a altitude do PS para estimar QFE pela atmosfera ISA.")

    altimeter = None
    if dep_ft is not None and pouso_ft is not None:
        altimeter = altimeter_adjustment(dep_ft, pouso_ft)
        st.metric(
            "Ajuste de altímetro (Dep − Pouso)",
            f"{altimeter:+.0f} ft · {'sentido horário' if altimeter >= 0 else 'sentido anti-horário'}",
        )
    else:
        st.info("Informe as altitudes de Dep e Pouso para calcular o ajuste do altímetro.")

    with st.expander("Passo a passo"):
        if effective_qfe is not None and ps_ft is not None:
            st.write(f"QNH estimado/calculado = QFE + Alt PS / 27 = {effective_qfe:.1f} + {ps_ft:.0f} / 27 = {effective_qfe + ps_ft / 27:.1f} hPa.")
        if altimeter is not None:
            st.write(f"Ajuste de altímetro = Dep − Pouso = {dep_ft:.0f} − {pouso_ft:.0f} = {altimeter:+.0f} ft.")

    if equipment == "Cypres":
        if ps_ft is not None and dep_ft is not None:
            result = cypres_adjustment(ps_ft, dep_ft)
            st.metric("Ajuste Cypres", f"{result:+.0f} ft")
            st.caption(f"Δ = PS − Dep = {ps_ft:.0f} − {dep_ft:.0f} = {ps_ft - dep_ft:+.0f} ft; teto em passos de 30 ft.")
        else:
            st.info("Informe as altitudes de PS e Dep para calcular o ajuste Cypres.")
    elif equipment == "Vigil":
        if ps_ft is not None and dep_ft is not None:
            result = vigil_adjustment(ps_ft, dep_ft)
            st.metric("Ajuste Vigil", f"{result:+.0f} ft")
            st.caption(f"Δ = PS − Dep = {ps_ft:.0f} − {dep_ft:.0f} = {ps_ft - dep_ft:+.0f} ft; teto em passos de 150 ft.")
        else:
            st.info("Informe as altitudes de PS e Dep para calcular o ajuste Vigil.")
    elif equipment == "Cypres Militar":
        if effective_qfe is not None:
            st.metric("DAA Cypres Militar — QFE PS", f"{effective_qfe:.1f} hPa")
            st.caption("Sem arredondamento pelo app: usar o valor de QFE confirmado pela calculadora Cypres.")
        else:
            st.info("Informe QFE ou altitude PS para obter o dado de referência.")
    else:
        if effective_qfe is not None and ps_ft is not None:
            qnh_value = effective_qfe + ps_ft / 27
            qnh_even = round_qnh_to_even(qnh_value)
            rounded_altitude = round_vigil_military_ps_altitude(ps_ft)
            st.metric("Vigil Militar — QNH PS", f"{qnh_even} hPa")
            st.metric("Vigil Militar — Alt PS", f"+{rounded_altitude:.0f} ft")
            st.caption(f"QNH intermediário {qnh_value:.1f} hPa → par mais próximo; Alt PS arredondada para cima em passos de 300 ft.")
        else:
            st.info("Informe QFE ou altitude PS para calcular QNH e Alt PS.")
