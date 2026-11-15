#!/usr/bin/env python3
"""Prepara los datos de vehículos para el modelo mensual de la zona de estudio."""

from __future__ import annotations

import argparse
import calendar
import csv
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


MUNICIPIOS_OBJETIVO = ("TUNJA", "DUITAMA", "SOGAMOSO")
TIPOS_PRINCIPALES = (
    "MOTOCICLETA",
    "AUTOMOVIL",
    "CAMIONETA",
    "CAMION",
    "TRACTOCAMION",
)


def texto_normalizado(valor: str | None) -> str:
    """Normaliza espacios, Unicode y mayúsculas sin eliminar acentos visibles."""
    texto = unicodedata.normalize("NFC", valor or "")
    return re.sub(r"\s+", " ", texto.strip()).upper()


def clave_ascii(valor: str | None) -> str:
    """Crea una clave tolerante a acentos para comparar nombres geográficos."""
    texto = texto_normalizado(valor)
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )


def entero_seguro(valor: str | None) -> int | None:
    texto = (valor or "").strip()
    return int(texto) if re.fullmatch(r"\d+", texto) else None


def mes_seguro(valor: str | None) -> tuple[int, int] | None:
    coincidencia = re.fullmatch(r"(0[1-9]|1[0-2])/(\d{4})", (valor or "").strip())
    if not coincidencia:
        return None
    mes, anio = map(int, coincidencia.groups())
    return anio, mes


def iterar_meses(inicio: date, fin: date):
    actual = inicio
    while actual <= fin:
        yield actual
        actual = date(actual.year + (actual.month == 12), actual.month % 12 + 1, 1)


def domingo_pascua(anio: int) -> date:
    """Calcula el Domingo de Pascua con el algoritmo gregoriano."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def lunes_siguiente(fecha: date) -> date:
    dias = (7 - fecha.weekday()) % 7
    return fecha + timedelta(days=dias)


def festivos_colombia(anio: int) -> set[date]:
    """Festivos nacionales definidos por la Ley 51 de 1983."""
    fijos = {
        date(anio, 1, 1),
        date(anio, 5, 1),
        date(anio, 7, 20),
        date(anio, 8, 7),
        date(anio, 12, 8),
        date(anio, 12, 25),
    }
    trasladables = {
        date(anio, 1, 6),
        date(anio, 3, 19),
        date(anio, 6, 29),
        date(anio, 8, 15),
        date(anio, 10, 12),
        date(anio, 11, 1),
        date(anio, 11, 11),
    }
    pascua = domingo_pascua(anio)
    religiosos = {
        pascua - timedelta(days=3),
        pascua - timedelta(days=2),
        lunes_siguiente(pascua + timedelta(days=39)),
        lunes_siguiente(pascua + timedelta(days=60)),
        lunes_siguiente(pascua + timedelta(days=68)),
    }
    return fijos | {lunes_siguiente(fecha) for fecha in trasladables} | religiosos


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("entrada", type=Path, help="CSV original")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path("datos_procesados"),
        help="Directorio para las salidas",
    )
    return parser.parse_args()


def main() -> None:
    args = argumentos()
    args.salida.mkdir(parents=True, exist_ok=True)

    ruta_limpia = args.salida / "vehiculos_zona_limpios.csv"
    ruta_mensual = args.salida / "serie_mensual_modelo.csv"
    ruta_reporte = args.salida / "reporte_limpieza.md"

    columnas_limpias = [
        "ID_FILA_FUENTE",
        "FECHA_MES",
        "ANIO",
        "MES",
        "DEPARTAMENTO",
        "MUNICIPIO",
        "MARCA_VEHICULO",
        "MODELO_VEHICULO",
        "TIPO_VEHICULO",
        "EDAD_REPORTADA",
        "ANTIGUEDAD_MODELO_AL_ACCIDENTE",
        "ESTADO_MODELO",
        "GRAVEDAD_ACCIDENTE",
        "AUTORIDAD_DE_TRANSITO",
    ]

    fuente_total = 0
    boyaca_total = 0
    zona_total = 0
    fechas_invalidas = 0
    fuera_periodo = 0
    modelos_invalidos = 0
    modelos_posteriores = 0
    edades_reportadas_invalidas = 0
    combinaciones = Counter()
    filas_limpias = Counter()
    periodos_validos = set()

    with (
        args.entrada.open("r", encoding="utf-8-sig", newline="") as entrada,
        ruta_limpia.open("w", encoding="utf-8", newline="") as salida,
    ):
        lector = csv.DictReader(entrada)
        escritor = csv.DictWriter(salida, fieldnames=columnas_limpias)
        escritor.writeheader()

        for numero_fila, fila in enumerate(lector, start=2):
            fuente_total += 1
            if clave_ascii(fila.get("DEPARTAMENTO_ACCIDENTE")) != "BOYACA":
                continue
            boyaca_total += 1

            municipio = clave_ascii(fila.get("MUNICIPIO_ACCIDENTE"))
            if municipio not in MUNICIPIOS_OBJETIVO:
                continue
            zona_total += 1

            periodo = mes_seguro(fila.get("FECHA_ACCIDENTE"))
            if periodo is None:
                fechas_invalidas += 1
                continue
            anio, mes = periodo
            if not 2022 <= anio <= 2026:
                fuera_periodo += 1
                continue
            periodos_validos.add(date(anio, mes, 1))

            modelo = entero_seguro(fila.get("MODELO_VEHICULO"))
            if modelo is None or not 1900 <= modelo <= 2100:
                estado_modelo = "INVALIDO"
                edad_accidente = ""
                modelos_invalidos += 1
            elif modelo > anio:
                estado_modelo = "POSTERIOR_AL_ACCIDENTE"
                edad_accidente = ""
                modelos_posteriores += 1
            else:
                estado_modelo = "VALIDO"
                edad_accidente = anio - modelo

            edad_reportada = entero_seguro(fila.get("EDAD_VEHICULO"))
            if edad_reportada is None:
                edades_reportadas_invalidas += 1

            tipo = texto_normalizado(fila.get("TIPO_VEHICULO"))
            gravedad = texto_normalizado(fila.get("GRAVEDAD_ACCIDENTE"))
            fecha_mes = f"{anio:04d}-{mes:02d}-01"

            limpia = {
                "ID_FILA_FUENTE": numero_fila,
                "FECHA_MES": fecha_mes,
                "ANIO": anio,
                "MES": mes,
                "DEPARTAMENTO": "BOYACA",
                "MUNICIPIO": municipio,
                "MARCA_VEHICULO": texto_normalizado(fila.get("MARCA_VEHICULO")),
                "MODELO_VEHICULO": modelo if modelo is not None else "",
                "TIPO_VEHICULO": tipo,
                "EDAD_REPORTADA": edad_reportada if edad_reportada is not None else "",
                "ANTIGUEDAD_MODELO_AL_ACCIDENTE": edad_accidente,
                "ESTADO_MODELO": estado_modelo,
                "GRAVEDAD_ACCIDENTE": gravedad,
                "AUTORIDAD_DE_TRANSITO": texto_normalizado(
                    fila.get("AUTORIDAD_DE_TRANSITO")
                ),
            }
            escritor.writerow(limpia)

            clave_duplicado = tuple(limpia[columna] for columna in columnas_limpias[1:])
            filas_limpias[clave_duplicado] += 1
            combinaciones[(fecha_mes, municipio, "TOTAL")] += 1
            combinaciones[(fecha_mes, municipio, gravedad)] += 1
            combinaciones[(fecha_mes, municipio, tipo)] += 1

    if not periodos_validos:
        raise RuntimeError("No se encontraron registros válidos para la zona de estudio")

    inicio = date(min(periodo.year for periodo in periodos_validos), 1, 1)
    fin = max(periodos_validos)
    columnas_mensuales = [
        "FECHA_MES",
        "ANIO",
        "MES",
        "MUNICIPIO",
        "REGISTROS_TOTAL",
        "ESTADO_COBERTURA",
        "DIAS_FESTIVOS",
        "FESTIVOS_EN_LUNES",
        "CON_HERIDOS",
        "CON_MUERTOS",
        *TIPOS_PRINCIPALES,
        "OTROS_VEHICULOS",
    ]

    with ruta_mensual.open("w", encoding="utf-8", newline="") as salida:
        escritor = csv.DictWriter(salida, fieldnames=columnas_mensuales)
        escritor.writeheader()
        for municipio in MUNICIPIOS_OBJETIVO:
            for periodo in iterar_meses(inicio, fin):
                fecha_mes = periodo.isoformat()
                total = combinaciones[(fecha_mes, municipio, "TOTAL")]
                principales = {
                    tipo: combinaciones[(fecha_mes, municipio, tipo)]
                    for tipo in TIPOS_PRINCIPALES
                }
                festivos_mes = {
                    festivo
                    for festivo in festivos_colombia(periodo.year)
                    if festivo.month == periodo.month
                }
                estado_cobertura = (
                    "CERO_SOSPECHOSO"
                    if municipio == "SOGAMOSO" and total == 0
                    else "OBSERVADO"
                )
                escritor.writerow(
                    {
                        "FECHA_MES": fecha_mes,
                        "ANIO": periodo.year,
                        "MES": periodo.month,
                        "MUNICIPIO": municipio,
                        "REGISTROS_TOTAL": total,
                        "ESTADO_COBERTURA": estado_cobertura,
                        "DIAS_FESTIVOS": len(festivos_mes),
                        "FESTIVOS_EN_LUNES": sum(
                            festivo.weekday() == calendar.MONDAY
                            for festivo in festivos_mes
                        ),
                        "CON_HERIDOS": combinaciones[
                            (fecha_mes, municipio, "CON HERIDOS")
                        ],
                        "CON_MUERTOS": combinaciones[
                            (fecha_mes, municipio, "CON MUERTOS")
                        ],
                        **principales,
                        "OTROS_VEHICULOS": total - sum(principales.values()),
                    }
                )

    duplicados_adicionales = sum(
        cantidad - 1 for cantidad in filas_limpias.values() if cantidad > 1
    )
    registros_limpios = sum(filas_limpias.values())
    meses_generados = sum(1 for _ in iterar_meses(inicio, fin))
    ceros_sospechosos = sum(
        1
        for municipio in MUNICIPIOS_OBJETIVO
        for periodo in iterar_meses(inicio, fin)
        if municipio == "SOGAMOSO"
        and combinaciones[(periodo.isoformat(), municipio, "TOTAL")] == 0
    )

    reporte = f"""# Reporte de limpieza

## Alcance

- Fuente: `{args.entrada.name}`
- Zona: Tunja, Duitama y Sogamoso
- Periodo conservado: {inicio:%Y-%m} a {fin:%Y-%m}
- Unidad: vehículos involucrados, no accidentes únicos

## Resultados

- Filas leídas: {fuente_total:,}
- Filas de Boyacá: {boyaca_total:,}
- Filas encontradas en la zona: {zona_total:,}
- Filas limpias exportadas: {registros_limpios:,}
- Fechas inválidas descartadas: {fechas_invalidas:,}
- Filas fuera del periodo descartadas: {fuera_periodo:,}
- Modelos de vehículo inválidos: {modelos_invalidos:,}
- Modelos posteriores al año del accidente: {modelos_posteriores:,}
- Edades reportadas vacías o mal formadas: {edades_reportadas_invalidas:,}
- Repeticiones exactas adicionales detectadas: {duplicados_adicionales:,}
- Meses por municipio en la serie completa: {meses_generados:,}
- Filas de la serie mensual: {meses_generados * len(MUNICIPIOS_OBJETIVO):,}
- Ceros sospechosos marcados en Sogamoso: {ceros_sospechosos:,}

## Decisiones

- El CSV original no fue modificado.
- Las repeticiones exactas no se eliminaron porque no existe un identificador de accidente o vehículo.
- `ANTIGUEDAD_MODELO_AL_ACCIDENTE` se calculó como `ANIO - MODELO_VEHICULO`; es una aproximación basada en el año-modelo, no la edad real desde la matrícula.
- La edad original se conserva como `EDAD_REPORTADA`, pero no debe usarse como variable principal.
- Los meses sin registros se incluyen con cero para mantener una serie temporal continua. Esto supone cobertura administrativa completa y debe validarse con la fuente.
- Los ceros de Sogamoso se marcan como `CERO_SOSPECHOSO` para permitir una evaluación alternativa tratándolos como datos faltantes.
- Se agregan festivos nacionales mensuales calculados según la Ley 51 de 1983.
- El corte final se determina con el último mes realmente observado en la zona, no con el último mes del archivo nacional.
"""
    ruta_reporte.write_text(reporte, encoding="utf-8")

    print(f"Registros limpios: {registros_limpios:,}")
    print(f"Serie mensual: {meses_generados * len(MUNICIPIOS_OBJETIVO):,} filas")
    print(f"Salidas: {args.salida.resolve()}")


if __name__ == "__main__":
    main()
