# Quantathon CR 2026 · Challenge 1

Solución reproducible de Max-Cut ponderado sobre cuatro subgrafos reales de
la red de transmisión del ICE, usando QUBO, líneas base clásicas y QAOA con
Guppy.

## Estado verificable

- Región: Central.
- Instancias: G6, G8, G10 y G12.
- Profundidades QAOA: p=1, p=2 y p=3.
- Optimización: 6, 10 y 12 reinicios por profundidad, respectivamente.
- Variabilidad de optimización: 6, 10 y 12 inicializaciones para p=1, p=2 y
  p=3, respectivamente.
- Incertidumbre de muestreo complementaria: 30 lotes de 512 tiros del mismo
  estado optimizado para cada combinación de tamaño y profundidad.
- Guppy local: 12 configuraciones validadas con 512 tiros.
- SelenePlus: G6/G8/G10/G12, p=3, 512 tiros, con `HeliosRuntime` y
  `QSystemErrorModel(alpha)`.
- Resultado SelenePlus: cuatro grafos completados en un único trabajo remoto.
  No se presenta como ejecución en hardware físico.

## Punto único de entrada

La ruta recomendada regenera las seis figuras y las cuatro tablas desde los
resultados detallados incluidos, actualiza el manifiesto y valida la entrega:

```bash
python scripts/ejecutar_entrega.py
```

Para recalcular el flujo local desde los grafos y después regenerar todos los
productos finales:

```bash
python scripts/ejecutar_entrega.py --modo completo
```

Este modo reconstruye primero G6/G8/G10/G12 desde `datos/crudos/` mediante
`scripts/construir_grafo_ice.py`, publica automáticamente la salida canónica
en `datos/grafos/` y luego ejecuta y guarda los notebooks. `build/` es
únicamente un área temporal regenerable y no forma parte de la entrega.

La recuperación del trabajo SelenePlus existente es explícita y nunca habilita
un envío nuevo:

```bash
python scripts/ejecutar_entrega.py --modo completo --recuperar-seleneplus
```

También existe una comprobación rápida que no modifica resultados:

```bash
python scripts/ejecutar_entrega.py --modo validar
```

Para instalar:

```bash
python -m pip install -r requirements.txt
```

Los notebooks permanecen separados para facilitar la revisión técnica, pero el
script anterior es el punto de entrada reproducible.

## Estructura

- `datos/crudos/`: capas, catálogos y fuentes oficiales.
- `datos/grafos/`: G6/G8/G10/G12 en CSV y GraphML.
- `scripts/construir_grafo_ice.py`: constructor definitivo de los grafos.
- `resultados/clasicos/`: QUBO, exacto, greedy, recocido y GW.
- `resultados/qaoa_local/`: optimizaciones, mediciones y resúmenes.
- `resultados/remoto/`: evidencia SelenePlus separada.
- `resultados/tablas_finales/`: comparaciones de calidad, costo, ruido y
  robustez.
- `figuras/`: seis figuras finales, incluida la comparación directa entre
  simulación ideal y SelenePlus con ruido.
- `docs/`: auditoría, interpretación y guía de tiros.
- `build/`: salida temporal regenerable; se excluye del paquete final.

## Limitación central

Las cuatro instancias son árboles bipartitos con pesos positivos. Su Max-Cut
óptimo corta todas las aristas y coincide con la suma de pesos. Esto permite
validar con rigor el flujo QUBO/QAOA, pero no representa una instancia
clásicamente difícil y no respalda una afirmación de ventaja cuántica.

Por esta razón, la entrega no utiliza «la mejor solución observada» como
métrica principal: con 512 tiros esa medida se satura en 1.0. Se reportan la
calidad esperada, la probabilidad de óptimo por tiro, la variabilidad entre
reinicios y el intercambio entre profundidad y operaciones ZZ.

No se añadieron aristas artificiales: se priorizó la fidelidad a los datos del
ICE y la reproducibilidad.
