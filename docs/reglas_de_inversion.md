# Reglas de inversión

Cómo se decide dónde y cuánto invertir en cada plan. Hoy existen el **plan 1 (conservador)** y el **plan 2
(escalera de CDT optimizada)**; el plan 3 se agregará aquí.

**Criterio de los resultados:** las decisiones pueden usar estimaciones (por ejemplo, la inflación esperada), siempre
con datos disponibles hasta $\tau$. El dinero reportado sale solo de rendimientos observados de instrumentos reales:
tasas de CDT del BanRep, precios del ETF y la UVR. Ningún resultado es un límite ni usa un rendimiento supuesto.

Código: `conservative_allocation` y `ladder_purchases` en `src/uvr_loan/portfolio.py`. Simulación:
`src/uvr_loan/backtest.py` (una estrategia por plan). Parámetros: `config/assumptions.yaml`.

## Notación

El tiempo se cuenta en **meses** desde $t_0$. Por eso la revisión siguiente a $\tau$ es $\tau + k$, no $\tau + 1$.

| Símbolo | Significado | Unidad | En el código / YAML |
|---|---|---|---|
| $t_0$ | Fecha inicial del backtest (oct-2016); mes 0 | fecha | `backtest.t0` |
| $m$ | Mes contado desde $t_0$ ($m = 0, \dots, H$); el pago del mes $m$ ocurre al cierre de ese mes | meses | `month` |
| $H$ | Horizonte: último mes del crédito (120) | meses | `backtest.horizon_months` |
| $\tau$ | Mes de una revisión: $0, k, 2k, \dots$ | meses | `decision_months` |
| $k$ | Meses entre revisiones (6) | meses | `backtest.rebalance_every` |
| $n$ | Meses desde $\tau$ hasta que vence un CDT vivo ($0 < n \le k$) | meses | – |
| $i$ | Tasa mensual del crédito: $(1{,}10)^{1/12} - 1$ | decimal | `monthly_rate` |
| $C$ | Cuota fija de los meses 37–120 (20.379,53) | UVR | `installment` |
| $P_m$ | Pago total del mes $m$ (cuota + abono) | UVR | `total_payment_uvr` |
| $\text{UVR}_m$ | Valor real de la UVR al cierre del mes $m$ | COP por UVR | panel, columna `uvr` |
| $\widehat{\text{UVR}}_m$ | UVR proyectada en $\tau$ para el mes $m$: $\text{UVR}_\tau (1 + \pi)^{(m - \tau)/12}$ | COP por UVR | `project_uvr` |
| $\pi$ | Inflación anual de un escenario en $\tau$: base, alto ($\pi^{\text{base}}_\tau$ + 3 p.p.) o bajo ($\pi^{\text{base}}_\tau$ − 1,5 p.p.) | decimal | `inflation_scenarios`, `scenarios` |
| $\pi^{\text{base}}_\tau$ | Inflación base en $\tau$: la de los últimos 6 meses, anualizada | decimal | `base_lookback_months`, `trailing_inflation` |
| $W$ | Riqueza en $\tau$: FIC + CDT + ETF a precio de mercado | COP | `wealth` |
| $L$ | Necesidad de liquidez en $\tau$ | COP | `projected_payments_cop` |
| $w$ | Peso del ETF sobre $W - L$ (plan 1: 0,10) | decimal | `conservative.equity_weight` |
| $r^{\text{FIC}}_m$ | Rentabilidad anual del FIC en el mes $m$ (DTF a 90 días) | decimal E.A. | panel, columna `fic` |
| $r^{\text{CDT}}_\tau$ | Tasa anual del CDT comprado en $\tau$ (CDT a 180 días) | decimal E.A. | panel, columna `cdt_180` |
| $D_m$ | Déficit del mes $m$: parte del pago que el FIC no cubre | COP | `shortfall` |

**Plan 2:**

| Símbolo | Significado | Unidad | En el código / YAML |
|---|---|---|---|
| $j$ | Plazo de un CDT: 3, 6 o 12 | meses | llaves de `cdt_ladder.terms` |
| $r_j(\tau)$ | Tasa nominal del CDT de plazo $j$ en $\tau$ (DTF, CDT 180 o CDT 360 días) | decimal E.A. | columna de `cdt_ladder.terms` |
| $\tilde r_j(\tau)$ | Rentabilidad real **esperada** de ese CDT en $\tau$ (solo para decidir) | decimal E.A. | `real_rates` |
| $y_{s,j}$ | Monto invertido en el mes $s$ en un CDT de plazo $j$ (solo en meses de revisión) | UVR | variable del LP |
| $c_m$ | Caja (FIC) al cierre del mes $m$ | UVR | variable del LP |
| $M_m$ | Lo que vence en el mes $m$ de los CDT ya comprados | UVR | `maturities_uvr` |
| $B$ | Dinero libre en $\tau$, en UVR | UVR | `budget_uvr` |
| $\rho_\tau$ | Rentabilidad real **esperada** de la caja en el LP (solo para decidir) | decimal E.A. | `cash_rate` |

Definiciones:

$$
\pi^{\text{base}}_\tau = \left(\frac{\text{UVR}_\tau}{\text{UVR}_{\tau-6}}\right)^{12/6} - 1
\qquad
L = \sum_{m=\tau+1}^{\tau+k} P_m \, \widehat{\text{UVR}}_m
$$

$$
B = \frac{\text{FIC}_\tau + \text{lo que vence en } \tau}{\text{UVR}_\tau}
\qquad
\tilde r_j(\tau) = \frac{1 + r_j(\tau)}{1 + \pi^{\text{base}}_\tau} - 1
\qquad
\rho_\tau = \frac{1 + r^{\text{FIC}}_\tau}{1 + \pi^{\text{base}}_\tau} - 1
$$

## Supuestos comunes a todos los planes

- **Orden dentro de un mes (S12):** primero crecen los activos, luego vencen los CDT, luego se paga la cuota y, si es
  mes de revisión, se decide. Un CDT que vence en el mes $m$ sirve para el pago del mes $m$. Si un CDT vivo vence en
  $\tau + n$ ($0 < n \le k$), la caja de hoy solo debe cubrir los $n - 1$ pagos anteriores
  ($\tau+1, \dots, \tau+n-1$).
- **Solo se compra en las revisiones (S13):** lo que vence entre $\tau$ y $\tau + k$ y no se usa para pagar queda en
  el FIC hasta la siguiente revisión.
- **Sin información futura:** en cada revisión la estrategia recibe los datos solo hasta $\tau$.
- **Inflación proyectada:** la base es la inflación de los últimos 6 meses medida con la UVR
  ($\pi^{\text{base}}_\tau$). Es un modelo provisional hasta que exista el modelo de inflación (`scenarios` en
  `src/uvr_loan/inflation.py`). Con 6 meses la base tiene estacionalidad: en abril ve los meses de inflación alta de
  comienzo de año y en octubre los de inflación baja.
- **Déficit (S9):** si el FIC no alcanza para un pago, se registra el déficit y no se hace nada más: no se vende ETF
  ni se redime un CDT antes del vencimiento.
- **FIC (S10):** su rentabilidad se aproxima con la DTF a 90 días.
- **Sin costos ni impuestos (S3, S6):** comprar, vender y rebalancear no cuesta nada.

## Plan 1 – Conservador

Es una regla fija, no una optimización. No usa rentabilidades esperadas, volatilidades ni el indicador de cobertura:
sirve como punto de comparación para los planes más elaborados.

### Instrumentos

| Instrumento | Rol | Dato que se usa |
|---|---|---|
| **FIC a la vista** | Liquidez: de aquí salen las cuotas | DTF a 90 días (supuesto: aproxima la rentabilidad de un FIC) |
| **CDT a 180 días** | Renta fija; vence justo en la siguiente revisión | Tasa de CDT a 180 días del mes de compra |
| **ETF iShares COLCAP** (`ICOLCAP`) | Porción pequeña en renta variable para crecimiento | Precio ajustado por dividendos |

Las fuentes de cada serie están en [`data/SOURCES.md`](../data/SOURCES.md).

### Cuándo se decide

En cada revisión $\tau$, cada $k$ = `backtest.rebalance_every` meses (hoy 6), desde `backtest.t0` (oct-2016):
oct-2016, abr-2017, oct-2017, …, abr-2026.

### Cómo se decide: tres pasos

**1. Cuánto dinero hay ($W$)**

$W$ = saldo del FIC + valor del CDT que vence ese día (capital más intereses) + valor del ETF a precio de mercado.

En $t_0$, $W$ = 760.000.000 COP (`initial_capital_cop`).

**2. Cuánto se necesita hasta la siguiente revisión ($L$)**

1. Se toman los pagos en UVR $P_m$ de los meses $\tau+1, \dots, \tau+k$ de la tabla de amortización (cuotas y
   abonos).
2. Se pasan a COP con la UVR proyectada $\widehat{\text{UVR}}_m$: la UVR real de $\tau$ creciendo a la inflación del
   escenario `conservative.liquidity_scenario` (hoy el **alto**: $\pi^{\text{base}}_\tau$ + 3 p.p.; en oct-2016,
   4,34 % + 3 p.p. = 7,34 %).
3. La suma es la necesidad de liquidez $L$.

Se usa el escenario alto para que el FIC alcance aunque la inflación sea mayor que la esperada.

**3. Repartir $W$**

| Instrumento | Monto |
|---|---|
| FIC | $L$ |
| ETF | $w\,(W - L)$, con $w$ = 10 % hoy |
| CDT | el resto: $(1 - w)(W - L)$ |

Si los pagos superan la riqueza ($L > W$), todo va al FIC y la diferencia se registra como déficit.

### Entre revisiones (cada mes)

- El FIC crece a la tasa del mes anterior, pasada a mensual: $\left(1 + r^{\text{FIC}}_{m-1}\right)^{1/12}$.
- El CDT crece a la tasa fijada al comprarlo: $\left(1 + r^{\text{CDT}}_\tau\right)^{1/12}$ por mes.
- El ETF vale las unidades compradas por su precio del mes.
- Se paga la cuota del mes en COP, $P_m \, \text{UVR}_m$ (con la UVR **real**), sacándola del FIC. Lo que falte es el
  déficit $D_m$.

En la siguiente revisión el CDT vence, todo se vuelve a sumar en $W$ y se repiten los tres pasos. Así el ETF vuelve
al 10 % y el FIC se ajusta a los pagos que vienen.

### Ejemplos (backtest con datos reales)

| Revisión | $W$ | $L$ (pagos de los próximos 6 meses) | FIC | CDT | ETF |
|---|---|---|---|---|---|
| oct-2016 (gracia) | 760,0M | 0 | 0 | 684,0M | 76,0M |
| oct-2019 (antes de la primera cuota) | 906,5M | 33,6M | 33,6M | 785,6M | 87,3M |

### Simplificaciones propias del plan 1

- **Plazo del CDT (S10):** se usa la tasa de 180 días aunque se pruebe $k$ = 3 o 12.
- Además aplican los supuestos comunes (S9, S10 para el FIC, S12, S13).

### Qué decide la regla y qué no

- **Dónde invertir:** los tres instrumentos son fijos, elegidos de antemano. La regla no compara alternativas.
- **Cuánto:** lo fijan solo los pagos próximos (FIC) y `equity_weight` (ETF). El 10 % es una elección, no el
  resultado de un cálculo.

## Plan 2 – Escalera de CDT optimizada

En lugar de poner todo en un CDT a 180 días (plan 1), escoge con un **programa lineal (LP)** cuánto invertir en CDT de
tasa fija a 3, 6 y 12 meses para que vayan venciendo cuando llegan los pagos. No hay renta variable. Los CDT y la caja
rinden sus tasas **reales** del BanRep; solo la decisión usa la inflación esperada.

### Instrumentos

| Instrumento | Rol | Dato que se usa (resultado) |
|---|---|---|
| **CDT a 3 meses** | Escalera | DTF a 90 días del mes de compra (serie 65) |
| **CDT a 6 meses** | Escalera | CDT a 180 días del mes de compra (serie 67) |
| **CDT a 12 meses** | Escalera | CDT a 360 días del mes de compra (serie 68) |
| **FIC a la vista** | Caja para los pagos que caen antes del siguiente vencimiento | DTF a 90 días |

### Cómo se decide en cada revisión $\tau$

Los pagos están fijos en UVR, así que el LP trabaja en UVR. Como los CDT pagan una tasa nominal, el LP necesita su
rendimiento en UVR, que no se conoce de antemano: usa el **esperado**, $\tilde r_j(\tau)$, con la inflación base
(`cdt_ladder.liquidity_scenario`).

1. **Datos (en UVR):**
   - los pagos $P_m$ de los meses $\tau+1, \dots, H$;
   - lo que vence de los CDT vivos, $M_m$: su valor al vencer en COP dividido por la UVR proyectada de ese mes;
   - el dinero libre $B$;
   - los rendimientos reales esperados $\tilde r_j(\tau)$ de cada plazo y $\rho_\tau$ de la caja.
2. **Variables:**
   - $y_{s,j} \ge 0$: compras en los meses de revisión $s = \tau, \tau + k, \dots$ con $s + j \le H$. Incluyen las
     reinversiones futuras previstas;
   - $c_m \ge 0$: caja al cierre de cada mes.
3. **Problema:**

$$
\begin{aligned}
\max_{y,\,c} \quad & c_H \\
\text{s.a.} \quad & c_\tau + \sum_j y_{\tau,j} = B \\
& c_m = c_{m-1}(1 + \rho_\tau)^{1/12} + \sum_j y_{m-j,\,j}\,\bigl(1 + \tilde r_j(\tau)\bigr)^{j/12} + M_m - \sum_j y_{m,j} - P_m,
  \quad m = \tau+1, \dots, H \\
& y_{s,j} \ge 0, \quad c_m \ge 0
\end{aligned}
$$

   Por S12, lo que vence en $m$ sirve para $P_m$.

4. **Ejecución:** solo se compran los $y_{\tau,j}$ de hoy, convertidos a COP con $\text{UVR}_\tau$; $c_\tau$ queda en
   el FIC. Cada CDT rinde después su tasa nominal **real** $r_j(\tau)$. En la siguiente revisión se vuelve a resolver
   con los CDT vivos como $M_m$.
5. **Sin escalera posible:** si con la inflación esperada el dinero libre no alcanza para todos los pagos, no se
   compra nada, todo queda en el FIC y los déficits se registran (S9).

### Ejemplos (backtest con datos reales)

| Revisión | Dinero libre | FIC | CDT 3 meses | CDT 6 meses | CDT 12 meses |
|---|---|---|---|---|---|
| oct-2016 (gracia) | 760,0M | 0 | 0 | 0 | 760,0M |
| oct-2019 (antes de la primera cuota) | 886,8M | 11,0M | 16,5M | 186,6M | 672,8M |

En oct-2016 las tasas eran 6,99 % (90 días), 7,24 % (180) y 8,18 % (360): sin pagos durante la gracia, todo va al
plazo más largo.

### Riesgo

Los CDT son de tasa fija: si la inflación supera la esperada, los pagos en COP crecen más que el dinero. Con la
inflación base, el backtest tiene 9 meses con déficit (1,85M COP en total); los mayores son sep-2025 (0,56M) y
sep-2026 (0,83M). En abr-2025 y abr-2026 no hubo escalera posible y el dinero quedó en el FIC.

### Simplificaciones propias del plan 2

- Los CDT se compran a la tasa promedio del mercado de su plazo (no a la de un banco concreto), por cualquier monto,
  solo en las revisiones, y se mantienen hasta el vencimiento.
- Además aplican los supuestos comunes.
