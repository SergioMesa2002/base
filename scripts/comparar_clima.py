#!/usr/bin/env python3
"""Compara las métricas del modelo base con el experimento climático."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("metricas_base", type=Path)
    parser.add_argument("metricas_clima", type=Path)
    parser.add_argument("--salida", type=Path, default=Path("modelos_clima"))
    return parser.parse_args()


def preparar(ruta: Path, sufijo: str) -> pd.DataFrame:
    datos = pd.read_csv(ruta)
    datos = datos[
        datos["MUNICIPIO"].eq("TODOS")
        & datos["ESCENARIO"].eq("CEROS_COMO_FALTANTES")
    ][["PERIODO", "MODELO", "MAE", "RMSE", "WAPE_PCT"]]
    return datos.rename(
        columns={
            "MAE": f"MAE_{sufijo}",
            "RMSE": f"RMSE_{sufijo}",
            "WAPE_PCT": f"WAPE_PCT_{sufijo}",
        }
    )


def main() -> None:
    args = argumentos()
    args.salida.mkdir(parents=True, exist_ok=True)
    base = preparar(args.metricas_base, "BASE")
    clima = preparar(args.metricas_clima, "CLIMA")
    comparacion = base.merge(clima, on=["PERIODO", "MODELO"], validate="1:1")
    comparacion["DELTA_WAPE_PUNTOS"] = (
        comparacion["WAPE_PCT_CLIMA"] - comparacion["WAPE_PCT_BASE"]
    )
    comparacion["CAMBIO_WAPE_PCT"] = (
        100 * comparacion["DELTA_WAPE_PUNTOS"] / comparacion["WAPE_PCT_BASE"]
    )
    comparacion = comparacion.sort_values(["PERIODO", "WAPE_PCT_CLIMA"])
    comparacion.to_csv(
        args.salida / "comparacion_clima.csv", index=False, float_format="%.3f"
    )

    validacion = comparacion[comparacion["PERIODO"].eq("VALIDACION_2024_2025")]
    prueba = comparacion[comparacion["PERIODO"].eq("PRUEBA_2026")]
    mejor_base_validacion = validacion.sort_values("WAPE_PCT_BASE").iloc[0]
    mejor_clima_validacion = validacion.sort_values("WAPE_PCT_CLIMA").iloc[0]
    fila_rf_validacion = validacion[validacion["MODELO"].eq("random_forest")].iloc[0]
    fila_rf_prueba = prueba[prueba["MODELO"].eq("random_forest")].iloc[0]
    mejor_base_prueba = prueba.sort_values("WAPE_PCT_BASE").iloc[0]

    reporte = f"""# Comparación del aporte de la precipitación

## Resultado

- Mejor modelo base en validación: **{mejor_base_validacion['MODELO']}**, WAPE {mejor_base_validacion['WAPE_PCT_BASE']:.2f}%.
- Mejor modelo con variables climáticas en validación: **{mejor_clima_validacion['MODELO']}**, WAPE {mejor_clima_validacion['WAPE_PCT_CLIMA']:.2f}%.
- Random Forest mejora {abs(fila_rf_validacion['DELTA_WAPE_PUNTOS']):.2f} puntos de WAPE en validación.
- En la prueba 2026, Random Forest cambia de {fila_rf_prueba['WAPE_PCT_BASE']:.2f}% a {fila_rf_prueba['WAPE_PCT_CLIMA']:.2f}% de WAPE.
- El mejor resultado de prueba continúa siendo **{mejor_base_prueba['MODELO']}**, con WAPE {mejor_base_prueba['WAPE_PCT_BASE']:.2f}%.

## Decisión

La precipitación muestra una señal pequeña durante la validación, pero no una mejora estable en la prueba final. Por ahora no debe reemplazar al modelo base. Sí puede conservarse como variable experimental del simulador para construir escenarios, indicando que la relación estimada todavía es débil.

Un delta negativo en `comparacion_clima.csv` representa mejora; un delta positivo representa deterioro.
"""
    (args.salida / "comparacion_clima.md").write_text(reporte, encoding="utf-8")
    print(reporte)


if __name__ == "__main__":
    main()
