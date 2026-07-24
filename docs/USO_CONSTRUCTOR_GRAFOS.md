# Constructor de grafos ICE v4.2.2

El constructor definitivo se encuentra en
`scripts/construir_grafo_ice.py` y utiliza `config.yaml` desde la raíz del
proyecto.

## Ejecución recomendada

```bash
python -m pip install -r requirements.txt
python scripts/construir_grafo_ice.py \
  --project-root . \
  --config config.yaml \
  --offline
```

Las salidas se escriben en `build/grafos_ice`; el constructor no borra ni
sobrescribe los resultados QAOA, notebooks o documentos finales.

Para ejecutar todo el proceso sin copiar archivos manualmente, use:

```bash
python scripts/ejecutar_entrega.py --modo completo
```

Ese punto de entrada reconstruye los grafos, copia automáticamente los doce
archivos canónicos a `datos/grafos/` y luego ejecuta los notebooks.

La ejecución predeterminada:

- usa los GeoJSON incluidos en `datos/crudos`;
- no consulta Internet;
- reconstruye aristas y pesos desde los datos ICE;
- conserva los conjuntos auditados de nodos G6/G8/G10/G12;
- ejecuta dos reconstrucciones en directorios vacíos y compara sus hashes;
- documenta que los cuatro grafos son árboles bipartitos;
- no añade aristas sintéticas.

## Prueba rápida

```bash
python scripts/construir_grafo_ice.py \
  --project-root . \
  --config config.yaml \
  --offline \
  --no-repro-check
```

## Validación sin evidencia visual

La versión 4.2.2 no requiere capturas de Escazú ni Alajuelita y no consulta
`manual_visual_overrides`. Los candidatos que exceden el umbral ordinario solo
se aceptan con confianza media si cumplen una regla general:

- misma parte continua de una geometría oficial;
- segmento real y estaciones consecutivas;
- ninguna estación intermedia;
- peso positivo;
- ajuste máximo de 250 m;
- razón recorrido/distancia directa máxima de 1,60;
- sin ramificaciones, cruces entre líneas o mezcla de regiones;
- un único candidato para el par.

Esta regla acepta Alajuelita–Escazú sin codificar sus nombres. La salida la
identifica como inferencia geoespacial sobre datos oficiales, nunca como
conectividad operativa certificada. Los límites pueden configurarse de forma
opcional con `validation.extended_geospatial_max_snap_m` y
`validation.extended_geospatial_max_detour_ratio`.

El bloque antiguo `validation.manual_visual_overrides` puede eliminarse de
`config.yaml`; si permanece, esta versión lo ignora.

## Opciones de red

`--online-verify` compara la caché local con el servicio ICE.
`--refresh-data` vuelve a descargar las capas. Ninguna de las dos opciones es
necesaria para la reproducción normal.

## Resultado validado

La prueba offline realizada sobre el ZIP v4.2 produjo:

| Grafo | Nodos | Aristas | Peso total | Max-Cut exacto |
|---|---:|---:|---:|---:|
| G6 | 6 | 5 | 38.301789578 | 38.301789578 |
| G8 | 8 | 7 | 42.218037148 | 42.218037148 |
| G10 | 10 | 9 | 87.075047828 | 87.075047828 |
| G12 | 12 | 11 | 93.299621336 | 93.299621336 |

Las cifras anteriores son la referencia que debe conservar la nueva prueba
offline. El reporte generado en
`build/grafos_ice/auditoria/reporte_reproducibilidad.md` contiene el conteo
actual de archivos y la comparación de hashes.
