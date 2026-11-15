# Vía Segura Boyacá

Aplicación FastAPI para consultar el pronóstico mensual de vehículos involucrados
y explorar siniestros históricos georreferenciados en Tunja, Duitama y Sogamoso.

## Ejecutar la aplicación

Desde la carpeta del proyecto:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Abrir <http://127.0.0.1:8000>. La documentación automática de la API queda en
<http://127.0.0.1:8000/docs>.

## Actualizar los siniestros de ANSV

La aplicación usa una copia local para que la API oficial no sea consultada cada
vez que se abre el mapa:

```bash
.venv/bin/python scripts/descargar_siniestros_ansv.py
```

El mapa base de OpenStreetMap y las bibliotecas Leaflet se cargan por internet.
Los puntos descargados actualmente cubren del 1 de enero al 12 de agosto de 2019.
Representan concentración histórica y no una probabilidad futura por cruce.

## Endpoints principales

- `GET /api/salud`
- `GET /api/siniestros`
- `GET /api/siniestros?municipio=TUNJA`
- `GET /api/siniestros/resumen`
- `POST /api/simular` con municipio, precipitación mensual, días con lluvia y
  precipitación máxima diaria.
- `POST /api/proyectar` genera septiembre–diciembre de 2026 mediante proyección
  recursiva mensual para el modelo principal o el climático.

Las bandas de octubre a diciembre son exploratorias: amplían el margen empírico
de un mes con la raíz del horizonte. Aún no sustituyen una validación histórica
multipaso.
