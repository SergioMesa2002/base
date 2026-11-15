#!/usr/bin/env python3
"""Entrena y valida modelos de volumen mensual para la zona de estudio."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from limpiar_dataset import festivos_colombia
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


OBJETIVO = "REGISTROS_TOTAL"
CATEGORICAS = ["MUNICIPIO"]
NUMERICAS_BASE = [
    "MES_SIN",
    "MES_COS",
    "TENDENCIA_TIEMPO",
    "DIAS_FESTIVOS",
    "FESTIVOS_EN_LUNES",
    "LAG_1",
    "LAG_2",
    "LAG_3",
    "PROMEDIO_3",
    "PROMEDIO_6",
    "LAG_12",
]
NUMERICAS_CLIMA = [
    "PRECIPITACION_MM",
    "DIAS_CON_LLUVIA",
    "PRECIPITACION_MAX_DIA",
]
NUMERICAS = NUMERICAS_BASE.copy()
VARIABLES = CATEGORICAS + NUMERICAS


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("entrada", type=Path, help="Serie mensual limpia")
    parser.add_argument("--salida", type=Path, default=Path("modelos"))
    parser.add_argument(
        "--usar-clima",
        action="store_true",
        help="Incluye las columnas de precipitación presentes en la entrada",
    )
    return parser.parse_args()


def crear_variables(datos: pd.DataFrame) -> pd.DataFrame:
    datos = datos.sort_values(["MUNICIPIO", "FECHA_MES"]).copy()
    datos["MES_SIN"] = np.sin(2 * np.pi * datos["MES"] / 12)
    datos["MES_COS"] = np.cos(2 * np.pi * datos["MES"] / 12)
    origen = datos["FECHA_MES"].min()
    datos["TENDENCIA_TIEMPO"] = (
        (datos["FECHA_MES"].dt.year - origen.year) * 12
        + datos["FECHA_MES"].dt.month
        - origen.month
    )
    grupo = datos.groupby("MUNICIPIO", sort=False)[OBJETIVO]
    for retraso in (1, 2, 3, 12):
        datos[f"LAG_{retraso}"] = grupo.shift(retraso)
    for ventana in (3, 6):
        datos[f"PROMEDIO_{ventana}"] = grupo.transform(
            lambda serie: serie.shift(1).rolling(ventana, min_periods=ventana).mean()
        )
    return datos


def preprocesador(escalar: bool) -> ColumnTransformer:
    pasos_numericos = [("imputar", SimpleImputer(strategy="median"))]
    if escalar:
        pasos_numericos.append(("escalar", StandardScaler()))
    return ColumnTransformer(
        [
            ("categorias", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAS),
            ("numericas", Pipeline(pasos_numericos), NUMERICAS),
        ],
        verbose_feature_names_out=False,
    )


def candidatos() -> dict[str, Pipeline]:
    return {
        "poisson": Pipeline(
            [
                ("preparar", preprocesador(escalar=True)),
                ("modelo", PoissonRegressor(alpha=1.0, max_iter=2_000)),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("preparar", preprocesador(escalar=False)),
                (
                    "modelo",
                    RandomForestRegressor(
                        n_estimators=400,
                        max_depth=5,
                        min_samples_leaf=3,
                        max_features=0.8,
                        random_state=42,
                        n_jobs=-1,
                    ),
                ),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                ("preparar", preprocesador(escalar=False)),
                (
                    "modelo",
                    GradientBoostingRegressor(
                        n_estimators=250,
                        learning_rate=0.03,
                        max_depth=2,
                        min_samples_leaf=4,
                        loss="huber",
                        random_state=42,
                    ),
                ),
            ]
        ),
    }


def prediccion_referencia(nombre: str, prueba: pd.DataFrame) -> np.ndarray:
    columna = {
        "mes_anterior": "LAG_1",
        "promedio_3_meses": "PROMEDIO_3",
        "mismo_mes_anterior": "LAG_12",
    }[nombre]
    return prueba[columna].to_numpy(dtype=float)


def validar_expandido(
    datos: pd.DataFrame,
    fechas: list[pd.Timestamp],
) -> pd.DataFrame:
    referencias = ("mes_anterior", "promedio_3_meses", "mismo_mes_anterior")
    modelos = candidatos()
    resultados = []

    for fecha in fechas:
        entrenamiento = datos[datos["FECHA_MES"] < fecha].dropna(
            subset=["LAG_12", OBJETIVO]
        )
        prueba = datos[datos["FECHA_MES"] == fecha].dropna(
            subset=["LAG_12", OBJETIVO]
        )
        if entrenamiento.empty or prueba.empty:
            continue

        for nombre in referencias:
            prediccion = prediccion_referencia(nombre, prueba)
            for fila, estimado in zip(prueba.itertuples(index=False), prediccion):
                resultados.append(
                    {
                        "FECHA_MES": fecha,
                        "MUNICIPIO": fila.MUNICIPIO,
                        "MODELO": nombre,
                        "REAL": fila.REGISTROS_TOTAL,
                        "PREDICCION": max(0.0, float(estimado)),
                    }
                )

        for nombre, modelo in modelos.items():
            modelo.fit(entrenamiento[VARIABLES], entrenamiento[OBJETIVO])
            prediccion = np.maximum(0, modelo.predict(prueba[VARIABLES]))
            for fila, estimado in zip(prueba.itertuples(index=False), prediccion):
                resultados.append(
                    {
                        "FECHA_MES": fecha,
                        "MUNICIPIO": fila.MUNICIPIO,
                        "MODELO": nombre,
                        "REAL": fila.REGISTROS_TOTAL,
                        "PREDICCION": float(estimado),
                    }
                )

    salida = pd.DataFrame(resultados)
    salida["ERROR_ABS"] = (salida["REAL"] - salida["PREDICCION"]).abs()
    return salida


def calcular_metricas(predicciones: pd.DataFrame, periodo: str) -> pd.DataFrame:
    filas = []
    grupos = [("TODOS", predicciones)] + list(predicciones.groupby("MUNICIPIO"))
    for municipio, subconjunto in grupos:
        for modelo, grupo in subconjunto.groupby("MODELO"):
            real = grupo["REAL"].to_numpy()
            estimado = grupo["PREDICCION"].to_numpy()
            denominador = real.sum()
            filas.append(
                {
                    "PERIODO": periodo,
                    "MUNICIPIO": municipio,
                    "MODELO": modelo,
                    "OBSERVACIONES": len(grupo),
                    "MAE": mean_absolute_error(real, estimado),
                    "RMSE": mean_squared_error(real, estimado) ** 0.5,
                    "WAPE_PCT": 100 * np.abs(real - estimado).sum() / denominador
                    if denominador
                    else np.nan,
                }
            )
    return pd.DataFrame(filas)


def predecir_modelo(
    nombre: str,
    entrenamiento: pd.DataFrame,
    prueba: pd.DataFrame,
) -> tuple[np.ndarray, Pipeline | None]:
    if nombre in {"mes_anterior", "promedio_3_meses", "mismo_mes_anterior"}:
        return np.maximum(0, prediccion_referencia(nombre, prueba)), None
    modelo = candidatos()[nombre]
    modelo.fit(entrenamiento[VARIABLES], entrenamiento[OBJETIVO])
    return np.maximum(0, modelo.predict(prueba[VARIABLES])), modelo


def main() -> None:
    global NUMERICAS, VARIABLES
    args = argumentos()
    args.salida.mkdir(parents=True, exist_ok=True)
    datos_fuente = pd.read_csv(args.entrada, parse_dates=["FECHA_MES"])
    if args.usar_clima:
        faltantes = [columna for columna in NUMERICAS_CLIMA if columna not in datos_fuente]
        if faltantes:
            raise ValueError(
                "Faltan columnas climáticas en la entrada: " + ", ".join(faltantes)
            )
        NUMERICAS = NUMERICAS_BASE + NUMERICAS_CLIMA
        VARIABLES = CATEGORICAS + NUMERICAS

    datos_publicados = crear_variables(datos_fuente.copy())
    datos_publicados["VALOR_SERIE"] = datos_publicados[OBJETIVO]

    datos_ajustados = datos_fuente.copy()
    sospechosos = datos_ajustados["ESTADO_COBERTURA"].eq("CERO_SOSPECHOSO")
    datos_ajustados.loc[sospechosos, OBJETIVO] = np.nan
    datos_ajustados[OBJETIVO] = datos_ajustados.groupby("MUNICIPIO")[OBJETIVO].transform(
        lambda serie: serie.interpolate(method="linear", limit_direction="both")
    )
    datos_ajustados = crear_variables(datos_ajustados)
    datos_ajustados["VALOR_SERIE"] = datos_ajustados[OBJETIVO]
    datos_ajustados.loc[
        datos_ajustados["ESTADO_COBERTURA"].eq("CERO_SOSPECHOSO"), OBJETIVO
    ] = np.nan
    datos = datos_ajustados

    fechas_desarrollo = sorted(
        datos.loc[datos["ANIO"].between(2024, 2025), "FECHA_MES"].unique()
    )
    fechas_prueba = sorted(datos.loc[datos["ANIO"] == 2026, "FECHA_MES"].unique())

    pred_desarrollo_publicado = validar_expandido(datos_publicados, fechas_desarrollo)
    pred_desarrollo_publicado["ESCENARIO"] = "CEROS_PUBLICADOS"
    metricas_desarrollo_publicado = calcular_metricas(
        pred_desarrollo_publicado, "VALIDACION_2024_2025"
    )
    metricas_desarrollo_publicado["ESCENARIO"] = "CEROS_PUBLICADOS"

    pred_desarrollo = validar_expandido(datos_ajustados, fechas_desarrollo)
    pred_desarrollo["ESCENARIO"] = "CEROS_COMO_FALTANTES"
    metricas_desarrollo = calcular_metricas(pred_desarrollo, "VALIDACION_2024_2025")
    metricas_desarrollo["ESCENARIO"] = "CEROS_COMO_FALTANTES"
    ranking = metricas_desarrollo[metricas_desarrollo["MUNICIPIO"] == "TODOS"].sort_values(
        ["WAPE_PCT", "MAE"]
    )
    ganador = ranking.iloc[0]["MODELO"]

    pred_prueba_publicado = validar_expandido(datos_publicados, fechas_prueba)
    pred_prueba_publicado["ESCENARIO"] = "CEROS_PUBLICADOS"
    metricas_prueba_publicado = calcular_metricas(pred_prueba_publicado, "PRUEBA_2026")
    metricas_prueba_publicado["ESCENARIO"] = "CEROS_PUBLICADOS"

    pred_prueba = validar_expandido(datos_ajustados, fechas_prueba)
    pred_prueba["ESCENARIO"] = "CEROS_COMO_FALTANTES"
    metricas_prueba = calcular_metricas(pred_prueba, "PRUEBA_2026")
    metricas_prueba["ESCENARIO"] = "CEROS_COMO_FALTANTES"
    metricas = pd.concat(
        [
            metricas_desarrollo_publicado,
            metricas_desarrollo,
            metricas_prueba_publicado,
            metricas_prueba,
        ],
        ignore_index=True,
    )

    errores_ganador = pred_desarrollo[pred_desarrollo["MODELO"] == ganador]
    cuantiles = errores_ganador.groupby("MUNICIPIO")["ERROR_ABS"].quantile(0.90).to_dict()
    cuantiles["GLOBAL"] = float(errores_ganador["ERROR_ABS"].quantile(0.90))

    pred_prueba_ganador = pred_prueba[pred_prueba["MODELO"] == ganador].copy()
    pred_prueba_ganador["MARGEN_90"] = pred_prueba_ganador["MUNICIPIO"].map(cuantiles)
    pred_prueba_ganador["LIMITE_INFERIOR"] = (
        pred_prueba_ganador["PREDICCION"] - pred_prueba_ganador["MARGEN_90"]
    ).clip(lower=0)
    pred_prueba_ganador["LIMITE_SUPERIOR"] = (
        pred_prueba_ganador["PREDICCION"] + pred_prueba_ganador["MARGEN_90"]
    )

    entrenamiento_final = datos.dropna(subset=["LAG_12", OBJETIVO])
    _, modelo_final = predecir_modelo(ganador, entrenamiento_final, entrenamiento_final.tail(1))
    if modelo_final is not None:
        joblib.dump(modelo_final, args.salida / "modelo_ml_seleccionado.joblib")

    siguiente_fecha = datos["FECHA_MES"].max() + pd.offsets.MonthBegin(1)
    filas_futuras = []
    for municipio, historial in datos.groupby("MUNICIPIO"):
        historial = historial.sort_values("FECHA_MES")
        valores = historial["VALOR_SERIE"]
        numero_mes = siguiente_fecha.month
        festivos_mes = {
            festivo
            for festivo in festivos_colombia(siguiente_fecha.year)
            if festivo.month == numero_mes
        }
        filas_futuras.append(
            {
                "FECHA_MES": siguiente_fecha,
                "ANIO": siguiente_fecha.year,
                "MES": numero_mes,
                "MUNICIPIO": municipio,
                "MES_SIN": np.sin(2 * np.pi * numero_mes / 12),
                "MES_COS": np.cos(2 * np.pi * numero_mes / 12),
                "TENDENCIA_TIEMPO": historial["TENDENCIA_TIEMPO"].max() + 1,
                "DIAS_FESTIVOS": len(festivos_mes),
                "FESTIVOS_EN_LUNES": sum(
                    festivo.weekday() == 0 for festivo in festivos_mes
                ),
                "LAG_1": valores.iloc[-1],
                "LAG_2": valores.iloc[-2],
                "LAG_3": valores.iloc[-3],
                "PROMEDIO_3": valores.iloc[-3:].mean(),
                "PROMEDIO_6": valores.iloc[-6:].mean(),
                "LAG_12": valores.iloc[-12],
                **(
                    {
                        variable: historial.loc[
                            historial["MES"] == numero_mes, variable
                        ].median()
                        for variable in NUMERICAS_CLIMA
                    }
                    if args.usar_clima
                    else {}
                ),
            }
        )
    futuro = pd.DataFrame(filas_futuras)
    pred_futuro, modelo_final = predecir_modelo(ganador, entrenamiento_final, futuro)
    futuro["MODELO"] = ganador
    futuro["PREDICCION"] = pred_futuro
    futuro["MARGEN_90"] = futuro["MUNICIPIO"].map(cuantiles).fillna(cuantiles["GLOBAL"])
    futuro["LIMITE_INFERIOR"] = (futuro["PREDICCION"] - futuro["MARGEN_90"]).clip(0)
    futuro["LIMITE_SUPERIOR"] = futuro["PREDICCION"] + futuro["MARGEN_90"]

    metricas.to_csv(args.salida / "metricas_modelos.csv", index=False, float_format="%.3f")
    pd.concat([pred_desarrollo_publicado, pred_desarrollo], ignore_index=True).to_csv(
        args.salida / "predicciones_validacion.csv", index=False, float_format="%.3f"
    )
    pd.concat([pred_prueba_publicado, pred_prueba], ignore_index=True).to_csv(
        args.salida / "predicciones_prueba_todos_modelos.csv",
        index=False,
        float_format="%.3f",
    )
    pred_prueba_ganador.to_csv(
        args.salida / "predicciones_prueba_2026.csv", index=False, float_format="%.3f"
    )
    columnas_pronostico = [
        "FECHA_MES",
        "MUNICIPIO",
        "MODELO",
        "PREDICCION",
        "LIMITE_INFERIOR",
        "LIMITE_SUPERIOR",
    ]
    if args.usar_clima:
        columnas_pronostico += NUMERICAS_CLIMA
    futuro[columnas_pronostico].to_csv(
        args.salida / "pronostico_siguiente_mes.csv",
        index=False,
        float_format="%.1f",
    )

    configuracion = {
        "objetivo": OBJETIVO,
        "escenario_seleccionado": "CEROS_COMO_FALTANTES",
        "modelo_seleccionado": ganador,
        "variables": VARIABLES,
        "usa_clima": args.usar_clima,
        "supuesto_clima_futuro": (
            "mediana histórica del municipio para el mismo mes"
            if args.usar_clima
            else None
        ),
        "periodo_validacion": "2024-01 a 2025-12",
        "periodo_prueba": "2026-01 a 2026-08",
        "intervalo": "cuantil 90% del error absoluto en validación",
        "margen_por_municipio": cuantiles,
    }
    (args.salida / "modelo_seleccionado.json").write_text(
        json.dumps(configuracion, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ganador_desarrollo = ranking.iloc[0]
    ganador_prueba = metricas_prueba[
        (metricas_prueba["MUNICIPIO"] == "TODOS")
        & (metricas_prueba["MODELO"] == ganador)
    ].iloc[0]
    publicado_mejor = metricas_desarrollo_publicado[
        metricas_desarrollo_publicado["MUNICIPIO"] == "TODOS"
    ].sort_values(["WAPE_PCT", "MAE"]).iloc[0]
    ceros_sogamoso = int(
        datos_fuente["ESTADO_COBERTURA"].eq("CERO_SOSPECHOSO").sum()
    )
    detalle_clima = (
        "- Se incorporaron precipitación mensual, días con lluvia y máxima diaria.\n"
        "- Para el pronóstico futuro sin un parte meteorológico se usa la mediana "
        "histórica del mismo municipio y mes."
        if args.usar_clima
        else ""
    )
    advertencia_clima = (
        "- La lluvia del mes evaluado se trata como un factor de escenario conocido. "
        "Para una predicción previa al mes debe suministrarse un pronóstico de lluvia "
        "o una hipótesis del simulador."
        if args.usar_clima
        else ""
    )
    reporte = f"""# Reporte del primer entrenamiento

## Objetivo

Predecir vehículos involucrados durante el mes siguiente para Tunja, Duitama y Sogamoso.

## Diseño de evaluación

- Validación expansiva mes a mes: enero de 2024 a diciembre de 2025.
- Prueba final no usada para elegir modelo: enero a agosto de 2026.
- Cada predicción usa exclusivamente valores observados en meses anteriores.
- Modelos comparados: mes anterior, promedio de tres meses, mismo mes del año anterior, Poisson, Random Forest y Gradient Boosting.
- Escenarios comparados: ceros tal como fueron publicados y ceros de Sogamoso tratados como faltantes con interpolación solo para construir rezagos.
- Se agregaron número de festivos y festivos en lunes por mes.
{detalle_clima}

## Resultado

- Modelo seleccionado en validación: **{ganador}**
- Mejor escenario con ceros publicados: **{publicado_mejor['MODELO']}**, WAPE {publicado_mejor['WAPE_PCT']:.2f}%
- MAE de validación: {ganador_desarrollo['MAE']:.2f}
- WAPE de validación: {ganador_desarrollo['WAPE_PCT']:.2f}%
- MAE en prueba 2026: {ganador_prueba['MAE']:.2f}
- WAPE en prueba 2026: {ganador_prueba['WAPE_PCT']:.2f}%

## Advertencias

- Sogamoso tiene {ceros_sogamoso} meses con cero registros; pueden ser ceros reales o falta de reporte.
- Los intervalos son empíricos y reflejan el error histórico, no una garantía probabilística formal.
- La evaluación es de un mes hacia adelante usando el último valor real disponible.
- El objetivo son vehículos involucrados, no accidentes únicos.
{advertencia_clima}
"""
    (args.salida / "reporte_entrenamiento.md").write_text(reporte, encoding="utf-8")

    print(f"Modelo seleccionado: {ganador}")
    print(f"Validación MAE={ganador_desarrollo['MAE']:.2f}, WAPE={ganador_desarrollo['WAPE_PCT']:.2f}%")
    print(f"Prueba 2026 MAE={ganador_prueba['MAE']:.2f}, WAPE={ganador_prueba['WAPE_PCT']:.2f}%")
    print(f"Resultados: {args.salida.resolve()}")


if __name__ == "__main__":
    main()
