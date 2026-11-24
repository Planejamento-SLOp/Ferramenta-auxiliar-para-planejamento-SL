from math import ceil, floor, radians, sin, cos, atan2, degrees, isfinite
from geographiclib.geodesic import Geodesic


CANOPY_CATALOG = [
    {
        "model": "Scorpion 190",
        "team_label": "SCORPION",
        "size_ft2": 190,
        "speed_kt": 30.73,
        "glide": 3.53,
        "source": (
            "Tamanho 190 ft² fornecido pelo usuário (2026-11-22); "
            "V/G: Planilha PS ATLZ.xlsx, aba Parachutes"
        ),
        "source_url": "",
        "consulted_on": "2026-11-22",
    },
    {
        "model": "Silhouette",
        "team_label": "SILHOUETTE",
        "size_ft2": 210,
        "speed_kt": None,
        "glide": None,
        "source": (
            "Tamanho 210 ft² fornecido pelo usuário (2026-11-22); "
            "V/G: [A CONFIRMAR] — fonte técnica pública não localizada"
        ),
        "source_url": "",
        "consulted_on": "2026-11-22",
    },
    {
        "model": "Merlin 260",
        "team_label": "MERLIN",
        "size_ft2": 260,
        "speed_kt": 28.58,
        "glide": 3.95,
        "source": (
            "Tamanho 260 ft² fornecido pelo usuário (2026-11-22); "
            "V/G: Planilha PS ATLZ.xlsx, aba Parachutes"
        ),
        "source_url": "",
        "consulted_on": "2026-11-22",
    },
    {
        "model": "Navigator",
        "team_label": "NAVIGATOR",
        "size_ft2": 260,
        "speed_kt": None,
        "glide": None,
        "source": (
            "Tamanho 260 ft² fornecido pelo usuário (2026-11-22); "
            "V/G: [A CONFIRMAR] — fonte técnica pública não localizada"
        ),
        "source_url": "",
        "consulted_on": "2026-11-22",
    },
    {
        "model": "VP 300",
        "team_label": "OPERACIONAL VP 300",
        "size_ft2": 372,
        "speed_kt": 23.69,
        "glide": 3.5,
        "source": (
            "Imagem 3 fornecida pelo usuário: 372 ft² e G=3.5; "
            "Planilha PS ATLZ.xlsx, aba Parachutes: V=23.69 kt "
            "(G=3.2 substituído por G=3.5 conforme orientação do usuário)"
        ),
        "source_url": "",
        "consulted_on": "2026-11-22",
    },
    {
        "model": "Tandem",
        "team_label": "TANDEM",
        "size_ft2": 372,
        "speed_kt": None,
        "glide": None,
        "source": (
            "Tamanho 372 ft² fornecido pelo usuário (2026-11-22); "
            "V/G: Strong Parachutes DHT; múltiplos velames principais, sem V/G publicado"
        ),
        "source_url": "https://strongparachutes.com/Tandem/Products/dual-hawk-tandem-dht",
        "consulted_on": "2026-11-22",
    },
]

PARACHUTES = {
    item["model"]: {"speed_kt": item["speed_kt"], "glide": item["glide"]}
    for item in CANOPY_CATALOG
    if item["speed_kt"] is not None and item["glide"] is not None
}

AIRCRAFT = {
    "KC-390 (C-390)": {"speed_ms": 70.0, "drag_m": 300.0},
    "C-105": {"speed_ms": 70.0, "drag_m": 300.0},
    "C-95": {"speed_ms": 60.0, "drag_m": 300.0},
    "Beech 99": {"speed_ms": 60.0, "drag_m": 300.0},
    "Grand Caravan": {"speed_ms": 40.0, "drag_m": 150.0},
    "Caravan": {"speed_ms": 40.0, "drag_m": 150.0},
    "Helicopteros (HP)": {"speed_ms": 40.0, "drag_m": 150.0},
}


def normalize_azimuth(azimuth):
    return float(azimuth) % 360.0


def opposite_azimuth(azimuth):
    return normalize_azimuth(azimuth + 180.0)


def true_to_magnetic_azimuth(true_azimuth, declination):
    return normalize_azimuth(float(true_azimuth) - float(declination))


def magnetic_to_true_azimuth(magnetic_azimuth, declination):
    return normalize_azimuth(float(magnetic_azimuth) + float(declination))


def navigation_axis_magnetic(canopy_direction_true, declination):
    return true_to_magnetic_azimuth(
        opposite_azimuth(canopy_direction_true),
        declination,
    )


def round_heading_to_five(azimuth):
    return int(round(float(azimuth) / 5.0) * 5) % 360


def launch_entry_headings(canopy_direction_true, declination):
    nose = round_heading_to_five(
        true_to_magnetic_azimuth(canopy_direction_true, declination)
    )
    return {
        "Nariz": [nose],
        "Cauda": [opposite_azimuth(nose)],
        "Boca do Cone": [
            normalize_azimuth(nose + 90),
            normalize_azimuth(nose - 90),
        ],
    }


def arithmetic_mean(values):
    values = [float(value) for value in values]
    if not values:
        raise ValueError("Lista vazia para media aritmetica")
    return round(sum(values) / len(values))


def circular_mean(directions):
    if not directions:
        raise ValueError("Lista vazia para media circular")
    sine = sum(sin(radians(float(value))) for value in directions)
    cosine = sum(cos(radians(float(value))) for value in directions)
    result = degrees(atan2(sine, cosine)) % 360
    return int(round(result)) % 360


def mean_wind(directions, speeds):
    if len(directions) != len(speeds) or not directions:
        raise ValueError("Direcoes e intensidades devem ter o mesmo tamanho")
    arithmetic_direction = arithmetic_mean(directions)
    circular_direction = circular_mean(directions)
    crosses_north = min(directions) < 20 and max(directions) > 340
    return {
        "speed_kt": sum(float(value) for value in speeds) / len(speeds),
        "arithmetic_direction": circular_direction if crosses_north else arithmetic_direction,
        "raw_arithmetic_direction": arithmetic_direction,
        "circular_direction": circular_direction,
        "crosses_north": crosses_north,
    }


def va_distance(opening_ft, minimum_ft, wind_kt, parachute_speed_kt, glide_ratio, margin_factor=0.75):
    """Return canopy drift in meters using the user's spreadsheet conversion."""
    if glide_ratio <= 0:
        raise ValueError("Razao de planeio deve ser maior que zero")
    if wind_kt >= parachute_speed_kt:
        raise ValueError("W >= Va -> sem progressao")
    delta_h_ft = opening_ft - minimum_ft
    if delta_h_ft < 0:
        raise ValueError("Altura de abertura menor que a altura minima sobre o alvo")
    vertical_speed_fps = parachute_speed_kt * 1.68781 / glide_ratio
    distance_m = (
        (delta_h_ft / vertical_speed_fps)
        * (parachute_speed_kt - wind_kt)
        * 1.68781
        * 0.3048
        * margin_factor
    )
    return round(distance_m)


def free_fall_distance(wind_kt, launch_ft, command_ft, k=3.0):
    if launch_ft < command_ft:
        raise ValueError("Altura de lancamento menor que a altura de comandamento")
    a_kft = (launch_ft - command_ft) / 1000.0
    return round(k * wind_kt * a_kft)


def dispersion_distance(blocks, interval_s, aircraft_speed_ms):
    return blocks * interval_s * aircraft_speed_ms


def safety_margin(distance_va_m):
    if distance_va_m < 1000:
        return 200
    if distance_va_m < 2000:
        return 400
    if distance_va_m < 3000:
        return 800
    if distance_va_m < 4000:
        return 1000
    raise ValueError("Velame >= 4000 m: margem de seguranca requer decisao do MSL")


def destination(lat, lon, distance_m, azimuth):
    result = Geodesic.WGS84.Direct(float(lat), float(lon), normalize_azimuth(azimuth), float(distance_m))
    return float(result["lat2"]), float(result["lon2"])


def azimuth_and_distance(start_lat, start_lon, end_lat, end_lon):
    result = Geodesic.WGS84.Inverse(
        float(start_lat),
        float(start_lon),
        float(end_lat),
        float(end_lon),
    )
    return normalize_azimuth(result["azi1"]), float(result["s12"])


def one_minute_out(ps_lat, ps_lon, aircraft_speed_ms, entry_heading_magnetic, declination):
    speed = float(aircraft_speed_ms)
    if not isfinite(speed) or speed <= 0:
        raise ValueError("Velocidade da aeronave deve ser maior que zero")
    entry_true = magnetic_to_true_azimuth(entry_heading_magnetic, declination)
    distance_m = speed * 60.0
    coordinate = destination(
        ps_lat,
        ps_lon,
        distance_m,
        opposite_azimuth(entry_true),
    )
    return {
        "distance_m": distance_m,
        "entry_heading_true": entry_true,
        "coordinate": coordinate,
    }


def coordinate_to_gms(latitude, longitude):
    def format_one(value, is_latitude):
        value = float(value)
        if not isfinite(value) or abs(value) > (90 if is_latitude else 180):
            raise ValueError("Coordenada fora dos limites geográficos")
        hemisphere = (
            ("N" if value >= 0 else "S")
            if is_latitude
            else ("E" if value >= 0 else "O")
        )
        absolute = abs(value)
        degrees_value = int(absolute)
        minutes_full = (absolute - degrees_value) * 60
        minutes_value = int(minutes_full)
        seconds = round((minutes_full - minutes_value) * 60, 2)
        if seconds >= 60:
            seconds = 0.0
            minutes_value += 1
        if minutes_value >= 60:
            minutes_value = 0
            degrees_value += 1
        width = 2 if is_latitude else 3
        return f"{degrees_value:0{width}d}°{minutes_value:02d}'{seconds:05.2f}\"{hemisphere}"

    return f"{format_one(latitude, True)} {format_one(longitude, False)}"


def vertical_speed_fps(speed_kt, glide_ratio):
    speed = float(speed_kt)
    glide = float(glide_ratio)
    if not isfinite(speed) or speed <= 0:
        raise ValueError("Velocidade do velame deve ser maior que zero")
    if not isfinite(glide) or glide <= 0:
        raise ValueError("Razão de planeio deve ser maior que zero")
    return speed * 1.68781 / glide


def vertical_speed_mps(speed_kt, glide_ratio):
    return vertical_speed_fps(speed_kt, glide_ratio) * 0.3048


def segment_table(start_lat, start_lon, azimuth, distance_m, name):
    end_lat, end_lon = destination(start_lat, start_lon, distance_m, azimuth)
    return {
        "name": name,
        "azimuth": normalize_azimuth(azimuth),
        "distance_m": float(distance_m),
        "start": (start_lat, start_lon),
        "end": (end_lat, end_lon),
    }


def va_sensitivity(opening_ft, minimum_ft, parachute_speed_kt, glide_ratio):
    """Return spreadsheet sensitivity distances for headwind/tailwind from 0 to 20 kt."""
    if glide_ratio <= 0:
        raise ValueError("Razao de planeio deve ser maior que zero")
    delta_h_ft = opening_ft - minimum_ft
    if delta_h_ft < 0:
        raise ValueError("Altura de abertura menor que a altura minima sobre o alvo")
    vertical_speed_fps = parachute_speed_kt * 1.68781 / glide_ratio
    result = []
    for wind_kt in range(21):
        scale = (delta_h_ft / vertical_speed_fps) * 1.68781 * 0.3048
        headwind = round(scale * (parachute_speed_kt - wind_kt))
        tailwind = round(scale * (parachute_speed_kt + wind_kt))
        result.append({
            "Vento (kt)": wind_kt,
            "VA_Nariz (m)": headwind,
            "VA_VentoCauda (m)": tailwind,
        })
    return result


def launch_segment_specs(launch_type, va_m, ql_m, va_az, ql_az, dispersion_m,
                         drag_m, safety_m=None):
    """Build ordered segment definitions with anchor references for one launch geometry."""
    va_az = normalize_azimuth(va_az)
    ql_az = normalize_azimuth(ql_az)
    opposite_va = opposite_azimuth(va_az)
    if launch_type == "Nariz":
        return [
            {"id": "va", "name": "VELAME ABERTO", "start": "target", "distance_m": va_m, "azimuth": va_az, "style": "velame"},
            {"id": "ql", "name": "QUEDA LIVRE", "start": "va", "distance_m": ql_m, "azimuth": ql_az, "style": "queda"},
            {"id": "dispersion", "name": "Dispersão", "start": "ql", "distance_m": dispersion_m, "azimuth": opposite_va, "style": "dispersao"},
            {"id": "drag", "name": "Arrasto", "start": "dispersion", "distance_m": drag_m, "azimuth": opposite_va, "style": "arrasto"},
            {"id": "limit", "name": "Limite", "start": "ql", "distance_m": drag_m, "azimuth": opposite_va, "style": "arrasto"},
        ]
    if launch_type == "Cauda":
        return [
            {"id": "va", "name": "VELAME ABERTO", "start": "target", "distance_m": va_m, "azimuth": va_az, "style": "velame"},
            {"id": "ql", "name": "QUEDA LIVRE", "start": "va", "distance_m": ql_m, "azimuth": ql_az, "style": "queda"},
            {"id": "drag", "name": "Arrasto", "start": "ql", "distance_m": drag_m, "azimuth": va_az, "style": "arrasto"},
            {"id": "last_ql", "name": "QUEDA LIVRE ÚLTIMO HOMEM", "start": "target", "distance_m": ql_m, "azimuth": ql_az, "style": "queda"},
            {"id": "last_drag", "name": "Arrasto limite cauda", "start": "last_ql", "distance_m": drag_m, "azimuth": va_az, "style": "arrasto"},
        ]
    if launch_type == "Boca do Cone":
        if safety_m is None:
            raise ValueError("Margem de seguranca nao configurada")
        azimuth_1 = normalize_azimuth(opposite_va + 90)
        azimuth_2 = normalize_azimuth(opposite_va - 90)
        return [
            {"id": "va", "name": "VELAME ABERTO", "start": "target", "distance_m": va_m, "azimuth": va_az, "style": "velame"},
            {"id": "ql", "name": "QUEDA LIVRE", "start": "va", "distance_m": ql_m, "azimuth": ql_az, "style": "queda"},
            {"id": "safety", "name": "Margem de segurança", "start": "ql", "distance_m": safety_m, "azimuth": opposite_va, "style": "margem"},
            {"id": "half_1", "name": "DISPERSÃO/2 1", "start": "safety", "distance_m": dispersion_m / 2, "azimuth": azimuth_1, "style": "dispersao"},
            {"id": "drag_1", "name": "Arrasto PS BC 1", "start": "half_1", "distance_m": drag_m, "azimuth": azimuth_1, "style": "arrasto"},
            {"id": "half_2", "name": "DISPERSÃO/2 2", "start": "safety", "distance_m": dispersion_m / 2, "azimuth": azimuth_2, "style": "dispersao"},
            {"id": "drag_2", "name": "Arrasto PS BC 2", "start": "half_2", "distance_m": drag_m, "azimuth": azimuth_2, "style": "arrasto"},
        ]
    raise ValueError("Tipo de lancamento desconhecido")


def calculate_launch_geometry(lat, lon, specs, overrides=None):
    """Calculate segment endpoints; overrides map segment IDs to distance/azimuth values."""
    overrides = overrides or {}
    anchors = {"target": (float(lat), float(lon))}
    segments = []
    for spec in specs:
        configured = overrides.get(spec["id"], {})
        distance_m = float(configured.get("distance_m", spec["distance_m"]))
        azimuth = normalize_azimuth(configured.get("azimuth", spec["azimuth"]))
        if distance_m < 0:
            raise ValueError("Comprimento de segmento nao pode ser negativo")
        start = anchors[spec["start"]]
        end = destination(start[0], start[1], distance_m, azimuth)
        anchors[spec["id"]] = end
        segments.append({
            **spec,
            "distance_m": distance_m,
            "azimuth": azimuth,
            "start_coord": start,
            "end_coord": end,
        })
    return segments, anchors
