#!/usr/bin/env python3
"""Descarga una copia local reproducible de siniestros georreferenciados de ANSV."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL = (
    "https://srvansvargweb.ansv.gov.co/server/rest/services/Hosted/"
    "Datos_siniestros/FeatureServer/0/query"
)
MUNICIPIOS = {
    "TUNJA": "TUNJA (CT)",
    "DUITAMA": "DUITAMA",
    "SOGAMOSO": "SOGAMOSO",
}
CAMPOS = ",".join(
    [
        "fid",
        "hechos_id",
        "smuertos",
        "slesionado",
        "latitud",
        "longitud",
        "depto_hech",
        "municipio_",
        "fecha_hech",
        "sievi_clas",
        "hipotesis_",
        "medio_cono",
        "tvictimas",
        "lugaro",
    ]
)
SALIDA = (
    Path(__file__).resolve().parents[1]
    / "datos_externos"
    / "ansv"
    / "siniestros_tres_municipios.geojson"
)


def descargar(municipio_ansv: str) -> list[dict]:
    parametros = {
        "where": f"municipio_='{municipio_ansv}'",
        "outFields": CAMPOS,
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": "2000",
        "f": "geojson",
    }
    request = Request(
        f"{URL}?{urlencode(parametros)}",
        headers={"User-Agent": "Via-Segura-Boyaca/0.1"},
    )
    with urlopen(request, timeout=60) as response:
        contenido = json.load(response)
    if "error" in contenido:
        raise RuntimeError(contenido["error"])
    return contenido.get("features", [])


def fecha_iso(valor: object) -> str | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        return datetime.fromtimestamp(valor / 1000, tz=UTC).date().isoformat()
    return str(valor)[:10]


def normalizar(feature: dict, municipio: str) -> dict:
    propiedades = feature.get("properties", {})
    longitud = propiedades.get("longitud")
    latitud = propiedades.get("latitud")
    geometria = feature.get("geometry")
    if not geometria and longitud is not None and latitud is not None:
        geometria = {"type": "Point", "coordinates": [longitud, latitud]}
    return {
        "type": "Feature",
        "geometry": geometria,
        "properties": {
            "id": propiedades.get("hechos_id") or propiedades.get("fid"),
            "municipio": municipio,
            "fecha": fecha_iso(propiedades.get("fecha_hech")),
            "clase": propiedades.get("sievi_clas"),
            "fallecidos": propiedades.get("smuertos") or 0,
            "lesionados": propiedades.get("slesionado") or 0,
            "victimas": propiedades.get("tvictimas") or 0,
            "lugar": propiedades.get("lugaro"),
            "hipotesis": propiedades.get("hipotesis_"),
            "medio_conocimiento": propiedades.get("medio_cono"),
        },
    }


def main() -> None:
    features = []
    conteos = {}
    for municipio, nombre_ansv in MUNICIPIOS.items():
        descargados = descargar(nombre_ansv)
        normalizados = [normalizar(feature, municipio) for feature in descargados]
        normalizados = [feature for feature in normalizados if feature["geometry"]]
        features.extend(normalizados)
        conteos[municipio] = len(normalizados)

    fechas = sorted(
        feature["properties"]["fecha"]
        for feature in features
        if feature["properties"]["fecha"]
    )
    salida = {
        "type": "FeatureCollection",
        "metadata": {
            "fuente": "Agencia Nacional de Seguridad Vial (ANSV)",
            "servicio": URL.rsplit("/query", 1)[0],
            "descargado": datetime.now(tz=UTC).isoformat(),
            "fecha_inicial": fechas[0] if fechas else None,
            "fecha_final": fechas[-1] if fechas else None,
            "conteos": conteos,
            "advertencia": "Los puntos describen siniestros históricos, no probabilidades futuras.",
        },
        "features": features,
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(
        json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Archivo: {SALIDA}")
    print(f"Registros: {len(features)} · {conteos}")
    print(f"Periodo: {salida['metadata']['fecha_inicial']} a {salida['metadata']['fecha_final']}")


if __name__ == "__main__":
    main()
