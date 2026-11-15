# Reporte de precipitación

## Alcance

- Periodo: 2022-01 a 2026-10
- Municipios: Tunja, Duitama y Sogamoso
- Umbral para usar una medición en el modelo: 80%
- Archivo mensual: `precipitacion_mensual.csv`
- Serie combinada: `serie_mensual_con_clima.csv`

## Cobertura por municipio

```
MUNICIPIO  ESTADO_COBERTURA_CLIMA
DUITAMA    COMPLETA                  58
SOGAMOSO   COMPLETA                  58
TUNJA      ACEPTABLE                  8
           COMPLETA                  38
           INSUFICIENTE              12
```

## Estaciones seleccionadas

```
MUNICIPIO  ESTACION_CODIGO  ESTACION_NOMBRE          
DUITAMA    24030350         DUITAMA                      56
           24035120         SURBATA BONZA                 1
           24035350         ANDALUCIA                     1
SOGAMOSO   24030940         SENA                          7
           24035340         AEROPUERTO ALBERTO LLERAS    42
           35190010         LAS CINTAS                    9
TUNJA      2401500086       UPTC AUTOMATICA              13
           24035130         UPTC                         45
```

## Decisiones

- Cada mes usa la estación con mayor cobertura disponible dentro del municipio.
- En empates se conserva la estación prioritaria más cercana o representativa.
- Los duplicados exactos de fecha y valor de la estación automática se eliminan.
- Los meses por debajo de 80% conservan el valor bruto para auditoría, pero las variables destinadas al modelo quedan vacías.
- Los faltantes no se convierten en lluvia cero.
- La lluvia automática es preliminar y requiere las cautelas de calidad indicadas por el IDEAM.
