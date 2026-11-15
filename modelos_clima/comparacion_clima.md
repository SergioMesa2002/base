# Comparación del aporte de la precipitación

## Resultado

- Mejor modelo base en validación: **promedio_3_meses**, WAPE 36.17%.
- Mejor modelo con variables climáticas en validación: **random_forest**, WAPE 35.97%.
- Random Forest mejora 0.32 puntos de WAPE en validación.
- En la prueba 2026, Random Forest cambia de 35.52% a 35.58% de WAPE.
- El mejor resultado de prueba continúa siendo **promedio_3_meses**, con WAPE 30.80%.

## Decisión

La precipitación muestra una señal pequeña durante la validación, pero no una mejora estable en la prueba final. Por ahora no debe reemplazar al modelo base. Sí puede conservarse como variable experimental del simulador para construir escenarios, indicando que la relación estimada todavía es débil.

Un delta negativo en `comparacion_clima.csv` representa mejora; un delta positivo representa deterioro.
