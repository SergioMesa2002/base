# Reporte del primer entrenamiento

## Objetivo

Predecir vehículos involucrados durante el mes siguiente para Tunja, Duitama y Sogamoso.

## Diseño de evaluación

- Validación expansiva mes a mes: enero de 2024 a diciembre de 2025.
- Prueba final no usada para elegir modelo: enero a agosto de 2026.
- Cada predicción usa exclusivamente valores observados en meses anteriores.
- Modelos comparados: mes anterior, promedio de tres meses, mismo mes del año anterior, Poisson, Random Forest y Gradient Boosting.
- Escenarios comparados: ceros tal como fueron publicados y ceros de Sogamoso tratados como faltantes con interpolación solo para construir rezagos.
- Se agregaron número de festivos y festivos en lunes por mes.
- Se incorporaron precipitación mensual, días con lluvia y máxima diaria.
- Para el pronóstico futuro sin un parte meteorológico se usa la mediana histórica del mismo municipio y mes.

## Resultado

- Modelo seleccionado en validación: **random_forest**
- Mejor escenario con ceros publicados: **random_forest**, WAPE 37.72%
- MAE de validación: 5.71
- WAPE de validación: 35.97%
- MAE en prueba 2026: 5.85
- WAPE en prueba 2026: 35.58%

## Advertencias

- Sogamoso tiene 11 meses con cero registros; pueden ser ceros reales o falta de reporte.
- Los intervalos son empíricos y reflejan el error histórico, no una garantía probabilística formal.
- La evaluación es de un mes hacia adelante usando el último valor real disponible.
- El objetivo son vehículos involucrados, no accidentes únicos.
- La lluvia del mes evaluado se trata como un factor de escenario conocido. Para una predicción previa al mes debe suministrarse un pronóstico de lluvia o una hipótesis del simulador.
