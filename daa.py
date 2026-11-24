import math


def ceil_step(value, step):
    return math.ceil(value / step) * step


def cypres_adjustment(ps_ft, dep_ft):
    difference = ps_ft - dep_ft
    return ceil_step(difference, 30)


def vigil_adjustment(ps_ft, dep_ft):
    difference = ps_ft - dep_ft
    return ceil_step(difference, 150)


def altimeter_adjustment(dep_ft, pouso_ft):
    return dep_ft - pouso_ft


def isa_pressure_hpa(altitude_ft):
    altitude_m = altitude_ft * 0.3048
    pressure_pa = 101325 * (1 - 2.25577e-5 * altitude_m) ** 5.25588
    return math.floor(pressure_pa / 100)


def qnh_hpa(qfe_hpa, altitude_ps_ft):
    return math.floor(qfe_hpa + altitude_ps_ft / 27.0 + 0.5)


def round_qnh_to_even(qnh_hpa):
    if float(qnh_hpa).is_integer():
        value = int(qnh_hpa)
        if value % 2:
            return value + 1
    return 2 * math.floor(qnh_hpa / 2 + 0.5)


def round_vigil_military_ps_altitude(altitude_ft):
    return ceil_step(altitude_ft, 300)
