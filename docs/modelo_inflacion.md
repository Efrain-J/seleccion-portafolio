# Proyección de inflación con Hull-White

Este documento explica cómo se proyecta la inflación con el modelo Hull-White (`src/uvr_loan/inflation_model/`), en qué
se diferencia del Hull-White original y qué significa cada parámetro. No hay fórmulas: las reglas de inversión que usan
estos escenarios están en [`reglas_de_inversion.md`](reglas_de_inversion.md).

## 1. Para qué sirve

En cada revisión (cada 6 meses) los planes necesitan una inflación para proyectar la UVR y, con ella, los pagos del
crédito en pesos: el plan 1 dimensiona el FIC, el plan 2 pasa las tasas nominales a reales y los planes 3 y 4 calculan el
piso. El modelo entrega **tres escenarios de inflación anual: bajo, base y alto**, calculados solo con información
disponible al cierre de ese mes.

## 2. El Hull-White original

El código que se recibió al principio (`hull_white.py`, `pipeline.py`, `curvas_simuladas.py`, `conversion_diaria.py` y
`generar_consolidado.py`) tenía otro objetivo: generar **curvas de tasas estresadas**, no pronosticar inflación. Hacía esto:

1. Reconstruía con los betas las curvas de UVR y de pesos, y la inflación implícita entre ambas.
2. Medía cuánto se mueve cada plazo y se quedaba con el percentil 99,5 de esa volatilidad.
3. Simulaba con Hull-White, con pasos anuales y 36 años de horizonte, la curva de UVR y la de inflación implícita por
   separado, con la misma semilla.
4. Ajustaba una curva Nelson-Siegel estable a cada curva simulada y la extendía de 36 a 37 años con un puente cúbico; la
   curva en pesos salía de combinar las dos.
5. Con una regresión Ridge derivaba otras cuatro curvas (CEC, BAAA12, BAAA3 y BAAA2) y escribía un archivo consolidado de
   nodos diarios para cinco clases de activo.

Su resultado era la nube de curvas simuladas tal como salía, un escenario de estrés de toda la curva.

## 3. El modelo ahora, en cinco pasos

```
betas del Banco ──► inflación ──► simulación ──► corrección con ──► escenarios
(curvas en pesos    implícita     Hull-White     la historia         bajo / base / alto
 y en UVR)          del mercado   (10.000                            (percentil 5, mediana,
                                  trayectorias)                      percentil 99,5)
```

1. **Datos.** Los betas de Nelson-Siegel que publica el Banco de la República, cada día, para la curva de los TES en
   pesos y para la de los TES en UVR. Con ellos se reconstruye cada curva para los plazos de 1 a 36 años.
2. **Inflación implícita.** La que descuenta el mercado: lo que rinde un TES en pesos frente a uno en UVR del mismo plazo.
   Es una mirada hacia adelante, con la información de todos los compradores y vendedores de TES.
3. **Simulación.** El modelo Hull-White genera 10.000 trayectorias de cómo podría moverse esa curva en los próximos meses
   y se mira la inflación de los próximos 6 meses en cada una. La simulación queda centrada en la inflación implícita de
   hoy; lo que aporta es la **dispersión**: cuánto puede alejarse la inflación de ese centro.
4. **Corrección con la historia.** Para cada mes pasado, ya con su resultado conocido, se compara lo que el modelo
   proyectó con lo que pasó (la inflación realizada se reconstruye del cambio mensual de la UVR). Con esas diferencias se
   corrigen tres cosas:
   - **El sesgo:** entre 2013 y 2026 la inflación implícita quedó, en promedio, por debajo de la inflación realizada.
   - **La estacionalidad:** la inflación de enero y febrero es alta y la de mediados de año es baja.
   - **La dispersión que le faltaba:** la simulación sola es demasiado estrecha frente a los errores que se observaron.
   Solo entran los meses cuyo resultado ya se conocía en ese momento: el modelo nunca mira el futuro.
5. **Escenarios.** Del resultado corregido se toman el **percentil 5 (bajo)**, la **mediana (base)** y el
   **percentil 99,5 (alto)**. Se guardan en `data/forecasts/hw_inflation_forecasts.csv`, una fila por mes, y la configuración
   decide qué columna es cada escenario (`inflation_scenarios.forecast_columns`).

## 4. Qué cambia frente al Hull-White original

| | Hull-White original | Modelo ahora |
|---|---|---|
| Objetivo | Curvas estresadas de todos los plazos y de cinco clases de activo | Un pronóstico de la inflación de los próximos 6 meses, con mediana y percentiles |
| Qué se simula | La curva de UVR y la inflación implícita, cada una por su lado | Solo la inflación implícita entre la curva en pesos y la de UVR |
| Pasos y horizonte | Pasos anuales, 36 años | Pasos mensuales, 1 año; se mira el punto de 6 meses |
| Qué entrega | La nube de curvas simuladas, tal cual | La nube corregida con la historia, resumida en percentil 5, mediana y percentil 99,5 de cada mes |
| Inflación realizada | No se usa | Se reconstruye de la UVR y sirve para corregir sesgo, estacionalidad y dispersión |
| Cuándo se calcula | Una corrida con toda la historia | Un pronóstico por cada cierre de mes, con lo conocido hasta ese día |
| Lo que se dejó fuera | Ajuste Nelson-Siegel de cada curva simulada, puente cúbico a 37 años, regresión Ridge, las otras cuatro curvas y el archivo consolidado | Nada de eso hace falta para pronosticar inflación |

**Lo que no cambió.** El núcleo de la simulación es el mismo: las mismas fórmulas, los mismos `kappas` (0,11 y 0,13), el
cambio a los 5 años, el percentil 99,5 de la volatilidad, la ventana de 365 días y la semilla. El resultado de la
simulación es idéntico al del código original con los mismos datos de entrada. También se conservan sus rarezas: solo se usan
los primeros 5 plazos de volatilidad y `kappa_switch_years` cumple dos funciones.

**Por qué importa la corrección.** El Hull-White original, usado como pronóstico, tiene una banda demasiado estrecha: describe
cómo podría moverse la curva del mercado, no las sorpresas que tiene la inflación real. Esa es la mejora principal, más que
cualquier cambio en la simulación. Se midió en un backtest de desarrollo de 130 meses de origen (de mediados de 2015 a marzo
de 2026), comparando la simulación sin corregir (el modelo original usado como pronóstico a 6 meses, con pasos mensuales) con
el modelo corregido, frente a la inflación que ocurrió en los 6 meses siguientes:

| | Simulación sin corregir | Modelo corregido |
|---|---|---|
| Error probabilístico (CRPS, menor es mejor) | 2,38 p.p. | 1,54 p.p. |
| Veces que la inflación real cae dentro de la banda del 90 % | 22 % | 79 % |
| Veces que cae dentro de la banda del 50 % | 7 % | 48 % |
| Ancho medio de la banda del 90 % | 1,9 p.p. | 7,0 p.p. |

La banda corregida es mucho más ancha, y eso explica gran parte de la mejora en cobertura. Lo que importa es que, con el
ancho original, la banda casi nunca contenía lo que pasaba. Este backtest se hizo en el proyecto original `hull_white` y sus
scripts **no se trasladaron a este repositorio**, así que estas cifras no se pueden repetir desde aquí.

## 5. Parámetros

### Sección `inflation_model` de `config/assumptions.yaml`

| Parámetro | Valor | Qué significa | Qué pasa si se cambia |
|---|---|---|---|
| `betas_file` | `data/raw/betas_historicos.csv` | Archivo con los betas del Banco de la República, descargado a mano (ver `data/SOURCES.md`) | Solo cambia de dónde se leen; el archivo debe tener las mismas columnas |
| `betas_start` | 2010-01-01 | Los betas anteriores a esta fecha se ignoran | No cambia nada mientras sea anterior al 2012-01-07, cuando empiezan los datos de la curva en pesos |
| `tenors` | 36 | Plazos anuales de las curvas (1 a 36 años) | Casi no afecta el pronóstico a 6 meses: solo cuentan los primeros plazos |
| `vol_window_days` | 365 | Días de historia con los que se mide cuánto se mueve la inflación implícita | En las pruebas con 180 y 730 días movió el ancho de la banda entre −9 % y +35 % según la fecha, sin cambiar las conclusiones |
| `vol_percentile` | 0,995 | Qué volatilidad se usa: la del 0,5 % de los años más movidos | Más bajo da una banda más estrecha; con 0,995 la banda es de estrés |
| `kappas` | 0,11 y 0,13 | Qué tan rápido vuelve la curva a su nivel normal, antes y después de `kappa_switch_years` | Más alto estrecha la banda a plazos largos; a 6 meses, en las pruebas, pasar de 0,11 a 0,7 la estrechó solo entre un 11 % y un 13 % |
| `kappa_switch_years` | 5 | Año en que cambia de un `kappa` al otro; también es el número de plazos de volatilidad que se usan (los demás se ignoran) | Moverlo cambia a la vez el `kappa` y los plazos de volatilidad usados |
| `n_paths` | 10.000 | Trayectorias simuladas en cada mes | Menos trayectorias hacen más ruidoso el percentil 99,5 |
| `seed` | 123456 | Semilla del azar: mismos números en cada corrida | Cambia los decimales de los resultados, no su sentido |
| `horizon_months` | 6 | Meses de inflación que se proyectan; de aquí salen también el rezago para considerar «realizado» un mes (6 más el de la UVR) y la ventana de estacionalidad | Cambiarlo cambia qué se pronostica y el archivo debe regenerarse |
| `min_history` | 12 | Meses con resultado ya conocido que hacen falta para empezar a corregir | Más meses retrasan el primer pronóstico |
| `first_origin` | 2013-06 | Primer mes que se simula | Debe haber al menos un año de betas antes |
| `first_forecast` | 2016-01 | Primer mes que se escribe en el archivo | Los meses anteriores se usan solo como historia |

### Sección `inflation_scenarios`

| Parámetro | Valor | Qué significa |
|---|---|---|
| `source` | `trailing` | De dónde salen los escenarios de los planes: `trailing` (inflación de los últimos meses de la UVR más un choque fijo) o `forecast` (este modelo) |
| `forecast_file` | `data/forecasts/hw_inflation_forecasts.csv` | Archivo del pronóstico: una fila por mes |
| `forecast_columns` | bajo `p05_ea`, base `median_ea`, alto `p995_ea` | Columna del archivo que es cada escenario (solo con `forecast`) |
| `base_lookback_months` | 6 | Meses de la UVR que mira la fuente `trailing` |
| `high_shock_pp` / `low_shock_pp` | +3,0 / −1,5 | Choques sobre la base de la fuente `trailing` |

### Fijos en el código (no son parámetros)

| Constante | Valor | Por qué es fija |
|---|---|---|
| Pasos por año | 12 | El IPC es mensual |
| Años simulados | 1 | Alcanza para cubrir el horizonte de 6 meses |
| Rezago de la UVR | 2 meses | Así está definida la UVR: su cambio mensual refleja el IPC de dos meses antes |
| Percentiles del archivo | 5 y 99,5 | Son los nombres de las columnas `p05_ea` y `p995_ea` |

## 6. Cómo se usa

```
.venv\Scripts\python -m uvr_loan.inflation_model.forecast        # regenera el pronóstico (unos 15 segundos)
.venv\Scripts\python -m uvr_loan.forecast_runs [base|high|low]   # corre los planes con cada fuente de escenarios
```

- Regenerar el pronóstico necesita el archivo de betas en `data/raw/`; sin él se usa el archivo ya guardado.
- Para que los planes usen el modelo, `inflation_scenarios.source` debe ser `forecast`. `forecast_runs` corre los planes con
  las dos fuentes y escribe los resultados en `results/forecast_runs[_<escenario>]/`; el argumento es el escenario con el
  que deciden los planes (por defecto, el alto).

## 7. Límites que hay que conocer

- **Un pronóstico de 6 meses se usa para todo el plazo.** Cada escenario es una inflación anual constante durante todo lo
  que falta del crédito (hasta 10 años). No es un pronóstico a 10 años.
- **La corrección se apoya en pocos datos.** El sesgo y la estacionalidad se estiman con unas 28 ventanas de 6 meses que no
  se solapan. Que la inflación implícita quede por debajo de la realizada puede ser una prima de liquidez de los TES en
  UVR o una característica de 2013 a 2026 (un periodo con inflación por encima de la meta).
- **El percentil 99,5 es un escenario de estrés,** no una expectativa; por eso, con `forecast`, el escenario alto es mucho
  más alto que la base.
- **Los betas no están versionados.** Sin ese archivo no se puede regenerar el pronóstico; el archivo guardado es el único
  registro de los resultados.
- **La fuente predeterminada sigue siendo `trailing`,** así que los números de `reglas_de_inversion.md` son los de esa fuente.
