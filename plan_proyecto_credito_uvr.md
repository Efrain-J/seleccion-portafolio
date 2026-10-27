# Plan de trabajo – Estrategia de inversión para cubrir un crédito en UVR

> Documento vivo. Última actualización: 26-oct-2026.
> Cambios v3: S5 (abonos pactados: se mantienen el plazo y la cuota, C ≈ 20.379,5 UVR) y S6 (sin costos).
> Cambios v2: se elimina la simulación futura (antiguo Enfoque B) y se añade la comparación entre una estrategia **estática** (selección única en t₀) y una **dinámica** (re-estimación y rebalanceo periódicos).

---

## 0. Enunciado (resumen)

- **Capital inicial:** $760.000.000 COP
- **Crédito:** 1.000.000 UVR, plazo 120 meses, tasa UVR + 10 % E.A., cuotas fijas mensuales en UVR
- **Periodo de gracia:** 3 años
- **Abonos extraordinarios programados:** 50.000 UVR al final del año 4 (mes 48) y 50.000 UVR al final del año 5 (mes 60)
- **Objetivos:**
  1. Calcular la cuota mensual en UVR después de la gracia.
  2. Diseñar la estrategia de inversión que dé liquidez para las cuotas y los abonos.
  3. Evaluar escenarios de inflación y rentabilidad.
  4. Justificar los activos y la estrategia.
  5. Simular los 10 años, maximizando la rentabilidad y minimizando el riesgo.

---

## 1. Supuestos

| # | Supuesto | Estado |
|---|---|---|
| S1 | **Gracia total**: no hay pagos en los meses 1–36 y los intereses se capitalizan | ✅ Definido |
| S2 | Los pagos (cuotas y abonos) son fijos en UVR: **la liquidez debe existir en cada fecha de pago (cero déficit)** | ✅ Definido |
| S3 | **No se incluyen impuestos** (ni 4×1000 ni retención en la fuente) | ✅ Definido |
| S4 | **t₀ histórico = oct-2016**, horizonte oct-2016 → oct-2026 con datos reales (backtest) | ✅ Definido |
| S5 | Abonos **pactados desde el inicio**: se mantienen el plazo (120 meses) y la cuota. La cuota fija de los meses 37–120 ya incorpora los dos abonos programados | ✅ Definido |
| S6 | **Sin costos** de transacción, comisiones ni rebalanceo | ✅ Definido |
| S7 | Convención de fechas: mes 48 = fin del año 4, mes 60 = fin del año 5 | ✅ Definido |
| S8 | Frecuencia de re-estimación de la estrategia dinámica: **k = 6 meses** (base; sensibilidad con 3 y 12) | ✅ Definido |

---

## 2. Tabla de amortización en UVR (Objetivo 1)

**Tasa mensual:** i = (1,10)^(1/12) − 1 ≈ 0,7974 %

**Pasos:**
1. Meses 1–36: capitalizar intereses. El saldo al mes 36 es 1.000.000 × 1,10³ = 1.331.000 UVR.
2. Como los abonos están pactados desde el inicio (S5), la cuota se calcula **una sola vez** con la ecuación de valor en el mes 36:

   Saldo₃₆ = C · [1 − (1+i)^−84] / i + 50.000 / (1+i)^12 + 50.000 / (1+i)^24

   - VP de los abonos en el mes 36: 50.000/1,10 + 50.000/1,21 ≈ 86.777 UVR
   - Saldo a financiar con cuotas: 1.331.000 − 86.777 ≈ 1.244.223 UVR
   - Factor de anualidad (84 meses): ≈ 61,0526
   - **C ≈ 20.379,5 UVR/mes** (constante en los meses 37–120)
3. Mes 48: se paga C + 50.000 UVR. Mes 60: se paga C + 50.000 UVR. No se recalcula nada.
4. Control: el saldo del mes 120 debe ser 0.

**Valores de referencia (aprox., se validan en el modelo):**

| Tramo | Pago mensual |
|---|---|
| Meses 1–36 | 0 (gracia total) |
| Meses 37–120 | ≈ 20.379,5 UVR |
| Mes 48 | ≈ 20.379,5 + 50.000 = 70.379,5 UVR |
| Mes 60 | ≈ 20.379,5 + 50.000 = 70.379,5 UVR |

**Momentos críticos de liquidez:**
- Mes 37: primera cuota.
- Mes 48: cuota + 50.000 UVR.
- Mes 60: cuota + 50.000 UVR.

**Entregable:** tabla mes a mes con saldo inicial, interés, amortización, cuota, abono y saldo final (en UVR).

---

## 3. UVR e inflación → flujo de pagos en COP

- Relación: UVRₜ = UVRₜ₋₁ × (1 + π_mensual), donde π_mensual = (1 + π_anual)^(1/12) − 1
- Pago en COPₜ = Pago en UVRₜ × UVRₜ
- **Dos versiones del flujo de pagos:**
  - **Proyectado:** el que se estima en cada fecha de decisión con la información disponible en ese momento. Se usa para diseñar o rebalancear el portafolio.
  - **Realizado:** el que ocurrió con la UVR real. Se usa para evaluar si los pagos se cubrieron.
- **Escenarios de planeación** (se construyen en cada fecha de decisión):
  - **Base:** expectativas de BanRep (Encuesta de Expectativas) y/o un modelo estimado con los datos hasta esa fecha.
  - **Alto:** base + choque (p. ej. +3 p.p.).
  - **Bajo:** base − choque (p. ej. −1,5 p.p.).
- **Método de pronóstico de inflación** (elegir uno o combinar):
  - Encuesta de Expectativas de BanRep
  - Inflación implícita (break-even) entre TES tasa fija y TES UVR
  - Modelo AR(1) / reversión a la meta del 3 %, estimado con datos hasta la fecha de decisión

---

## 4. Diagnóstico de viabilidad (en t₀ = oct-2016)

1. Calcular el valor del crédito en COP en t₀ (1.000.000 × UVR de oct-2016) y compararlo con los 760M.
2. Calcular el VP de todos los pagos en COP por escenario de planeación.
3. Hallar la **TIR requerida**: la rentabilidad que hace VP(pagos) = 760M.
4. Calcular el **indicador de cobertura (funding ratio)** = valor de los activos / VP de los pagos pendientes. Se recalcula en cada revisión de la estrategia dinámica.
5. Interpretación: si el capital excede con holgura las obligaciones, la pregunta central pasa a ser **"¿cuánto excedente se genera sin arriesgar ningún pago?"**.
6. Discusión adicional: comparar prepagar frente a invertir. Si la rentabilidad esperada es menor que UVR + 10 %, conviene prepagar.

---

## 5. Diseño del portafolio (Objetivos 2 y 4)

### 5.1 Universo de activos

| Activo | Rol |
|---|---|
| Cuenta remunerada / FIC a la vista | Liquidez inmediata |
| CDT tasa fija / CDT IPC+ | Escalera de vencimientos de corto y mediano plazo |
| **TES UVR** | **Cobertura natural**: el activo y el pasivo están indexados a la UVR |
| TES tasa fija | Rentabilidad y diversificación |
| Renta variable / ETF (COLCAP, internacionales) | Crecimiento del excedente |

Para cada activo se documenta: rentabilidad esperada, volatilidad, liquidez, riesgo de crédito y riesgo de mercado.

> Verificar qué referencias de TES UVR estaban disponibles en cada fecha de decisión (fechas de vencimiento existentes).

### 5.2 Estructura: portafolio dedicado + portafolio de excedente

- **Portafolio dedicado (cubre los pagos):**
  - Calce de flujos con TES UVR, CDT IPC+ y una escalera de vencimientos.
  - Los títulos vencen justo antes de los meses 48 y 60 (ventanas de meses 46–48 y 58–60) y antes de cada bloque anual de cuotas.
  - Se dimensiona en UVR, de modo que si sube la inflación también sube el activo.
  - Inmunización: la duración de los activos debe ser similar a la de los pasivos.
- **Portafolio de excedente:** TES tasa fija y renta variable. Es el único componente que asume riesgo de mercado.
- **Buckets operativos:**
  - Bucket 1, liquidez (0–12 meses).
  - Bucket 2, calce (1–5 años): incluye los dos abonos.
  - Bucket 3, largo plazo (años 5–10).
- **Ventaja de la gracia total:** no hay retiros durante 36 meses, así que se puede invertir a más largo plazo al inicio.

### 5.3 Formulación

> **Maximizar el excedente final, sujeto a que la caja disponible sea ≥ el pago en COP en todo mes t (cero déficit).**

### 5.4 Perfiles de asignación

Cada perfil se evalúa con ambos enfoques de gestión (sección 6):

- **Conservador:** solo CDT/FIC.
- **Propuesto:** dedicado + excedente.
- **Agresivo:** mayor proporción en renta variable.
- **No indexado:** solo instrumentos de tasa fija. Sirve para evidenciar el valor de la cobertura UVR.

---

## 6. Simulación de los 10 años – Backtest oct-2016 → oct-2026

### 6.1 Marco común

- **Datos reales:**
  - UVR (BanRep)
  - IPC (DANE)
  - Curvas TES UVR y tasa fija (BanRep)
  - Tasas de CDT (Superfinanciera)
  - COLCAP / MSCI COLCAP
  - Rentabilidad de FIC
- **Dinámica mensual:** Saldoₜ = Saldoₜ₋₁ × (1 + rₜ) − Pago COPₜ, con los pagos tomados del bucket de liquidez.
- **Regla sin sesgo de anticipación:** toda decisión tomada en la fecha τ usa **solo** información disponible hasta τ. Los resultados se miden con la trayectoria real.
- El periodo incluye el choque inflacionario de 2021–2023, que funciona como prueba de estrés real.

### 6.2 Enfoque 1 – Estático (selección única en t₀)

- En oct-2016 se estima la inflación, se proyectan los pagos y se arma el portafolio una sola vez.
- Después **no se re-optimiza**: los títulos se mantienen hasta el vencimiento.
- Solo hay movimientos operativos con reglas fijadas en t₀. Por ejemplo, los vencimientos que no se usan van al FIC y los pagos se toman del bucket de liquidez.
- **Pregunta que responde:** ¿una buena decisión inicial basta para cubrir 10 años, incluyendo una sorpresa inflacionaria?

### 6.3 Enfoque 2 – Dinámico (re-estimación cada k = 6 meses)

En cada fecha de revisión τ = 6, 12, 18, … meses:

1. **Actualizar los datos** hasta τ: UVR e IPC realizados, curvas TES, tasas de CDT y precios de mercado.
2. **Re-estimar la inflación** y las demás métricas con el método de la sección 3:
   - Rentabilidades esperadas
   - Volatilidades y correlaciones (ventana móvil)
3. **Reproyectar los pagos pendientes** en COP y recalcular:
   - VP de los pagos pendientes
   - Indicador de cobertura (funding ratio)
   - Brecha de duración
   - Cobertura de los próximos pagos críticos (abonos de los meses 48 y 60)
4. **Re-optimizar el portafolio** con la misma formulación de la sección 5.3, aplicada a los pagos restantes:
   - Ajustar el dedicado si cambió la proyección (p. ej. más TES UVR si sube la inflación esperada).
   - Mover el excedente sobrante a crecimiento, o recortar riesgo si el indicador de cobertura cae.
5. **Registrar la rotación del portafolio.** El rebalanceo no tiene costo (S6), pero la venta anticipada de bonos sí realiza ganancias o pérdidas a precio de mercado.

**Reglas a definir:**
- Bandas de tolerancia (opcional): no son necesarias por costos, pero evitan cambios por ruido en las estimaciones.
- Límite de venta anticipada de títulos: considerar el riesgo de precio.
- Indicador de cobertura mínimo para reducir riesgo (p. ej. < 1,10).

**Pregunta que responde:** ¿actualizar la información periódicamente mejora el excedente y/o reduce el riesgo, después de costos?

### 6.4 Comparación estático vs. dinámico

| Métrica | Estático | Dinámico |
|---|---|---|
| Meses con déficit (meta: 0) | | |
| Saldo mínimo de liquidez | | |
| Excedente final (COP) | | |
| Rentabilidad anualizada / volatilidad | | |
| Máxima caída (drawdown) | | |
| Trayectoria del indicador de cobertura | | |
| Brecha de duración promedio | | |
| Error de pronóstico de inflación (proyectado vs. realizado) | | |
| Rotación y pérdidas/ganancias por venta anticipada | | |

### 6.5 Escenarios de inflación y rentabilidad (Objetivo 3)

- **Escenarios de planeación:** base, alto y bajo en cada fecha de decisión (sección 3).
- **Estrés contrafactual:** aplicar ambos enfoques a trayectorias alternativas de inflación, por ejemplo:
  - La real ±2 p.p.
  - Una sin el choque de 2021–2023
- **Rentabilidad:** pesimista, base y optimista para el componente de excedente.

### 6.6 Gráficos

- Saldo del portafolio frente al flujo de pagos (COP): estático y dinámico
- Indicador de cobertura en el tiempo (ambos enfoques)
- Composición del portafolio en cada revisión (dinámico) frente a la inicial (estático)
- Inflación pronosticada en cada τ frente a la realizada
- Cuota en COP por escenario de inflación

---

## 7. Sensibilidad

- Frecuencia de re-estimación: k = 3, 6 y 12 meses
- Bandas de tolerancia del rebalanceo
- Método de pronóstico de inflación (encuesta BanRep vs. break-even vs. AR)
- Proporción en renta variable
- Opcional: efecto de introducir costos de transacción (relajando S6)

---

## 8. Entregables

1. **Modelo** (Excel y/o Python):
   - Hojas o módulos: supuestos · amortización UVR · datos históricos · pronóstico de inflación · flujo COP · portafolio estático · portafolio dinámico · comparación.
2. **Informe:**
   - Introducción
   - Supuestos
   - Metodología
   - Resultados (cuota, tabla, backtest estático vs. dinámico, escenarios)
   - Estrategia y justificación de los activos
   - Riesgos
   - Conclusiones
   - Fuentes

---

## 9. Orden de trabajo / checklist

- [ ] 1. Tabla de amortización en UVR (gracia total y abonos)
- [ ] 2. Descarga y limpieza de datos históricos 2016–2026
- [ ] 3. Método de pronóstico de inflación y escenarios de planeación
- [ ] 4. Diagnóstico en t₀: VP de los pagos vs. 760M, TIR requerida e indicador de cobertura
- [ ] 5. Diseño del portafolio inicial (dedicado + excedente)
- [ ] 6. Backtest del enfoque estático
- [ ] 7. Backtest del enfoque dinámico (revisiones cada 6 meses)
- [ ] 8. Comparación, escenarios de estrés y sensibilidad
- [ ] 9. Gráficos e informe final

---

## 10. Decisiones pendientes

- [x] ~~Confirmar S5 (tratamiento del abono)~~: se mantienen el plazo y la cuota
- [x] ~~Definir costos y comisiones (S6)~~: sin costos
- [ ] Definir el día exacto de t₀ y la UVR inicial
- [ ] Elegir el método de pronóstico de inflación
- [ ] Definir las bandas de tolerancia y las reglas de rebalanceo del enfoque dinámico
- [ ] Elegir el índice de renta variable y si se incluyen activos internacionales (implica riesgo cambiario)

---

## 11. Fuentes de datos

- Banco de la República: UVR, curvas TES, Encuesta de Expectativas
- DANE: IPC
- Superintendencia Financiera: tasas de CDT, rentabilidad de FIC
- BVC: COLCAP
