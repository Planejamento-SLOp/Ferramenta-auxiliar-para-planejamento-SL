import math
import unicodedata

from calc_dkva import CANOPY_CATALOG


WORK_SCALE = [
    "DIVE", "SIT FLY", "DORSO", "LOOP", "½ SÉRIE", "NO CONTACT",
    "CURVA-CURVA", "VOO LATERAL", "QE", "SLOP", "FQL",
]

CANOPY_SCALE = [item["team_label"] for item in CANOPY_CATALOG]

CATEGORY_MINIMUMS = {
    "AI": 5500,
    "A": 4500,
    "B": 4000,
    "C": 3500,
    "D": 3000,
    "Estagiário ESL/EMSL/Readaptação": 5500,
    "Equipe SL da Bda Inf Pqdt / instrução CSL": 2500,
}


def _normalized(value):
    value = unicodedata.normalize("NFKD", str(value))
    return "".join(character for character in value if not unicodedata.combining(character)).upper().strip()


def _rank(value, scale):
    normalized = _normalized(value).replace("1/2", "½")
    return next(
        (index for index, option in enumerate(scale) if _normalized(option).replace("1/2", "½") == normalized),
        len(scale),
    )


def minimum_command_height(category, tandem=False, operational=False, armed_equipped=False,
                          canopy_operational=False, training_bda=False, csl_team=False):
    minimum = next(
        (height for name, height in CATEGORY_MINIMUMS.items() if _normalized(name) == _normalized(category)),
        0,
    )
    minimum = max(minimum, 4500 if armed_equipped or operational else 0)
    minimum = max(minimum, 4000 if canopy_operational else 0)
    minimum = max(minimum, 3000 if training_bda else 0)
    minimum = max(minimum, 2500 if csl_team else 0)
    if tandem:
        minimum = max(minimum, 5500)
    return minimum


def sort_team(members, launch_type):
    def sink_priority(member):
        canopy_rank = _rank(member.get("velame", ""), CANOPY_SCALE)
        work_rank = _rank(member.get("trabalho_ql", ""), WORK_SCALE)
        weight = float(member.get("peso_kg", 0) or 0)
        return work_rank, canopy_rank, -weight

    tandems = [member for member in members if bool(member.get("tandem"))]
    others = [member for member in members if not bool(member.get("tandem"))]
    if launch_type == "Nariz":
        ordered = sorted(others, key=sink_priority)
    elif launch_type == "Cauda":
        ordered = sorted(others, key=sink_priority, reverse=True)
    elif launch_type == "Boca do Cone":
        center_order = sorted(others, key=sink_priority)
        positions = [None] * len(center_order)
        center = len(center_order) // 2
        indices = [center]
        for offset in range(1, len(center_order) + 1):
            if center - offset >= 0:
                indices.append(center - offset)
            if center + offset < len(center_order):
                indices.append(center + offset)
        for member, position in zip(center_order, indices):
            positions[position] = member
        ordered = positions
    else:
        raise ValueError("Tipo de lancamento desconhecido")
    return ordered + tandems


def assign_command_heights(ordered, base_ft, max_per_passage, launch_type):
    if max_per_passage < 1:
        raise ValueError("Informe o maximo de saltadores por passagem")
    placements = []
    passages = [ordered[index:index + max_per_passage] for index in range(0, len(ordered), max_per_passage)]
    for passage_index, passage in enumerate(passages, 1):
        if launch_type == "Boca do Cone":
            center = (len(passage) - 1) / 2
            blocks_by_altitude = {}
            for position, member in enumerate(passage):
                height_level = int(abs(position - center)) * 500
                block = str(member.get("bloco", position + 1))
                altitude = base_ft + height_level
                while block in blocks_by_altitude.setdefault(altitude, set()):
                    altitude += 500
                blocks_by_altitude.setdefault(altitude, set()).add(block)
                placements.append({
                    **member,
                    "passagem_atribuida": passage_index,
                    "altura_comandamento_atribuida_ft": altitude,
                })
            continue

        altitude_groups = []
        current_group = []
        blocks_in_group = set()
        for position, member in enumerate(passage, 1):
            block = str(member.get("bloco", position))
            if current_group and (len(current_group) >= 6 or block in blocks_in_group):
                altitude_groups.append(current_group)
                current_group = []
                blocks_in_group = set()
            current_group.append(member)
            blocks_in_group.add(block)
        if current_group:
            altitude_groups.append(current_group)

        group_count = len(altitude_groups)
        for group_index, group in enumerate(altitude_groups):
            if launch_type == "Nariz":
                altitude = base_ft + group_index * 500
            elif launch_type == "Cauda":
                altitude = base_ft + (group_count - group_index - 1) * 500
            for member in group:
                placements.append({
                    **member,
                    "passagem_atribuida": passage_index,
                    "altura_comandamento_atribuida_ft": altitude,
                })
    return placements


def validate_command_height_edits(members, exit_height_ft):
    errors = []
    heights = {}
    exit_height = float(exit_height_ft)
    if not math.isfinite(exit_height):
        raise ValueError("Altura de saída inválida")

    for member in members:
        name = str(member.get("identificacao") or "Saltador")
        try:
            height = float(member["altura_comandamento_ft"])
            minimum = float(member.get("minimum_ft", 0))
        except (KeyError, TypeError, ValueError):
            errors.append(f"{name}: informe um comandamento numérico.")
            continue
        if not math.isfinite(height) or not math.isfinite(minimum):
            errors.append(f"{name}: comandamento ou mínimo não numérico.")
            continue
        heights.setdefault(height, []).append(member)
        if height < minimum:
            errors.append(
                f"{name}: {height:g} ft abaixo do mínimo aplicável de {minimum:g} ft."
            )
        if height >= exit_height:
            errors.append(
                f"{name}: comandamento deve ficar abaixo da altura de saída ({exit_height:g} ft)."
            )

    distinct_heights = sorted(heights)
    for lower, upper in zip(distinct_heights, distinct_heights[1:]):
        if upper - lower < 500:
            errors.append(
                f"Intervalo menor que 500 ft entre os grupos de {lower:g} ft e {upper:g} ft."
            )

    for height, group in heights.items():
        if len(group) > 6:
            errors.append(f"Mais de 6 saltadores definidos a {height:g} ft.")
        blocks = [str(member.get("bloco") or "").strip() for member in group]
        if len(blocks) != len(set(blocks)):
            errors.append(
                f"Blocos repetidos a {height:g} ft; no máximo 6, todos de blocos diferentes."
            )
    return errors
