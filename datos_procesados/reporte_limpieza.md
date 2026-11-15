# Reporte de limpieza

## Alcance

- Fuente: `VEHICULOS_INVOLUCRADOS_EN_UN_ACCIDENTE_DE_TRANSITO_LEY_2251-2022_20261113.csv`
- Zona: Tunja, Duitama y Sogamoso
- Periodo conservado: 2022-01 a 2026-08
- Unidad: vehículos involucrados, no accidentes únicos

## Resultados

- Filas leídas: 450,335
- Filas de Boyacá: 5,277
- Filas encontradas en la zona: 2,428
- Filas limpias exportadas: 2,428
- Fechas inválidas descartadas: 0
- Filas fuera del periodo descartadas: 0
- Modelos de vehículo inválidos: 0
- Modelos posteriores al año del accidente: 49
- Edades reportadas vacías o mal formadas: 0
- Repeticiones exactas adicionales detectadas: 42
- Meses por municipio en la serie completa: 56
- Filas de la serie mensual: 168
- Ceros sospechosos marcados en Sogamoso: 11

## Decisiones

- El CSV original no fue modificado.
- Las repeticiones exactas no se eliminaron porque no existe un identificador de accidente o vehículo.
- `ANTIGUEDAD_MODELO_AL_ACCIDENTE` se calculó como `ANIO - MODELO_VEHICULO`; es una aproximación basada en el año-modelo, no la edad real desde la matrícula.
- La edad original se conserva como `EDAD_REPORTADA`, pero no debe usarse como variable principal.
- Los meses sin registros se incluyen con cero para mantener una serie temporal continua. Esto supone cobertura administrativa completa y debe validarse con la fuente.
- Los ceros de Sogamoso se marcan como `CERO_SOSPECHOSO` para permitir una evaluación alternativa tratándolos como datos faltantes.
- Se agregan festivos nacionales mensuales calculados según la Ley 51 de 1983.
- El corte final se determina con el último mes realmente observado en la zona, no con el último mes del archivo nacional.
