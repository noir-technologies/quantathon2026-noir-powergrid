# Auditoría y guía de tiros

## 1. Qué se encontró en el paquete original

El material técnico es mejor de lo que sugería su organización. Ya existían:

- cuatro tamaños de grafo y una formulación QUBO verificada;
- fuerza bruta, greedy, recocido simulado y Goemans–Williamson;
- QAOA ideal para p=1,2,3 en G6/G8/G10/G12;
- 112 registros de optimización con múltiples reinicios;
- 30 repeticiones de 512 tiros para cada una de las 12 configuraciones;
- 12 ejecuciones Guppy locales de 512 tiros;
- una ejecución SelenePlus ruidosa de los cuatro grafos en p=3.

Los problemas principales eran de entrega:

- dos notebooks QAOA casi duplicados;
- una celda del entorno con `SyntaxError`;
- instalaciones hechas dentro de los notebooks;
- rutas que dependían de archivos no incluidos;
- `requirements.txt` sin Guppy, qnexus, SciPy, CVXPY ni seaborn;
- README limitado al constructor del grafo;
- archivos planos y duplicados con sufijos `(1)` y `(2)`;
- ausencia de un único punto de entrada;
- una comparación de “mejor solución” que daba razón 1.0 para todos los
  métodos y ocultaba el rendimiento promedio.

## 2. Qué significan los tiros

Un tiro es una ejecución completa del circuito seguida de una medición. Con
512 tiros se obtienen 512 bitstrings. El valor esperado experimental es:

\[
\widehat{E}[C] =
\frac{1}{S}\sum_z N_z C(z),
\]

donde \(S\) es el número de tiros, \(N_z\) la frecuencia del bitstring \(z\)
y \(C(z)\) el valor del corte. La razón reportada es:

\[
\widehat r = \frac{\widehat{E}[C]}{C_{\mathrm{óptimo}}}.
\]

Más tiros reducen la incertidumbre de muestreo aproximadamente como
\(1/\sqrt{S}\), pero no corrigen:

- parámetros QAOA deficientes;
- ruido físico o del emulador;
- errores en el orden de bits;
- una formulación de costo incorrecta.

Por eso no debe aumentarse el número de tiros antes de validar el circuito.

## 3. Flujo ejecutado

| Etapa | Backend | Tiros | Propósito |
|---|---|---:|---|
| Optimización | Vector de estado ideal | 0 | Encontrar gamma y beta sin ruido de muestreo |
| Validación Guppy | Emulador local | 512 | Confirmar signo, escala y orden de bits |
| Estadística local | Muestreo ideal | 30 × 512 | Media, desviación e intervalo de confianza |
| Resultado final | SelenePlus | 512 por grafo | Comparar el resultado remoto con el ideal |

Los cuatro resultados SelenePlus en p=3 son suficientes para el criterio remoto
del evento. Las 30 × 512 mediciones locales cuantifican error de muestreo del
mismo estado ideal; el único trabajo SelenePlus por grafo no permite estimar
variabilidad entre trabajos remotos.

## 4. Cómo recuperar SelenePlus sin enviar otro trabajo

Abra `notebooks/04_seleneplus.ipynb`.

1. Confirme que `ENVIAR_NUEVO_JOB = False`.
2. Verifique el `JOB_ID_SELENE`, `P_SELENE = 3` y `SHOTS_SELENE = 512`.
3. Ejecute las secciones de construcción, recuperación y exportación.
4. Compruebe que el estado sea `COMPLETED` y que existan cuatro resultados.
5. Guarde los conteos, el resumen y los metadatos exportados.

La recuperación mediante `qnx.jobs.get(...)` reutiliza el trabajo existente.
El bloque de envío permanece desactivado durante la auditoría.

## 5. Evidencia que debe aparecer en el informe

No basta una captura con estado `SUBMITTED`. La evidencia mínima es:

- backend exacto;
- ID del trabajo;
- estado `COMPLETED`;
- fecha y hora;
- tiros solicitados y recibidos;
- conteos o CSV descargado;
- razón de aproximación;
- probabilidad del óptimo;
- comparación con ideal, GW y greedy.

En esta entrega esa evidencia corresponde a SelenePlus.

## 6. Gráficas y tablas finales

Las figuras principales son:

1. `01_razon_vs_p_inicializaciones.png`: razón esperada frente a \(p\), con
   media y desviación entre las distintas inicializaciones del optimizador
   para cada combinación de tamaño y profundidad.
2. `02_probabilidad_optimo_por_tiro.png`: probabilidad de óptimo en un tiro,
   en escala logarítmica; evita la saturación causada por lotes grandes.
3. `03_comparacion_metodos_calidad_media.png`: comparación por rendimiento
   medio, no por el mejor bitstring.
4. `04_tradeoff_calidad_operaciones_zz.png`: ganancia de calidad frente al
   crecimiento del circuito.
5. `05_robustez_reinicios_p3.png`: dispersión entre reinicios y selección
6. `06_ideal_vs_seleneplus_p3.png`: comparación directa entre la simulación
   ideal local y el único trabajo SelenePlus ruidoso para cada grafo.
   explícita del mejor.

Las tablas de `resultados/tablas_finales/` contienen los valores exactos para
profundidad, costo, comparación de métodos, SelenePlus y reinicios. La figura
de “mejor solución por método” no forma parte de la entrega final.

## 7. Interpretación honesta de los resultados

El QAOA ideal mejora al pasar de p=1 a p=3 en los cuatro tamaños:

| Grafo | p=1 | p=3 | Mejora |
|---|---:|---:|---:|
| G6 | 0.8384 | 0.9173 | +0.0789 |
| G8 | 0.8116 | 0.8945 | +0.0829 |
| G10 | 0.7938 | 0.8712 | +0.0774 |
| G12 | 0.7809 | 0.8539 | +0.0730 |

La probabilidad ideal de medir un óptimo en G12, p=3 es aproximadamente
1.49 %. Con 512 tiros, la probabilidad teórica de observar al menos uno es
superior al 99.9 %, lo cual explica por qué la “mejor solución observada”
resulta óptima aunque la razón media sea 0.8539.

Esa diferencia es crucial: encontrar una muestra óptima no significa que la
distribución QAOA sea óptima.

## 8. Fuente oficial para el flujo remoto

- SelenePlus:
  https://docs.quantinuum.com/nexus/trainings/notebooks/basics/selene_examples.html
