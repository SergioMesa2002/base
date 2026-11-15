"""API y servidor web para el panel Vía Segura Boyacá."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from scripts.limpiar_dataset import festivos_colombia


BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BASE_DIR / "visualizations"
SINIESTROS_PATH = (
    BASE_DIR / "datos_externos" / "ansv" / "siniestros_tres_municipios.geojson"
)
MUNICIPIOS = {"TUNJA", "DUITAMA", "SOGAMOSO"}
MODELO_CLIMA_PATH = BASE_DIR / "modelos_clima" / "modelo_ml_seleccionado.joblib"
CONFIG_CLIMA_PATH = BASE_DIR / "modelos_clima" / "modelo_seleccionado.json"
CONFIG_BASE_PATH = BASE_DIR / "modelos" / "modelo_seleccionado.json"
SERIE_CLIMA_PATH = BASE_DIR / "datos_procesados" / "serie_mensual_con_clima.csv"
PRONOSTICO_CLIMA_PATH = BASE_DIR / "modelos_clima" / "pronostico_siguiente_mes.csv"

app = FastAPI(
    title="Vía Segura Boyacá API",
    description="Pronóstico municipal y consulta de siniestros georreferenciados.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class EscenarioClimatico(BaseModel):
    municipio: str
    precipitacion_mm: float = Field(ge=0, le=500)
    dias_con_lluvia: float = Field(ge=0, le=31)
    precipitacion_max_dia: float = Field(ge=0, le=250)

    @model_validator(mode="after")
    def validar_escenario(self) -> "EscenarioClimatico":
        self.municipio = self.municipio.upper().strip()
        if self.municipio not in MUNICIPIOS:
            raise ValueError("Municipio no soportado")
        if self.precipitacion_max_dia > self.precipitacion_mm:
            raise ValueError(
                "La precipitación máxima diaria no puede superar el acumulado mensual"
            )
        if self.precipitacion_mm == 0 and self.dias_con_lluvia > 0:
            raise ValueError("Un mes sin precipitación no puede tener días con lluvia")
        if self.dias_con_lluvia == 0 and self.precipitacion_mm > 0:
            raise ValueError("Un mes con precipitación debe tener al menos un día de lluvia")
        return self


class EscenarioMensual(BaseModel):
    fecha: date
    precipitacion_mm: float = Field(ge=0, le=500)
    dias_con_lluvia: float = Field(ge=0, le=31)
    precipitacion_max_dia: float = Field(ge=0, le=250)

    @model_validator(mode="after")
    def validar_factores(self) -> "EscenarioMensual":
        if self.precipitacion_max_dia > self.precipitacion_mm:
            raise ValueError(
                "La precipitación máxima diaria no puede superar el acumulado mensual"
            )
        if (self.precipitacion_mm == 0) != (self.dias_con_lluvia == 0):
            raise ValueError(
                "Precipitación y días con lluvia deben ser ambos cero o ambos positivos"
            )
        return self


class SolicitudProyeccion(BaseModel):
    municipio: str
    modelo: Literal["principal", "clima"]
    escenarios: list[EscenarioMensual] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validar_solicitud(self) -> "SolicitudProyeccion":
        self.municipio = self.municipio.upper().strip()
        if self.municipio not in MUNICIPIOS:
            raise ValueError("Municipio no soportado")
        fechas = [escenario.fecha for escenario in self.escenarios]
        if len(fechas) != len(set(fechas)):
            raise ValueError("No se permiten escenarios repetidos para el mismo mes")
        return self


@lru_cache(maxsize=1)
def cargar_siniestros() -> dict:
    if not SINIESTROS_PATH.exists():
        raise FileNotFoundError(
            "No existe la copia local de ANSV. Ejecute scripts/descargar_siniestros_ansv.py"
        )
    return json.loads(SINIESTROS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def cargar_componentes_simulador() -> tuple[object, dict, pd.DataFrame, pd.DataFrame]:
    modelo = joblib.load(MODELO_CLIMA_PATH)
    configuracion = json.loads(CONFIG_CLIMA_PATH.read_text(encoding="utf-8"))
    serie = pd.read_csv(SERIE_CLIMA_PATH, parse_dates=["FECHA_MES"])
    pronostico = pd.read_csv(PRONOSTICO_CLIMA_PATH, parse_dates=["FECHA_MES"])

    serie["VALOR_AJUSTADO"] = serie["REGISTROS_TOTAL"].astype(float)
    serie.loc[
        serie["ESTADO_COBERTURA"].eq("CERO_SOSPECHOSO"), "VALOR_AJUSTADO"
    ] = np.nan
    serie["VALOR_AJUSTADO"] = serie.groupby("MUNICIPIO")[
        "VALOR_AJUSTADO"
    ].transform(lambda valores: valores.interpolate(method="linear", limit_direction="both"))
    return modelo, configuracion, serie, pronostico


def construir_fila_futura(
    serie: pd.DataFrame,
    escenario: EscenarioClimatico,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    historial = serie[serie["MUNICIPIO"].eq(escenario.municipio)].sort_values(
        "FECHA_MES"
    )
    if historial.empty:
        raise HTTPException(status_code=404, detail="No existe historia para el municipio")

    siguiente_fecha = serie["FECHA_MES"].max() + pd.offsets.MonthBegin(1)
    numero_mes = siguiente_fecha.month
    festivos_mes = {
        festivo
        for festivo in festivos_colombia(siguiente_fecha.year)
        if festivo.month == numero_mes
    }
    valores = historial["VALOR_AJUSTADO"]
    origen = serie["FECHA_MES"].min()
    tendencia = (
        (siguiente_fecha.year - origen.year) * 12
        + siguiente_fecha.month
        - origen.month
    )
    fila = pd.DataFrame(
        [
            {
                "MUNICIPIO": escenario.municipio,
                "MES_SIN": np.sin(2 * np.pi * numero_mes / 12),
                "MES_COS": np.cos(2 * np.pi * numero_mes / 12),
                "TENDENCIA_TIEMPO": tendencia,
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
                "PRECIPITACION_MM": escenario.precipitacion_mm,
                "DIAS_CON_LLUVIA": escenario.dias_con_lluvia,
                "PRECIPITACION_MAX_DIA": escenario.precipitacion_max_dia,
            }
        ]
    )
    return fila, siguiente_fecha


def construir_fila_recursiva(
    serie: pd.DataFrame,
    municipio: str,
    fecha: pd.Timestamp,
    valores: list[float],
    escenario: EscenarioMensual,
) -> pd.DataFrame:
    festivos_mes = {
        festivo for festivo in festivos_colombia(fecha.year) if festivo.month == fecha.month
    }
    origen = serie["FECHA_MES"].min()
    tendencia = (fecha.year - origen.year) * 12 + fecha.month - origen.month
    return pd.DataFrame(
        [
            {
                "MUNICIPIO": municipio,
                "MES_SIN": np.sin(2 * np.pi * fecha.month / 12),
                "MES_COS": np.cos(2 * np.pi * fecha.month / 12),
                "TENDENCIA_TIEMPO": tendencia,
                "DIAS_FESTIVOS": len(festivos_mes),
                "FESTIVOS_EN_LUNES": sum(
                    festivo.weekday() == 0 for festivo in festivos_mes
                ),
                "LAG_1": valores[-1],
                "LAG_2": valores[-2],
                "LAG_3": valores[-3],
                "PROMEDIO_3": float(np.mean(valores[-3:])),
                "PROMEDIO_6": float(np.mean(valores[-6:])),
                "LAG_12": valores[-12],
                "PRECIPITACION_MM": escenario.precipitacion_mm,
                "DIAS_CON_LLUVIA": escenario.dias_con_lluvia,
                "PRECIPITACION_MAX_DIA": escenario.precipitacion_max_dia,
            }
        ]
    )


def escenario_tipico(
    serie: pd.DataFrame,
    municipio: str,
    fecha: pd.Timestamp,
) -> EscenarioMensual:
    historia = serie[
        serie["MUNICIPIO"].eq(municipio) & serie["FECHA_MES"].dt.month.eq(fecha.month)
    ]
    valores = {
        "precipitacion_mm": float(historia["PRECIPITACION_MM"].median()),
        "dias_con_lluvia": float(historia["DIAS_CON_LLUVIA"].median()),
        "precipitacion_max_dia": float(historia["PRECIPITACION_MAX_DIA"].median()),
    }
    if not all(np.isfinite(valor) for valor in valores.values()):
        raise HTTPException(
            status_code=422,
            detail=f"No hay clima histórico suficiente para {municipio} en el mes {fecha.month}",
        )
    return EscenarioMensual(fecha=fecha.date(), **valores)


def nivel_horizonte(paso: int) -> tuple[str, str]:
    niveles = {
        1: ("mayor", "Usa observaciones reales hasta agosto de 2026."),
        2: ("media-alta", "Depende de una predicción mensual anterior."),
        3: ("media", "Depende de dos predicciones mensuales anteriores."),
        4: ("menor", "Depende de tres predicciones mensuales anteriores."),
    }
    return niveles[paso]


def interpretar_escenario(
    modelo: object,
    fila_base: pd.DataFrame,
    prediccion_base: float,
    prediccion: float,
    escenario: EscenarioClimatico,
    escenario_base: EscenarioClimatico,
) -> dict:
    factores = [
        (
            "precipitacion_mm",
            "Precipitación mensual",
            "PRECIPITACION_MM",
            escenario.precipitacion_mm,
            escenario_base.precipitacion_mm,
        ),
        (
            "dias_con_lluvia",
            "Días con lluvia",
            "DIAS_CON_LLUVIA",
            escenario.dias_con_lluvia,
            escenario_base.dias_con_lluvia,
        ),
        (
            "precipitacion_max_dia",
            "Máxima diaria",
            "PRECIPITACION_MAX_DIA",
            escenario.precipitacion_max_dia,
            escenario_base.precipitacion_max_dia,
        ),
    ]
    efectos = []
    for clave, etiqueta, columna, valor, valor_base in factores:
        fila_aislada = fila_base.copy()
        fila_aislada.loc[0, columna] = valor
        prediccion_aislada = max(0.0, float(modelo.predict(fila_aislada)[0]))
        efecto = prediccion_aislada - prediccion_base
        efectos.append(
            {
                "factor": clave,
                "etiqueta": etiqueta,
                "valor": valor,
                "valor_base": valor_base,
                "efecto_aislado": round(efecto, 3),
            }
        )

    cambio = prediccion - prediccion_base
    cambio_absoluto = abs(cambio)
    if cambio_absoluto < 0.25:
        magnitud = "mínimo"
        resumen = "El escenario prácticamente no cambia la estimación frente al clima típico."
    elif cambio_absoluto < 1:
        magnitud = "pequeño"
        sentido = "aumenta" if cambio > 0 else "disminuye"
        resumen = f"El escenario {sentido} ligeramente la estimación frente al clima típico."
    elif cambio_absoluto < 3:
        magnitud = "moderado"
        sentido = "aumenta" if cambio > 0 else "disminuye"
        resumen = f"El escenario {sentido} de forma moderada la estimación frente al clima típico."
    else:
        magnitud = "notable"
        sentido = "aumenta" if cambio > 0 else "disminuye"
        resumen = f"El escenario {sentido} de forma notable la estimación frente al clima típico."

    factor_mayor = max(efectos, key=lambda item: abs(item["efecto_aislado"]))
    if abs(factor_mayor["efecto_aislado"]) < 0.05:
        factor_destacado = "Ningún factor aislado produjo un cambio apreciable."
    else:
        direccion = "al alza" if factor_mayor["efecto_aislado"] > 0 else "a la baja"
        factor_destacado = (
            f"El mayor cambio aislado provino de {factor_mayor['etiqueta'].lower()} "
            f"y fue {direccion}."
        )
    return {
        "resumen": resumen,
        "magnitud": magnitud,
        "factor_destacado": factor_destacado,
        "efectos_individuales": efectos,
        "metodo": (
            "Cada efecto cambia un solo factor respecto al escenario típico. "
            "Es una prueba de sensibilidad del modelo, no un escenario meteorológico "
            "independiente. Los efectos no se suman porque el Random Forest incluye "
            "interacciones."
        ),
        "cautela": (
            "Describe asociaciones aprendidas por el modelo; no demuestra que la lluvia "
            "cause el cambio estimado."
        ),
    }


@app.get("/", include_in_schema=False)
def inicio() -> FileResponse:
    return FileResponse(WEB_DIR / "simulador-riesgo-vial.html")


@app.get("/api/salud", tags=["sistema"])
def salud() -> dict:
    try:
        cantidad = len(cargar_siniestros()["features"])
    except FileNotFoundError:
        cantidad = 0
    return {"estado": "ok", "siniestros_disponibles": cantidad}


@app.post("/api/simular", tags=["predicción"])
def simular(escenario: EscenarioClimatico) -> dict:
    modelo, configuracion, serie, pronostico = cargar_componentes_simulador()
    fila, fecha = construir_fila_futura(serie, escenario)
    prediccion = max(0.0, float(modelo.predict(fila)[0]))
    margen = float(
        configuracion["margen_por_municipio"].get(
            escenario.municipio,
            configuracion["margen_por_municipio"]["GLOBAL"],
        )
    )
    base = pronostico[pronostico["MUNICIPIO"].eq(escenario.municipio)].iloc[0]
    escenario_base = EscenarioClimatico(
        municipio=escenario.municipio,
        precipitacion_mm=float(base["PRECIPITACION_MM"]),
        dias_con_lluvia=float(base["DIAS_CON_LLUVIA"]),
        precipitacion_max_dia=float(base["PRECIPITACION_MAX_DIA"]),
    )
    fila_base, _ = construir_fila_futura(serie, escenario_base)
    prediccion_base = max(0.0, float(modelo.predict(fila_base)[0]))
    interpretacion = interpretar_escenario(
        modelo,
        fila_base,
        prediccion_base,
        prediccion,
        escenario,
        escenario_base,
    )
    return {
        "fecha": fecha.date().isoformat(),
        "municipio": escenario.municipio,
        "modelo": configuracion["modelo_seleccionado"],
        "prediccion": round(prediccion, 3),
        "limite_inferior": round(max(0.0, prediccion - margen), 3),
        "limite_superior": round(prediccion + margen, 3),
        "prediccion_base": round(prediccion_base, 3),
        "cambio_absoluto": round(prediccion - prediccion_base, 3),
        "factores": {
            "precipitacion_mm": escenario.precipitacion_mm,
            "dias_con_lluvia": escenario.dias_con_lluvia,
            "precipitacion_max_dia": escenario.precipitacion_max_dia,
        },
        "interpretacion": interpretacion,
        "advertencia": (
            "Escenario experimental: la señal climática no mejoró de forma estable "
            "al modelo principal en la prueba final."
        ),
    }


@app.post("/api/proyectar", tags=["predicción"])
def proyectar(solicitud: SolicitudProyeccion) -> dict:
    modelo_clima, config_clima, serie, _ = cargar_componentes_simulador()
    config_base = json.loads(CONFIG_BASE_PATH.read_text(encoding="utf-8"))
    historial = serie[serie["MUNICIPIO"].eq(solicitud.municipio)].sort_values(
        "FECHA_MES"
    )
    valores = historial["VALOR_AJUSTADO"].astype(float).tolist()
    primera_fecha = serie["FECHA_MES"].max() + pd.offsets.MonthBegin(1)
    fechas_permitidas = [
        (primera_fecha + pd.offsets.MonthBegin(paso)).date() for paso in range(4)
    ]
    overrides = {escenario.fecha: escenario for escenario in solicitud.escenarios}
    fechas_invalidas = sorted(set(overrides) - set(fechas_permitidas))
    if fechas_invalidas:
        raise HTTPException(
            status_code=422,
            detail="Los escenarios deben estar entre septiembre y diciembre de 2026",
        )

    configuracion = config_clima if solicitud.modelo == "clima" else config_base
    margen_base = float(
        configuracion["margen_por_municipio"].get(
            solicitud.municipio,
            configuracion["margen_por_municipio"]["GLOBAL"],
        )
    )
    proyecciones = []
    for indice, fecha_date in enumerate(fechas_permitidas, start=1):
        fecha = pd.Timestamp(fecha_date)
        nivel, detalle_nivel = nivel_horizonte(indice)
        interpretacion = None
        factores = None
        cambio_escenario = None
        if solicitud.modelo == "principal":
            prediccion = max(0.0, float(np.mean(valores[-3:])))
        else:
            tipico = escenario_tipico(serie, solicitud.municipio, fecha)
            escenario = overrides.get(fecha_date, tipico)
            fila = construir_fila_recursiva(
                serie, solicitud.municipio, fecha, valores, escenario
            )
            prediccion = max(0.0, float(modelo_clima.predict(fila)[0]))
            fila_base = construir_fila_recursiva(
                serie, solicitud.municipio, fecha, valores, tipico
            )
            prediccion_base = max(0.0, float(modelo_clima.predict(fila_base)[0]))
            cambio_escenario = round(prediccion - prediccion_base, 3)
            interpretacion = interpretar_escenario(
                modelo_clima,
                fila_base,
                prediccion_base,
                prediccion,
                EscenarioClimatico(
                    municipio=solicitud.municipio,
                    precipitacion_mm=escenario.precipitacion_mm,
                    dias_con_lluvia=escenario.dias_con_lluvia,
                    precipitacion_max_dia=escenario.precipitacion_max_dia,
                ),
                EscenarioClimatico(
                    municipio=solicitud.municipio,
                    precipitacion_mm=tipico.precipitacion_mm,
                    dias_con_lluvia=tipico.dias_con_lluvia,
                    precipitacion_max_dia=tipico.precipitacion_max_dia,
                ),
            )
            factores = {
                "precipitacion_mm": escenario.precipitacion_mm,
                "dias_con_lluvia": escenario.dias_con_lluvia,
                "precipitacion_max_dia": escenario.precipitacion_max_dia,
            }

        # Ampliación exploratoria: aún no es un intervalo calibrado por horizonte.
        margen = margen_base * np.sqrt(indice)
        proyecciones.append(
            {
                "fecha": fecha_date.isoformat(),
                "paso": indice,
                "prediccion": round(prediccion, 3),
                "limite_inferior": round(max(0.0, prediccion - margen), 3),
                "limite_superior": round(prediccion + margen, 3),
                "confiabilidad_relativa": nivel,
                "detalle_confiabilidad": detalle_nivel,
                "factores": factores,
                "cambio_escenario": cambio_escenario,
                "interpretacion": interpretacion,
            }
        )
        valores.append(prediccion)

    return {
        "municipio": solicitud.municipio,
        "modelo": solicitud.modelo,
        "metodo": "Proyección recursiva mensual",
        "banda": (
            "Banda exploratoria: margen empírico de un mes multiplicado por la raíz "
            "del horizonte. No está calibrada todavía con validación multipaso."
        ),
        "proyecciones": proyecciones,
    }


@app.get("/api/siniestros", tags=["siniestros"])
def siniestros(
    municipio: str | None = Query(
        default=None,
        description="TUNJA, DUITAMA o SOGAMOSO. Sin valor devuelve los tres.",
    ),
) -> dict:
    try:
        fuente = cargar_siniestros()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    municipio_normalizado = municipio.upper().strip() if municipio else None
    if municipio_normalizado and municipio_normalizado not in MUNICIPIOS:
        raise HTTPException(status_code=400, detail="Municipio no soportado")

    features = fuente["features"]
    if municipio_normalizado:
        features = [
            feature
            for feature in features
            if feature["properties"]["municipio"] == municipio_normalizado
        ]
    return {
        "type": "FeatureCollection",
        "metadata": fuente.get("metadata", {}),
        "features": features,
    }


@app.get("/api/siniestros/resumen", tags=["siniestros"])
def resumen_siniestros() -> dict:
    try:
        features = cargar_siniestros()["features"]
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    por_municipio = Counter(
        feature["properties"]["municipio"] for feature in features
    )
    por_clase = Counter(
        feature["properties"].get("clase") or "SIN INFORMACIÓN"
        for feature in features
    )
    fechas = sorted(
        feature["properties"]["fecha"]
        for feature in features
        if feature["properties"].get("fecha")
    )
    return {
        "total": len(features),
        "por_municipio": dict(sorted(por_municipio.items())),
        "por_clase": dict(por_clase.most_common()),
        "fecha_inicial": fechas[0] if fechas else None,
        "fecha_final": fechas[-1] if fechas else None,
        "interpretacion": "Concentración histórica; no es una probabilidad futura.",
    }
