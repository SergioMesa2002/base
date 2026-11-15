#!/usr/bin/env python3
"""Genera un recurso JavaScript offline para la interfaz de predicción."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("serie", type=Path)
    parser.add_argument("pronostico", type=Path)
    parser.add_argument("pronostico_clima", type=Path)
    parser.add_argument("metricas", type=Path)
    parser.add_argument("metricas_clima", type=Path)
    parser.add_argument("--salida", type=Path, required=True)
    return parser.parse_args()


def registros(df: pd.DataFrame, columnas: list[str]) -> list[dict]:
    salida = df[columnas].copy()
    if "FECHA_MES" in salida:
        salida["FECHA_MES"] = pd.to_datetime(salida["FECHA_MES"]).dt.strftime("%Y-%m-%d")
    salida = salida.where(pd.notna(salida), None)
    return salida.to_dict(orient="records")


def main() -> None:
    args = argumentos()
    serie = pd.read_csv(args.serie, parse_dates=["FECHA_MES"])
    pronostico = pd.read_csv(args.pronostico, parse_dates=["FECHA_MES"])
    pronostico_clima = pd.read_csv(args.pronostico_clima, parse_dates=["FECHA_MES"])
    metricas = pd.read_csv(args.metricas)
    metricas_clima = pd.read_csv(args.metricas_clima)

    escenario = "CEROS_COMO_FALTANTES"
    base_prueba = metricas[
        metricas["PERIODO"].eq("PRUEBA_2026")
        & metricas["MUNICIPIO"].eq("TODOS")
        & metricas["ESCENARIO"].eq(escenario)
        & metricas["MODELO"].eq("promedio_3_meses")
    ].iloc[0]
    clima_prueba = metricas_clima[
        metricas_clima["PERIODO"].eq("PRUEBA_2026")
        & metricas_clima["MUNICIPIO"].eq("TODOS")
        & metricas_clima["ESCENARIO"].eq(escenario)
        & metricas_clima["MODELO"].eq("random_forest")
    ].iloc[0]

    columnas_historia = [
        "FECHA_MES",
        "MUNICIPIO",
        "REGISTROS_TOTAL",
        "ESTADO_COBERTURA",
        "MOTOCICLETA",
        "AUTOMOVIL",
        "CAMIONETA",
        "CAMION",
        "TRACTOCAMION",
        "OTROS_VEHICULOS",
        "PRECIPITACION_MM",
        "DIAS_CON_LLUVIA",
        "PRECIPITACION_MAX_DIA",
        "COBERTURA_PCT",
        "ESTADO_COBERTURA_CLIMA",
    ]
    datos = {
        "meta": {
            "actualizado": str(serie["FECHA_MES"].max().date()),
            "periodo_inicio": str(serie["FECHA_MES"].min().date()),
            "periodo_fin": str(serie["FECHA_MES"].max().date()),
            "fecha_pronostico": str(pronostico["FECHA_MES"].max().date()),
            "unidad": "vehículos involucrados",
            "modelo_principal": "Promedio de 3 meses",
            "modelo_clima": "Random Forest experimental",
            "wape_principal": round(float(base_prueba["WAPE_PCT"]), 2),
            "mae_principal": round(float(base_prueba["MAE"]), 2),
            "wape_clima": round(float(clima_prueba["WAPE_PCT"]), 2),
            "mae_clima": round(float(clima_prueba["MAE"]), 2),
        },
        "pronosticos": registros(
            pronostico,
            [
                "FECHA_MES",
                "MUNICIPIO",
                "MODELO",
                "PREDICCION",
                "LIMITE_INFERIOR",
                "LIMITE_SUPERIOR",
            ],
        ),
        "pronosticos_clima": registros(
            pronostico_clima,
            [
                "FECHA_MES",
                "MUNICIPIO",
                "MODELO",
                "PREDICCION",
                "LIMITE_INFERIOR",
                "LIMITE_SUPERIOR",
                "PRECIPITACION_MM",
                "DIAS_CON_LLUVIA",
                "PRECIPITACION_MAX_DIA",
            ],
        ),
        "historia": registros(serie.sort_values(["MUNICIPIO", "FECHA_MES"]), columnas_historia),
    }

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    contenido = "/* Generado desde las salidas del modelo. */\nwindow.APP_DATA="
    contenido += json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    contenido += ";\n"
    args.salida.write_text(contenido, encoding="utf-8")
    print(f"Datos web: {args.salida.resolve()}")
    print(f"Historia: {len(datos['historia'])} filas")
    print(f"Pronósticos: {len(datos['pronosticos'])} municipios")


if __name__ == "__main__":
    main()
