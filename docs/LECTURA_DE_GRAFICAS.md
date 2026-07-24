# Lectura de las comparaciones finales

## Qué se retiró

La gráfica «mejor solución encontrada por método» no se usa como evidencia
principal. Con 512 tiros, basta que aparezca un único bitstring óptimo para que
la razón de mejor solución sea 1.0, aunque la mayoría de las muestras sean
peores. En estas instancias esa gráfica se satura, no discrimina métodos y no
forma parte de la entrega final.

## Qué se reporta

| Pregunta | Métrica | Mejor dirección | Precaución |
|---|---|---|---|
| ¿Qué calidad entrega normalmente? | Razón de aproximación media | Mayor | No confundir con el mejor tiro |
| ¿Qué tan concentrado está QAOA en el óptimo? | Probabilidad de óptimo por tiro | Mayor | Usar escala logarítmica |
| ¿Cuánto varía el muestreo? | Desviación entre 30 lotes de 512 tiros | Menor | Es error de tiros, no de optimización |
| ¿Cuánto depende del punto inicial? | Distribución entre reinicios | Menor dispersión | La entrega selecciona el mejor reinicio |
| ¿Qué cuesta aumentar \(p\)? | Operaciones ZZ y RX | Menor para igual calidad | Más profundidad puede aumentar ruido |
| ¿Qué cambió con SelenePlus? | Diferencia SelenePlus − ideal | Cercana a cero | Solo existe un trabajo remoto por grafo |

## Hallazgos principales

1. La razón ideal mejora al pasar de \(p=1\) a \(p=3\) en los cuatro grafos.
2. Las operaciones ZZ se triplican en el mismo cambio de profundidad.
3. La ganancia por ZZ adicional disminuye especialmente en G10 y G12.
4. En G12, \(p=3\), la razón ideal es 0.853893 y la probabilidad ideal de
   óptimo por tiro es 0.014891. En 512 tiros se esperan alrededor de 7.62
   muestras óptimas; esto explica por qué el mejor tiro llega a 1.0 sin que el
   estado completo sea óptimo.
5. SelenePlus presenta una reducción de entre 0.244678 y 0.376358 en razón de
   aproximación respecto al valor ideal para este único trabajo de 512 tiros
   por grafo. La figura `06_ideal_vs_seleneplus_p3.png` muestra esta comparación
   directa y la tabla `03_seleneplus_vs_ideal_p3.csv` conserva los valores
   exactos.
6. En \(p=3\), la media entre reinicios es menor que el mejor reinicio
   seleccionado. La diferencia debe mostrarse de forma explícita.

## Límite estructural

Los cuatro grafos son árboles bipartitos con pesos positivos. El óptimo clásico
corta todas las aristas, por lo que Goemans–Williamson y recocido simulado
alcanzan 1.0 de forma consistente. Las comparaciones demuestran implementación,
escalamiento y efecto de profundidad, pero no ventaja cuántica.

Si se quiere estudiar dificultad algorítmica real, la mejora más importante no
es añadir más gráficas, sino incluir una instancia regional real con ciclos o
una formulación con restricciones operativas adicionales. No deben inventarse
aristas para lograrlo.
