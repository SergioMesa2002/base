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

## Resultado

- Modelo seleccionado en validación: **promedio_3_meses**
- Mejor escenario con ceros publicados: **promedio_3_meses**, WAPE 37.75%
- MAE de validación: 5.74
- WAPE de validación: 36.17%
- MAE en prueba 2026: 5.07
- WAPE en prueba 2026: 30.80%

## Advertencias

- Sogamoso tiene 11 meses con cero registros; pueden ser ceros reales o falta de reporte.
- Los intervalos son empíricos y reflejan el error histórico, no una garantía probabilística formal.
- La evaluación es de un mes hacia adelante usando el último valor real disponible.
- El objetivo son vehículos involucrados, no accidentes únicos.
