# Quantathon CR 2026 · Challenge 1

Solución reproducible de Max-Cut ponderado sobre cuatro subgrafos derivados de
datos geoespaciales oficiales de la red de transmisión del Instituto
Costarricense de Electricidad (ICE), utilizando QUBO, líneas base clásicas y
QAOA con Guppy.

Repositorio oficial:
[noir-technologies/quantathon2026-noir-powergrid](https://github.com/noir-technologies/quantathon2026-noir-powergrid)

## Estado verificable

- Región analizada: Central.
- Instancias: G6, G8, G10 y G12.
- Profundidades QAOA: `p=1`, `p=2` y `p=3`.
- Inicializaciones del optimizador: 6, 10 y 12 para `p=1`, `p=2` y `p=3`,
  respectivamente.
- Incertidumbre de muestreo: 30 lotes de 512 tiros del mismo estado optimizado
  para cada combinación de tamaño y profundidad.
- Guppy local: 12 configuraciones validadas con 512 tiros.
- SelenePlus: G6, G8, G10 y G12 con `p=3`, 512 tiros,
  `HeliosRuntime` y `QSystemErrorModel(alpha)`.
- Los cuatro grafos se ejecutaron en un único trabajo remoto.
- SelenePlus se utiliza como backend de emulación; los resultados no se
  presentan como una ejecución en hardware cuántico físico.

## Cómo obtener el proyecto desde GitHub

### Opción 1: clonar el repositorio con Git

Esta opción es la recomendada porque permite descargar futuras actualizaciones.

```bash
git clone https://github.com/noir-technologies/quantathon2026-noir-powergrid.git
cd quantathon2026-noir-powergrid
```

Para actualizar posteriormente una copia local:

```bash
git switch main
git pull origin main
```

Antes de ejecutar `git pull`, se recomienda guardar o confirmar cualquier
cambio local para evitar conflictos.

### Opción 2: descargar un archivo ZIP

1. Abrir el
   [repositorio en GitHub](https://github.com/noir-technologies/quantathon2026-noir-powergrid).
2. Seleccionar **Code**.
3. Seleccionar **Download ZIP**.
4. Descomprimir el archivo.
5. Abrir una terminal dentro de la carpeta descomprimida.

La descarga ZIP permite ejecutar el proyecto, pero no incluye el historial de
Git ni facilita la instalación de actualizaciones mediante `git pull`.

## Requisitos

- Git, si se utiliza la opción de clonación.
- Python 3.11.
- Un entorno capaz de instalar las dependencias de `requirements.txt`.
- Acceso y credenciales de Quantinuum Nexus únicamente para operaciones remotas
  autorizadas.

La validación local y la regeneración de productos a partir de los resultados
incluidos no requieren enviar un nuevo trabajo remoto.

## Instalación

Se recomienda utilizar un entorno virtual.

### macOS o Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Ejecución recomendada

El proyecto utiliza un único punto de entrada:

```bash
python scripts/ejecutar_entrega.py
```

Este comando regenera las seis figuras y las cuatro tablas a partir de los
resultados detallados incluidos, actualiza el manifiesto y valida la entrega.

### Validación rápida

Para comprobar la integridad de la entrega sin recalcular los experimentos:

```bash
python scripts/ejecutar_entrega.py --modo validar
```

### Reconstrucción completa del flujo local

Para reconstruir los grafos desde los datos crudos, ejecutar el flujo local y
regenerar los productos finales:

```bash
python scripts/ejecutar_entrega.py --modo completo
```

Este modo:

1. reconstruye G6, G8, G10 y G12 desde `datos/crudos/`;
2. publica la salida canónica en `datos/grafos/`;
3. ejecuta y guarda los notebooks correspondientes;
4. regenera las tablas, figuras y validaciones.

La carpeta `build/` es un área temporal regenerable y no forma parte de la
entrega final.

### Recuperación del trabajo remoto existente

La recuperación del trabajo SelenePlus existente debe habilitarse
explícitamente:

```bash
python scripts/ejecutar_entrega.py --modo completo --recuperar-seleneplus
```

Esta opción recupera el trabajo registrado y no habilita el envío automático
de un nuevo experimento remoto.

## Uso de GitHub para colaborar

Para proponer cambios sin modificar directamente la rama principal:

1. Crear un **fork** desde la página del repositorio.
2. Clonar el fork.
3. Crear una rama descriptiva.
4. Confirmar y publicar los cambios.
5. Abrir un **Pull Request** hacia el repositorio original.

Ejemplo:

```bash
git clone https://github.com/USUARIO/quantathon2026-noir-powergrid.git
cd quantathon2026-noir-powergrid
git switch -c mejora-documentacion

# Después de modificar y validar los archivos:
git status
git add README.md
git commit -m "Mejora las instrucciones de uso"
git push -u origin mejora-documentacion
```

Después del `push`, GitHub mostrará la opción para crear el Pull Request.

Los errores reproducibles, preguntas técnicas y propuestas también pueden
documentarse en la sección **Issues** del repositorio. Se recomienda incluir:

- sistema operativo y versión de Python;
- comando ejecutado;
- mensaje de error completo;
- pasos mínimos para reproducir el problema;
- confirmación de si se utilizó simulación local o recuperación remota.

No deben publicarse tokens, credenciales de Nexus, llaves privadas ni otros
secretos en commits, Issues o Pull Requests.

## Estructura del repositorio

- `datos/crudos/`: capas, catálogos y fuentes oficiales.
- `datos/grafos/`: G6, G8, G10 y G12 en CSV y GraphML.
- `scripts/construir_grafo_ice.py`: constructor definitivo de los grafos.
- `scripts/ejecutar_entrega.py`: punto único de entrada.
- `resultados/clasicos/`: QUBO, solución exacta, greedy, recocido y
  Goemans-Williamson.
- `resultados/qaoa_local/`: optimizaciones, mediciones y resúmenes.
- `resultados/remoto/`: evidencia SelenePlus separada.
- `resultados/tablas_finales/`: comparaciones de calidad, costo, ruido y
  robustez.
- `figuras/`: seis figuras finales, incluida la comparación entre simulación
  ideal y SelenePlus con ruido.
- `notebooks/`: desarrollo y validación técnica de las etapas del proyecto.
- `docs/`: informe, auditoría, interpretación y guía de tiros.
- `build/`: salida temporal regenerable.

## Métodos

### 1. Construcción de los grafos

La red se representa como un grafo ponderado `G=(V,E,w)`. Los nodos representan
subestaciones y las aristas representan conexiones de transmisión. Los pesos
combinan la longitud del corredor y su tensión nominal.

Fuente:
[Portal de datos abiertos del ICE](https://datos-ice-se.opendata.arcgis.com/).

El peso es un proxy reproducible de exposición física. No representa una
métrica oficial de riesgo, flujo, capacidad, demanda ni criticidad operativa.

### 2. Formulación QUBO

Max-Cut se expresa como:

```text
C(x) = Σ w_ij (x_i + x_j - 2 x_i x_j)
```

Para utilizar una convención QUBO de minimización se minimiza `-C(x)`. La
formulación se verificó en instancias pequeñas mediante evaluación directa,
fuerza bruta y comparación con el Hamiltoniano de Ising.

### 3. Implementación de QAOA

La QUBO se transforma en un Hamiltoniano de costo de Ising. QAOA alterna capas
de costo y mezcla, cuyos parámetros se optimizan clásicamente.

La implementación final utiliza Guppy, profundidades `p=1,2,3`, múltiples
inicializaciones y el optimizador L-BFGS-B. Los resultados principales reportan
la media y la desviación estándar entre inicializaciones, no únicamente el
mejor reinicio.

### 4. Líneas base clásicas

La comparación incluye:

- bipartición exacta del árbol;
- fuerza bruta para verificación;
- Goemans-Williamson;
- greedy;
- recocido simulado;
- referencia aleatoria teórica `r=0.5`.

## Resultados principales

En simulación ideal, QAOA mejoró al aumentar `p`, pero perdió calidad al crecer
la instancia y no superó los métodos clásicos.

Para `p=3`, la media entre inicializaciones fue aproximadamente:

| Instancia | QAOA ideal, media | Mejor reinicio ideal | SelenePlus con ruido |
|---|---:|---:|---:|
| G6 | 0.894 | 0.917 | 0.673 |
| G8 | 0.874 | 0.894 | 0.518 |
| G10 | 0.853 | 0.871 | 0.515 |
| G12 | 0.840 | 0.854 | 0.501 |

La ejecución SelenePlus mostró una degradación marcada frente al mejor valor
ideal. En G8, G10 y G12, el resultado quedó próximo a la referencia aleatoria
de 0.5.

Solo existe una ejecución remota de 512 tiros por instancia. Por tanto, estos
datos describen el trabajo observado, pero no permiten estimar la media,
desviación o reproducibilidad del ruido del backend.

## Limitaciones honestas

- No se demostró ventaja cuántica.
- No hubo ejecución en una computadora cuántica física.
- SelenePlus es un backend de emulación con un modelo de errores.
- No se comparan tiempos de pared como evidencia de aceleración.
- Las cuatro instancias son árboles bipartitos con pesos positivos y se
  resuelven exactamente en tiempo lineal mediante bipartición.
- QAOA no superó la solución exacta, Goemans-Williamson, recocido ni greedy.
- La ejecución con ruido se realizó una sola vez por instancia.
- No se aplicó mitigación de ruido ni corrección de errores cuánticos.
- Los pesos no representan riesgo, flujo eléctrico ni criticidad oficial.
- Max-Cut produce candidatos topológicos, no un diseño operativo de zonas de
  falla para el ICE.

## Reproducibilidad

El flujo utiliza semillas deterministas y separa:

1. datos de entrada;
2. construcción geoespacial;
3. líneas base clásicas;
4. optimización QAOA;
5. compilación Guppy/HUGR;
6. resultados remotos;
7. tablas, figuras y validaciones.

Las cifras del informe se generan a partir de archivos tabulares versionados.
No se añadieron aristas artificiales: se priorizaron la fidelidad a los datos
del ICE, la trazabilidad y la reproducibilidad.

## Referencias

- Farhi, E., Goldstone, J. y Gutmann, S. (2014).
  [A Quantum Approximate Optimization Algorithm](https://arxiv.org/abs/1411.4028).
- Goemans, M. X. y Williamson, D. P. (1995). Improved approximation algorithms
  for maximum cut and satisfiability problems. *JACM*, 42(6), 1115-1145.
- Blekos, K. et al. (2024). A review on Quantum Approximate Optimization
  Algorithm and its variants.
- Jin, Y. et al. (2025).
  [Iceberg QEC code](https://arxiv.org/abs/2504.21172).
- [Datos abiertos del ICE](https://datos-ice-se.opendata.arcgis.com/).

## Equipo

**NOIR Technologies · Universidad Cenfotec · Costa Rica**

---

Quantathon CR 2026: se priorizan el rigor, la reproducibilidad y la
interpretación honesta de los resultados.
