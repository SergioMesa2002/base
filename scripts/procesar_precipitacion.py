#!/usr/bin/env python3
"""Agrega la precipitación diaria del IDEAM al nivel municipio-mes."""

from __future__ import annotations

import argparse
import calendar
from pathlib import Path

import numpy as np
import pandas as pd


ESTACIONES_DIARIAS = {
    "TUNJA": [
        ("24035130", "UPTC", 1),
    ],
    "DUITAMA": [
        ("24030350", "DUITAMA", 1),
        ("24035120", "SURBATA BONZA", 2),
        ("24035350", "ANDALUCIA", 3),
    ],
    "SOGAMOSO": [
        ("24035340", "AEROPUERTO ALBERTO LLERAS", 1),
        ("24030940", "SENA", 2),
        ("35190010", "LAS CINTAS", 3),
    ],
}

ESTACION_AUTOMATICA_TUNJA = ("2401500086", "UPTC AUTOMATICA", 0)
UMBRAL_COBERTURA = 80.0


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("directorio", type=Path, help="Directorio de archivos .data")
    parser.add_argument(
        "--automatica-tunja",
        type=Path,
        help="CSV de la estación automática UPTC descargado de Datos Abiertos",
    )
    parser.add_argument(
        "--accidentes",
        type=Path,
        help="Serie mensual de accidentes que se unirá con el clima",
    )
    parser.add_argument("--inicio", default="2022-01", help="Primer mes AAAA-MM")
    parser.add_argument("--fin", default="2026-10", help="Último mes AAAA-MM")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path("datos_procesados"),
        help="Directorio de salida",
    )
    return parser.parse_args()


def agregar_diaria(
    ruta: Path,
    municipio: str,
    codigo: str,
    nombre: str,
    prioridad: int,
) -> pd.DataFrame:
    datos = pd.read_csv(ruta, sep="|", parse_dates=["Fecha"])
    datos["Valor"] = pd.to_numeric(datos["Valor"], errors="coerce")
    datos = datos.dropna(subset=["Fecha", "Valor"])
    datos["DIA"] = datos["Fecha"].dt.normalize()
    diarios = datos.groupby("DIA", as_index=False)["Valor"].sum()
    diarios["FECHA_MES"] = diarios["DIA"].dt.to_period("M").dt.to_timestamp()

    mensual = diarios.groupby("FECHA_MES", as_index=False).agg(
        PRECIPITACION_MM_BRUTA=("Valor", "sum"),
        DIAS_CON_DATO=("DIA", "nunique"),
        DIAS_CON_LLUVIA_BRUTO=("Valor", lambda serie: int((serie > 0.1).sum())),
        PRECIPITACION_MAX_DIA_BRUTA=("Valor", "max"),
    )
    mensual["DIAS_ESPERADOS"] = mensual["FECHA_MES"].map(
        lambda fecha: calendar.monthrange(fecha.year, fecha.month)[1]
    )
    mensual["COBERTURA_PCT"] = (
        100 * mensual["DIAS_CON_DATO"] / mensual["DIAS_ESPERADOS"]
    ).clip(upper=100)
    mensual["MUNICIPIO"] = municipio
    mensual["ESTACION_CODIGO"] = codigo
    mensual["ESTACION_NOMBRE"] = nombre
    mensual["FUENTE_CLIMA"] = "IDEAM_DIARIA"
    mensual["PRIORIDAD"] = prioridad
    return mensual


def agregar_automatica(
    ruta: Path,
    municipio: str,
    codigo: str,
    nombre: str,
    prioridad: int,
) -> pd.DataFrame:
    datos = pd.read_csv(ruta, parse_dates=["fechaobservacion"])
    datos["valorobservado"] = pd.to_numeric(datos["valorobservado"], errors="coerce")
    datos = datos.dropna(subset=["fechaobservacion", "valorobservado"])
    datos = datos.drop_duplicates(subset=["fechaobservacion", "valorobservado"])
    datos = datos.drop_duplicates(subset=["fechaobservacion"], keep="first")
    datos["DIA"] = datos["fechaobservacion"].dt.normalize()
    datos["FECHA_MES"] = datos["fechaobservacion"].dt.to_period("M").dt.to_timestamp()

    por_dia = datos.groupby(["FECHA_MES", "DIA"], as_index=False).agg(
        LLUVIA_DIA=("valorobservado", "sum")
    )
    mensual = por_dia.groupby("FECHA_MES", as_index=False).agg(
        PRECIPITACION_MM_BRUTA=("LLUVIA_DIA", "sum"),
        DIAS_CON_DATO=("DIA", "nunique"),
        DIAS_CON_LLUVIA_BRUTO=("LLUVIA_DIA", lambda serie: int((serie > 0.1).sum())),
        PRECIPITACION_MAX_DIA_BRUTA=("LLUVIA_DIA", "max"),
    )
    observaciones = datos.groupby("FECHA_MES")["fechaobservacion"].nunique()
    mensual["DIAS_ESPERADOS"] = mensual["FECHA_MES"].map(
        lambda fecha: calendar.monthrange(fecha.year, fecha.month)[1]
    )
    mensual["COBERTURA_PCT"] = mensual.apply(
        lambda fila: 100
        * observaciones.loc[fila["FECHA_MES"]]
        / (fila["DIAS_ESPERADOS"] * 144),
        axis=1,
    ).clip(upper=100)
    mensual["MUNICIPIO"] = municipio
    mensual["ESTACION_CODIGO"] = codigo
    mensual["ESTACION_NOMBRE"] = nombre
    mensual["FUENTE_CLIMA"] = "IDEAM_AUTOMATICA_10_MIN"
    mensual["PRIORIDAD"] = prioridad
    return mensual


def estado_cobertura(porcentaje: float) -> str:
    if porcentaje >= 90:
        return "COMPLETA"
    if porcentaje >= UMBRAL_COBERTURA:
        return "ACEPTABLE"
    if porcentaje > 0:
        return "INSUFICIENTE"
    return "SIN_DATOS"


def main() -> None:
    args = argumentos()
    args.salida.mkdir(parents=True, exist_ok=True)
    inicio = pd.Period(args.inicio, freq="M")
    fin = pd.Period(args.fin, freq="M")
    meses = pd.period_range(inicio, fin, freq="M").to_timestamp()

    candidatos = []
    archivos_ausentes = []
    for municipio, estaciones in ESTACIONES_DIARIAS.items():
        for codigo, nombre, prioridad in estaciones:
            ruta = args.directorio / f"PTPM_CON_INTER@{codigo}.data"
            if not ruta.exists():
                archivos_ausentes.append(str(ruta))
                continue
            candidatos.append(
                agregar_diaria(ruta, municipio, codigo, nombre, prioridad)
            )

    if args.automatica_tunja:
        codigo, nombre, prioridad = ESTACION_AUTOMATICA_TUNJA
        candidatos.append(
            agregar_automatica(
                args.automatica_tunja, "TUNJA", codigo, nombre, prioridad
            )
        )

    if not candidatos:
        raise RuntimeError("No se encontraron series de precipitación utilizables")

    todas = pd.concat(candidatos, ignore_index=True)
    todas = todas[todas["FECHA_MES"].between(meses.min(), meses.max())]
    todas = todas.sort_values(
        ["MUNICIPIO", "FECHA_MES", "COBERTURA_PCT", "PRIORIDAD"],
        ascending=[True, True, False, True],
    )
    seleccion = todas.drop_duplicates(["MUNICIPIO", "FECHA_MES"], keep="first")

    indice = pd.MultiIndex.from_product(
        [ESTACIONES_DIARIAS, meses], names=["MUNICIPIO", "FECHA_MES"]
    )
    seleccion = seleccion.set_index(["MUNICIPIO", "FECHA_MES"]).reindex(indice)
    seleccion = seleccion.reset_index()
    seleccion["DIAS_ESPERADOS"] = seleccion["FECHA_MES"].map(
        lambda fecha: calendar.monthrange(fecha.year, fecha.month)[1]
    )
    seleccion["COBERTURA_PCT"] = seleccion["COBERTURA_PCT"].fillna(0.0)
    seleccion["DIAS_CON_DATO"] = seleccion["DIAS_CON_DATO"].fillna(0).astype(int)
    seleccion["ESTADO_COBERTURA_CLIMA"] = seleccion["COBERTURA_PCT"].map(
        estado_cobertura
    )
    utilizable = seleccion["COBERTURA_PCT"] >= UMBRAL_COBERTURA
    seleccion["PRECIPITACION_MM"] = seleccion["PRECIPITACION_MM_BRUTA"].where(
        utilizable
    )
    seleccion["DIAS_CON_LLUVIA"] = seleccion["DIAS_CON_LLUVIA_BRUTO"].where(
        utilizable
    )
    seleccion["PRECIPITACION_MAX_DIA"] = seleccion[
        "PRECIPITACION_MAX_DIA_BRUTA"
    ].where(utilizable)
    seleccion["ANIO"] = seleccion["FECHA_MES"].dt.year
    seleccion["MES"] = seleccion["FECHA_MES"].dt.month

    columnas = [
        "FECHA_MES",
        "ANIO",
        "MES",
        "MUNICIPIO",
        "PRECIPITACION_MM",
        "DIAS_CON_LLUVIA",
        "PRECIPITACION_MAX_DIA",
        "PRECIPITACION_MM_BRUTA",
        "DIAS_CON_LLUVIA_BRUTO",
        "PRECIPITACION_MAX_DIA_BRUTA",
        "DIAS_CON_DATO",
        "DIAS_ESPERADOS",
        "COBERTURA_PCT",
        "ESTADO_COBERTURA_CLIMA",
        "ESTACION_CODIGO",
        "ESTACION_NOMBRE",
        "FUENTE_CLIMA",
    ]
    seleccion = seleccion[columnas].sort_values(["MUNICIPIO", "FECHA_MES"])
    ruta_clima = args.salida / "precipitacion_mensual.csv"
    seleccion.to_csv(ruta_clima, index=False, float_format="%.2f")

    ruta_unida = None
    if args.accidentes:
        accidentes = pd.read_csv(args.accidentes, parse_dates=["FECHA_MES"])
        clima_modelo = seleccion[
            [
                "FECHA_MES",
                "MUNICIPIO",
                "PRECIPITACION_MM",
                "DIAS_CON_LLUVIA",
                "PRECIPITACION_MAX_DIA",
                "COBERTURA_PCT",
                "ESTADO_COBERTURA_CLIMA",
                "ESTACION_CODIGO",
                "FUENTE_CLIMA",
            ]
        ]
        unida = accidentes.merge(
            clima_modelo, on=["FECHA_MES", "MUNICIPIO"], how="left", validate="1:1"
        )
        ruta_unida = args.salida / "serie_mensual_con_clima.csv"
        unida.to_csv(ruta_unida, index=False, float_format="%.2f")

    resumen = seleccion.groupby(["MUNICIPIO", "ESTADO_COBERTURA_CLIMA"]).size()
    uso = (
        seleccion.dropna(subset=["ESTACION_CODIGO"])
        .groupby(["MUNICIPIO", "ESTACION_CODIGO", "ESTACION_NOMBRE"])
        .size()
    )
    reporte = f"""# Reporte de precipitación

## Alcance

- Periodo: {inicio} a {fin}
- Municipios: Tunja, Duitama y Sogamoso
- Umbral para usar una medición en el modelo: {UMBRAL_COBERTURA:.0f}%
- Archivo mensual: `{ruta_clima.name}`
- Serie combinada: `{ruta_unida.name if ruta_unida else 'no solicitada'}`

## Cobertura por municipio

```
{resumen.to_string()}
```

## Estaciones seleccionadas

```
{uso.to_string()}
```

## Decisiones

- Cada mes usa la estación con mayor cobertura disponible dentro del municipio.
- En empates se conserva la estación prioritaria más cercana o representativa.
- Los duplicados exactos de fecha y valor de la estación automática se eliminan.
- Los meses por debajo de {UMBRAL_COBERTURA:.0f}% conservan el valor bruto para auditoría, pero las variables destinadas al modelo quedan vacías.
- Los faltantes no se convierten en lluvia cero.
- La lluvia automática es preliminar y requiere las cautelas de calidad indicadas por el IDEAM.
"""
    if archivos_ausentes:
        reporte += "\n## Archivos ausentes\n\n" + "\n".join(
            f"- `{ruta}`" for ruta in archivos_ausentes
        )
    (args.salida / "reporte_precipitacion.md").write_text(reporte, encoding="utf-8")

    utilizables = int(utilizable.sum())
    print(f"Meses generados: {len(seleccion)}")
    print(f"Meses utilizables: {utilizables}/{len(seleccion)}")
    print(f"Clima mensual: {ruta_clima.resolve()}")
    if ruta_unida:
        print(f"Serie combinada: {ruta_unida.resolve()}")


if __name__ == "__main__":
    main()
