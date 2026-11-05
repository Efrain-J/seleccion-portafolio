# Reglas de inversión

Cómo se decide dónde y cuánto invertir en cada plan: el **plan 1 (conservador)**, el **plan 2 (escalera de CDT
optimizada)**, el **plan 3 (LDI: piso en CDT y crecimiento en ETF)** y el **plan 4 (plan 3 con filtro de
tendencia)**. Al final, una prueba de estrés repite el backtest con ETF que pierden dinero.

**Criterio de los resultados.** Las decisiones pueden usar estimaciones (por ejemplo, la inflación esperada), siempre
con datos conocidos en la fecha de la revisión. El dinero reportado sale solo de rendimientos observados de
instrumentos reales (tasas de CDT del BanRep, el índice de FIC de la Superfinanciera, precios de los ETF y la UVR):
ningún resultado es una cota ni usa un rendimiento supuesto.

Los códigos S1–S19 son los supuestos del proyecto, listados en
[`plan_proyecto_credito_uvr.md`](plan_proyecto_credito_uvr.md).

Código: `conservative_allocation`, `ladder_purchases`, `ladder_floor` e `inverse_volatility_weights` en
`src/uvr_loan/portfolio.py`. Simulación: `src/uvr_loan/backtest.py` (un plan por estrategia, en `PLANS`).
Parámetros: `config/assumptions.yaml`.

## Glosario

| Término | Significado |
|---|---|
| E.A. | Tasa efectiva anual: lo que rinde un peso en un año, con capitalización incluida |
| p.p. | Puntos porcentuales: de 4 % a 7 % son 3 p.p. |
| UVR | Unidad de Valor Real: unidad indexada a la inflación; el crédito y sus pagos están en UVR |
| Real | Medido en UVR, es decir, descontando la inflación: rendimiento real = $(1 + \text{nominal})/(1 + \pi) - 1$ |
| FIC | Fondo de Inversión Colectiva de mercado monetario: cuenta de la que se puede sacar dinero cualquier día |
| CDT | Certificado de Depósito a Término: depósito bancario a tasa fija; no se puede retirar antes de vencer |
| DTF | Tasa promedio de los CDT a 90 días |
| ETF | Fondo que replica un índice de acciones y se compra y vende como una acción |
| TRM | Tasa Representativa del Mercado: pesos por dólar |
| LP | Programa lineal: optimización con objetivo y restricciones lineales |
| LDI | Inversión guiada por los pasivos (*liability-driven investment*): primero se cubren los pagos, después se invierte el resto |
| CPPI | Seguro de portafolio de proporción constante: se arriesga solo un múltiplo del dinero que sobra sobre un piso |

## Notación común

**Convención de tiempo.** El tiempo se cuenta en meses desde $t_0$ (oct-2016, mes 0). El mes $m$ va del cierre del
mes $m-1$ al cierre del mes $m$; el pago $P_m$ y la $\text{UVR}_m$ son del cierre del mes $m$. Las revisiones son los
meses $\tau = 0, k, 2k, \dots$, así que la siguiente a $\tau$ es $\tau + k$ (no $\tau + 1$). Todo símbolo con subíndice
$\tau$ se calcula solo con datos conocidos al cierre del mes $\tau$. El orden dentro de un mes está en S12 (ver los supuestos
comunes).

**Unidades.** El dinero se mide en COP. Los LP de los planes 2 y 3 trabajan en UVR, porque los pagos están fijos en
UVR: el dinero libre se convierte con $\text{UVR}_\tau$ al entrar al LP y las compras se convierten a COP con
$\text{UVR}_\tau$ al ejecutarlas.

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $t_0$ | Fecha inicial del backtest (oct-2016), mes 0 | fecha | YAML `backtest.t0` |
| $m$ | Mes contado desde $t_0$, $m = 0, \dots, H$ | meses | columna `month` |
| $H$ | Horizonte: último mes del crédito (120) | meses | YAML `backtest.horizon_months` |
| $k$ | Meses entre revisiones (6) | meses | YAML `backtest.review_every_months` |
| $\tau$ | Mes de una revisión: $0, k, 2k, \dots, H - k$ | meses | función `decision_months` |
| $P_m$ | Pago total del mes $m$ (cuota + abono), de la tabla de amortización | UVR | columna `total_payment_uvr` |
| $\text{UVR}_m$ | Valor observado de la UVR al cierre del mes $m$ | COP por UVR | columna `uvr_cop` |
| $\pi^{\text{base}}_\tau$ | Inflación base en $\tau$: la de los últimos 6 meses, anualizada (S14) | decimal E.A. | función `trailing_inflation` |
| $\pi_\tau$ | Inflación con la que deciden los planes en $\tau$ (ver abajo) | decimal E.A. | función `scenarios` |
| $\widehat{\text{UVR}}_{m\mid\tau}$ | UVR proyectada en $\tau$ para el mes $m > \tau$ | COP por UVR | función `project_uvr` |
| $r^{\text{FIC}}_m$ | Rentabilidad **realizada** del FIC durante el mes $m$ (índice de FIC de mercado monetario) | decimal mensual | columna `fic_ret_m` |
| $\bar r^{\text{FIC}}_m$ | La misma, anualizada: conocida al cierre del mes $m$, se usa para decidir | decimal E.A. | columna `fic_rate_ea` |
| $r_j(\tau)$ | Tasa observada del CDT de plazo $j$ meses comprado en $\tau$ ($j$ = 3, 6, 12: DTF, CDT 180 y 360 días) | decimal E.A. | columnas `cdt_90d_ea`, `cdt_180d_ea`, `cdt_360d_ea` |
| $F_m$ | Saldo del FIC al cierre del mes $m$ (después de crecer, recibir lo que vence y pagar; si $m$ es revisión, después de reasignar) | COP | columna `fic_cop` |
| $W_\tau$ | Dinero libre en $\tau$: FIC + ETF a precio de mercado (lo que vence en $\tau$ ya está en el FIC; los CDT vivos no cuentan) | COP | variable `free_cop` |
| $E_m$ | Valor de los ETF al cierre del mes $m$, a precio de mercado (suma de todos; cada uno en `<nombre>_cop`; si $m$ es revisión, después de reasignar) | COP | columna `etf_cop` |
| $\text{CDT}_m$ | Valor acumulado de los CDT vivos al cierre del mes $m$ | COP | columna `cdt_cop` |
| $D_m$ | Déficit del mes $m$: parte del pago que no cubren ni el FIC ni el ETF | COP | columna `shortfall_cop` |

**Definiciones:**

$$
\pi^{\text{base}}_\tau = \left(\frac{\text{UVR}_\tau}{\text{UVR}_{\tau-6}}\right)^{12/6} - 1
\qquad
\widehat{\text{UVR}}_{m\mid\tau} = \text{UVR}_\tau\,(1 + \pi_\tau)^{(m-\tau)/12}
\qquad
\bar r^{\text{FIC}}_m = \bigl(1 + r^{\text{FIC}}_m\bigr)^{12} - 1
$$

En $\pi^{\text{base}}_\tau$, el 6 es `inflation_scenarios.base_lookback_months` (no $k$) y el exponente $12/6$ anualiza
la inflación de esos 6 meses; en $\tau = 0$ usa la UVR de abr-2016, anterior a $t_0$.

**Escenario de inflación de los planes.** Los planes deciden con
$\pi_\tau = \pi^{\text{alto}}_\tau = \pi^{\text{base}}_\tau + 0{,}03$: es el margen para el riesgo de que la inflación
supere lo esperado. Todos usan el mismo, para que sus resultados se puedan comparar. La base es la referencia del
escenario alto; el código también calcula un escenario bajo ($\pi^{\text{base}}_\tau - 0{,}015$), que ningún plan
usa.

| Plan | $\pi_\tau$ | Para qué | YAML |
|---|---|---|---|
| 1 | $\pi^{\text{alto}}_\tau$ | Proyectar los pagos que guarda el FIC | `conservative.fic_sizing_scenario` |
| 2 | $\pi^{\text{alto}}_\tau$ | Pasar las tasas nominales a reales en el LP | `cdt_ladder.deflator_scenario` |
| 3 | $\pi^{\text{alto}}_\tau$ | Calcular el piso y comprar la escalera | `ldi.floor_scenario` |
| 4 | $\pi^{\text{alto}}_\tau$ | Igual que el plan 3 | `ldi.floor_scenario` |

Nota: el test `test_plans_use_the_same_inflation_scenario` (`tests/test_inflation.py`) avisa si las tres claves del
YAML difieren.

### Medidas de resultado

- **Riqueza:** $F_m + \text{CDT}_m + E_m$ (columna `wealth_cop`). La riqueza final es lo que queda después de pagar
  todo el crédito, por eso puede ser menor que el capital inicial.
- **Liquidez:** FIC + ETF, $F_m + E_m$; los CDT no son liquidez hasta que vencen (métrica
  `min_liquid_at_payment_cop`).
- **Déficit:**

$$
D_m = \max\bigl(P_m\,\text{UVR}_m - F^{-}_m - E^{-}_m,\ 0\bigr)
$$

  donde $F^{-}_m$ es el saldo del FIC en el mes $m$ después de crecer y recibir lo que vence, y antes de pagar, y
  $E^{-}_m$ el valor del ETF a precio del mes $m$ antes de pagar.
- **Riqueza neta:** riqueza menos el déficit acumulado, $F_m + \text{CDT}_m + E_m - \sum_{m' \le m} D_{m'}$ (un pago
  sin cubrir sigue debiéndose; columna `wealth_net_cop`).

## Supuestos comunes a todos los planes

### Reglas de operación

- **Orden dentro de un mes (S12):** primero crecen los activos, luego vencen los CDT, luego se paga la cuota y, si es
  mes de revisión, se decide. Un CDT que vence en el mes $m$ sirve para el pago del mes $m$. Si el primer CDT que
  vence después de $\tau$ lo hace en el mes $m^\star$, la caja de hoy solo debe cubrir los pagos
  $\tau+1, \dots, m^\star-1$: el CDT que vence en $m^\star$ paga $P_{m^\star}$.
- **Solo se compra en las revisiones (S13):** lo que vence entre $\tau$ y $\tau + k$ y no se usa para pagar queda en
  el FIC hasta la siguiente revisión.
- **Sin información futura:** en cada revisión la estrategia recibe los datos solo hasta $\tau$.
- **Liquidez y déficit (S9):** el pago sale primero del FIC; si no alcanza, se venden unidades de los ETF al precio de
  ese mes (columna `etf_sold_cop`). Si hay varios ETF, se vende de cada uno en proporción a su valor (a prorrata), así
  las proporciones entre ETF no cambian hasta la siguiente revisión. Solo si el FIC y los ETF juntos no alcanzan se registra el déficit
  $D_m$. Los CDT nunca se redimen antes del vencimiento. Los ETF se tratan como liquidez en tiempo, pero no en valor:
  se venden al precio del mes, que puede estar en pérdida.
- **Sin costos ni impuestos (S3, S6):** comprar, vender y rebalancear no cuesta nada.

### Datos y supuestos de mercado

- **Inflación proyectada (S14):** la base es la inflación de los últimos 6 meses medida con la UVR
  ($\pi^{\text{base}}_\tau$). Es un modelo provisional hasta que exista el modelo de inflación (`scenarios` en
  `src/uvr_loan/inflation.py`). Con 6 meses la base tiene estacionalidad: en abril ve los meses de inflación alta de
  comienzo de año y en octubre los de inflación baja.
- **FIC:** rinde lo que rindió un índice de los FIC de mercado monetario reales: el valor de la unidad de cada fondo,
  publicado a diario por la Superfinanciera, promediado según el tamaño de cada fondo. Ver `data/SOURCES.md`.
- **Venta inmediata, sin deslizamiento (S16):** cualquier ETF se vende al precio de cierre del mes en que se necesita
  el dinero, sin diferencia entre precio de compra y de venta. Para un ETF en dólares, la venta, la conversión a pesos
  y el traslado a Colombia ocurren en ese mismo mes (en la realidad tardan de 1 a 3 días hábiles).
- **Conversión a la TRM (S17):** valor en COP = unidades × precio ajustado en USD × TRM de cierre del mes (BanRep,
  serie 1), sin margen cambiario.
- **Acceso (S18):** desde oct-2016 un residente colombiano puede comprar el ETF extranjero en un bróker del exterior,
  por cualquier monto y en fracciones de unidad, y mover el dinero sin límites ni trámites.
- **Sin cobertura cambiaria (S19):** la exposición al dólar se mantiene.
- **Impuestos del ETF irlandés (nota a S3):** la retención del 15 % que el fondo irlandés paga en EE. UU. sobre los
  dividendos está dentro de su precio, como su comisión. El modelo no la separa, así que no contradice S3.

## Plan 1 – Conservador

Es una regla fija, no una optimización, y solo usa renta fija: FIC y CDT, sin renta variable (como el perfil
conservador del plan del proyecto). No usa rentabilidades esperadas ni volatilidades: sirve como punto de comparación
para los planes más elaborados. Los dos instrumentos están elegidos de antemano y la regla no compara alternativas;
los montos los fijan solo los pagos próximos (FIC), `cdt_weight` (CDT) y `grace_cdt_weight` (CDT durante la gracia).
El 90 % es una elección, no el resultado de un cálculo.

### Instrumentos

| Instrumento | Rol | Dato que se usa |
|---|---|---|
| **FIC a la vista** | Liquidez para las cuotas y una parte fija del resto | Índice de FIC de mercado monetario (Superfinanciera) |
| **CDT a 180 días** | Renta fija; vence justo en la siguiente revisión | $r_6(\tau)$: tasa observada del CDT a 180 días del mes de compra |

Las fuentes de cada serie están en [`data/SOURCES.md`](../data/SOURCES.md).

### Notación del plan 1

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $L_\tau$ | Necesidad de liquidez en $\tau$: pagos hasta que venza el nuevo CDT | COP | función `projected_payments_cop` |
| $\theta$ | Parte de $W_\tau - L_\tau$ que va al CDT (0,90; 1,00 en las revisiones de la gracia, `grace_cdt_weight`); el resto queda en el FIC | decimal | YAML `conservative.cdt_weight` |

### En cada revisión $\tau$

Las revisiones son cada $k$ = `backtest.review_every_months` meses (hoy 6), desde `backtest.t0`: oct-2016, abr-2017,
oct-2017, …, abr-2026.

**Paso 1: cuánto dinero libre hay ($W_\tau$).** $W_\tau$ = saldo del FIC, que ya incluye el CDT que vence ese mes (el
plan 1 no tiene ETF). En $t_0$, $W_0$ = 760.000.000 COP (`initial_capital_cop`).

**Paso 2: cuánto se necesita hasta que venza el nuevo CDT ($L_\tau$).** El CDT que se compra hoy vence en $\tau + k$
y, por S12, paga $P_{\tau+k}$. El FIC solo cubre los pagos anteriores:

$$
L_\tau = \sum_{m=\tau+1}^{\tau+k-1} P_m\,\widehat{\text{UVR}}_{m\mid\tau}
$$

con la UVR proyectada con $\pi_\tau = \pi^{\text{alto}}_\tau$ (`conservative.fic_sizing_scenario`, ver la notación
común; en oct-2016, 4,34 % + 3 p.p. = 7,34 %).

**Paso 3: repartir $W_\tau$.**

| Instrumento | Monto |
|---|---|
| CDT | $\theta\,(W_\tau - L_\tau)$, con $\theta$ = 90 % hoy |
| FIC | el resto: $L_\tau + (1 - \theta)(W_\tau - L_\tau)$ |

**Durante la gracia:** mientras no hay pagos en $\tau+1, \dots, \tau+k-1$, $L_\tau = 0$ y no hace falta colchón, así
que se usa $\theta$ = 100 % (`conservative.grace_cdt_weight`) y todo el dinero va al CDT. La primera cuota es la del
mes 37 (nov-2019): esto aplica a las revisiones con $\tau$ < 36 (oct-2016 a abr-2019). Desde la revisión de oct-2019
($\tau$ = 36) se usa el 90 %.

Si los pagos proyectados superan el dinero libre ($L_\tau > W_\tau$), la fórmula del CDT daría un monto negativo: en
ese caso el CDT recibe 0 y todo queda en el FIC. La parte que no alcanza solo se convierte en déficit $D_m$ si al
llegar el pago el FIC no lo cubre.

### Entre revisiones (cada mes)

- El FIC crece con su rentabilidad realizada del mes y recibe lo que vence:
  $F^{-}_m = F_{m-1}\,(1 + r^{\text{FIC}}_m) + (\text{CDT que vencen en } m)$.
- El CDT crece a la tasa fijada al comprarlo: $\bigl(1 + r_6(\tau)\bigr)^{1/12}$ por mes.
- Se paga la cuota del mes en COP, $P_m\,\text{UVR}_m$ (con la UVR **observada**), sacándola del FIC. Como el plan 1
  no tiene ETF, lo que falte es el déficit $D_m$.

En la siguiente revisión el CDT vence, entra al FIC, paga el pago de ese mes y lo que queda forma el nuevo $W_\tau$.
Así el FIC se ajusta a los pagos que vienen y el CDT vuelve a ser el 90 % del resto.

### Ejemplos (backtest con datos reales)

| Revisión | $W_\tau$ | $L_\tau$ (pagos de $\tau+1$ a $\tau+k-1$) | FIC | CDT |
|---|---|---|---|---|
| oct-2016 (gracia, $\theta$ = 100 %) | 760,0M | 0 | 0 | 760,0M |
| oct-2019 (antes de la primera cuota, $\theta$ = 90 %) | 897,6M | 27,9M | 114,9M | 782,7M |

### Riesgo y resultados

- Sin meses con déficit y riqueza final de 701,0M.
- El 10 % que queda en el FIC además de $L_\tau$ funciona como colchón: el saldo mínimo del FIC en un mes de pago fue
  71,8M. A cambio, ese dinero rinde lo del FIC y no lo del CDT.

### Simplificaciones propias del plan 1

- **Plazo del CDT (S10):** el CDT es siempre a 180 días. Con $k$ = 6 (el caso base) vence justo en la siguiente
  revisión; si se prueba $k$ = 3 o 12, se sigue usando la tasa de 180 días como si el CDT venciera en $\tau + k$.
- Además aplican los supuestos comunes.

## Plan 2 – Escalera de CDT optimizada

En lugar de poner todo en un CDT a 180 días (plan 1), escoge con un **programa lineal (LP)** cuánto invertir en CDT de
tasa fija a 3, 6 y 12 meses para que vayan venciendo cuando llegan los pagos. No hay renta variable. Los CDT y la caja
rinden sus tasas **observadas** (BanRep e índice de FIC); solo la decisión usa la inflación esperada.

### Instrumentos

| Instrumento | Rol | Dato que se usa |
|---|---|---|
| **CDT a 3 meses** | Escalera | $r_3(\tau)$: DTF del mes de compra (serie 65) |
| **CDT a 6 meses** | Escalera | $r_6(\tau)$: CDT a 180 días del mes de compra (serie 67) |
| **CDT a 12 meses** | Escalera | $r_{12}(\tau)$: CDT a 360 días del mes de compra (serie 68) |
| **FIC a la vista** | Caja para los pagos que caen antes del siguiente vencimiento | Índice de FIC de mercado monetario (Superfinanciera) |

### Notación del plan 2

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $j$ | Plazo de un CDT: 3, 6 o 12 | meses | YAML `cdt_ladder.term_columns` |
| $\tilde r_j(\tau)$ | Rentabilidad real **esperada** del CDT de plazo $j$ (solo para decidir) | decimal E.A. | variable `cdt_real_ea` |
| $\rho_\tau$ | Rentabilidad real **esperada** de la caja (solo para decidir) | decimal E.A. | variable `fic_real_ea` |
| $\mathcal R_\tau$ | Meses en que se puede comprar: $\{\tau, \tau + k, \tau + 2k, \dots\}$ | meses | – |
| $y_{s,j}$ | Monto invertido en el mes $s \in \mathcal R_\tau$ en un CDT de plazo $j$, con $s + j \le H$ | UVR | variable del LP |
| $c_m$ | Caja (FIC) al cierre del mes $m$ dentro del LP | UVR | variable del LP |
| $M_m$ | Lo que vence en el mes $m$ de los CDT comprados antes de $\tau$ | UVR | variable `maturities_uvr` |
| $B_\tau$ | Presupuesto del LP: dinero libre en $\tau$, en UVR | UVR | variable `budget_uvr` |

$$
\tilde r_j(\tau) = \frac{1 + r_j(\tau)}{1 + \pi_\tau} - 1
\qquad
\rho_\tau = \frac{1 + \bar r^{\text{FIC}}_\tau}{1 + \pi_\tau} - 1
\qquad
B_\tau = \frac{W_\tau}{\text{UVR}_\tau}
$$

$$
M_m = \sum_{\text{CDT vivos que vencen en } m} \frac{\text{VF}}{\widehat{\text{UVR}}_{m\mid\tau}}
\qquad (M_m = 0 \text{ si } m \le \tau)
$$

donde $\text{VF}$ es el valor de cada CDT al vencer, en COP: capital $\times\,(1 +
\text{tasa})^{\text{plazo}/12}$.

$c_m$ es la caja que **planea** el LP, en UVR; el saldo real del FIC es $F_m$, en COP. Solo $c_\tau$ pasa a la
realidad (ver paso 2).

### En cada revisión $\tau$

En cada revisión se resuelve un LP que reparte el dinero libre entre el FIC y CDT a 3, 6 y 12 meses, de modo que los
CDT venzan cuando llegan los pagos y quede la mayor cantidad posible de dinero al final del crédito. Como los CDT y el
FIC pagan en pesos y el LP trabaja en UVR, necesita su rendimiento en UVR, que no se conoce de antemano: usa el
**esperado**, $\tilde r_j(\tau)$ y $\rho_\tau$, con $\pi_\tau = \pi^{\text{alto}}_\tau$
(`cdt_ladder.deflator_scenario`).

**Datos y variables del LP.**

- **Fijo (datos, en UVR):** los pagos $P_m$ de los meses $\tau+1, \dots, H$; lo que vence de los CDT vivos, $M_m$; el
  dinero libre $B_\tau$; los rendimientos reales esperados $\tilde r_j(\tau)$ y $\rho_\tau$.
- **Se decide (variables):** las compras de hoy $y_{\tau,j}$; las compras previstas en las revisiones futuras
  $y_{s,j}$, $s = \tau + k, \tau + 2k, \dots$ (solo si $s + j \le H$, es decir, si el CDT vence antes del final); y la
  caja $c_m$ al cierre de cada mes, después de pagar.

**Por qué el LP incluye compras futuras.** Solo se ejecutan las compras de hoy. Sin las futuras, el dinero de un CDT
corto que vence quedaría en la caja hasta el final, rindiendo $\rho_\tau$, y el LP subvaloraría los CDT cortos frente a
los largos. Con ellas, el LP sabe que ese dinero se puede volver a invertir en CDT en la siguiente revisión. Para
decidir, esas compras futuras se suponen a las tasas reales de hoy (ver "Simplificaciones"); no se ejecutan: en la
siguiente revisión el LP se resuelve otra vez con los datos nuevos.

**Paso 1: resolver el LP.** El objetivo es maximizar $c_H$, la caja que queda al final del crédito, en UVR, después de
pagar todas las cuotas:

$$
\begin{aligned}
\max_{y,\,c} \quad & c_H \\
\text{s.a.} \quad & c_\tau + \sum_j y_{\tau,j} = B_\tau \\
& c_m = c_{m-1}(1 + \rho_\tau)^{1/12} + \sum_j y_{m-j,\,j}\,\bigl(1 + \tilde r_j(\tau)\bigr)^{j/12} \\
& \qquad\quad + M_m - \sum_j y_{m,j} - P_m, \qquad m = \tau+1, \dots, H \\
& y_{s,j} \ge 0, \quad c_m \ge 0
\end{aligned}
$$

Cómo se lee:

- **Primera restricción:** el presupuesto de hoy se reparte entre la caja y las compras de hoy, así que $c_\tau$ es la
  caja que queda después de comprar.
- **Una restricción por mes $m$:** la caja del mes es la del mes anterior, con su rendimiento, más lo que vence (CDT
  comprados en el LP y CDT vivos), menos lo que se compra ese mes y menos el pago. Por S12, lo que vence en $m$ sirve
  para $P_m$.
- **$c_m \ge 0$:** la caja nunca es negativa, es decir, todos los pagos se cubren.
- **Índices:** solo hay compras en los meses de revisión, así que $y_{s,j} = 0$ si $s \notin \mathcal R_\tau$ o si
  $s + j > H$. En la restricción del mes $m$, $y_{m-j,j}$ es lo que vence (comprado en $m - j \ge \tau$) e $y_{m,j}$ lo
  que se compra ese mes, después de pagar $P_m$.

Si $B_\tau$ es menor que la menor cantidad que cubre todos los pagos con $c_m \ge 0$, el LP no tiene solución (esa
cantidad mínima es el piso del plan 3).

**Desempate:** si varias soluciones dejan la misma $c_H$ (pasa sobre todo en la gracia, donde dos CDT a 6 meses
seguidos rinden casi lo mismo que uno a 12), se resuelve un segundo LP: entre las soluciones que alcanzan ese $c_H$, se
minimiza $\sum_j j\,y_{\tau,j}$, es decir, se elige la compra de hoy con los plazos más cortos. Así la compra no depende
del método del solver.

**Paso 2: ejecutar.** De la solución del LP solo se llevan a la realidad las compras de hoy $y_{\tau,j}$, convertidas a
COP con $\text{UVR}_\tau$, y $c_\tau$, que queda en el FIC. Las demás variables ($c_m$ para $m > \tau$ y las compras
futuras) son un plan, no saldos reales. Cada CDT rinde después su tasa observada $r_j(\tau)$.

**Sin escalera posible:** si el LP no tiene solución, no se compra nada, todo queda en el FIC y los déficits se
registran (S9). Cualquier otra falla del solver detiene el backtest con un error, para que no se confunda con este
caso.

**En la siguiente revisión** ($\tau + k$) se arma un LP nuevo con la misma forma:

- el horizonte empieza en el nuevo $\tau$, así que hay menos meses y menos fechas de compra;
- los CDT comprados antes que siguen vivos entran como vencimientos fijos $M_m$;
- el presupuesto es el dinero libre nuevo;
- las tasas $r_j$ y el rendimiento del FIC son los observados en el nuevo $\tau$, y la inflación esperada se calcula
  otra vez.

### Entre revisiones (cada mes)

- El FIC crece con su rentabilidad realizada del mes, $r^{\text{FIC}}_m$.
- Cada CDT crece a la tasa fijada al comprarlo, $r_j(\tau)$, y al vencer entra al FIC; lo que no se usa para pagar
  espera en el FIC hasta la siguiente revisión (S13).
- Se paga la cuota del mes en COP, $P_m\,\text{UVR}_m$ (con la UVR **observada**), sacándola del FIC. Como el plan 2
  no tiene ETF, lo que falte es el déficit $D_m$.

### Ejemplos (backtest con datos reales)

| Revisión | Dinero libre | FIC | CDT 3 meses | CDT 6 meses | CDT 12 meses |
|---|---|---|---|---|---|
| oct-2016 (gracia) | 760,0M | 0 | 0 | 198,4M | 561,6M |
| oct-2019 (antes de la primera cuota) | 678,8M | 11,0M | 16,6M | 4,5M | 646,6M |

En oct-2016 las tasas eran 6,99 % (90 días), 7,24 % (180) y 8,18 % (360): sin pagos durante la gracia, casi todo va al
plazo más largo. En oct-2019 el dinero libre es menor que la riqueza total porque hay CDT comprados antes que siguen
vivos.

### Riesgo y resultados

- Los CDT son de tasa fija: si la inflación supera la esperada, los pagos en COP crecen más que el dinero.
- El backtest tiene 2 meses con déficit, ambos muy pequeños: jun-2021 (38.611 COP) y jun-2022
  (9.503 COP), 48.114 COP en total.
- En abr-2026 no hubo escalera posible y el dinero quedó en el FIC.
- La riqueza final es 780,1M y la riqueza neta también es 780,1M: los 48.114 COP de déficit no se ven al redondear.

### Simplificaciones propias del plan 2

- Los CDT se compran a la tasa promedio del mercado de su plazo (no a la de un banco concreto), por cualquier monto,
  solo en las revisiones, y se mantienen hasta el vencimiento.
- **Pronóstico de la caja (S15):** para decidir, el LP supone que el FIC seguirá rindiendo, durante todo el horizonte,
  lo mismo que rindió el último mes, anualizado ($\bar r^{\text{FIC}}_\tau$). Así obtiene $\rho_\tau$ y lo compara con
  los CDT. Como la caja y los CDT se descuentan con la misma inflación, preferir la caja depende solo de comparar
  $\bar r^{\text{FIC}}_\tau$ con las $r_j(\tau)$ del día. Ver la validación abajo.
- **Compras futuras a las tasas de hoy:** el LP supone que las compras de revisiones futuras se harán a las tasas
  reales de hoy; en cada revisión se corrige con las tasas nuevas.
- Además aplican los supuestos comunes.

### Validación del pronóstico de la caja

Evaluado contra lo que pasó en los 6 meses siguientes a cada revisión (error = pronóstico − realizado):

- acierta en 17 de 20 revisiones cuál rinde más, la caja o el CDT a 180 días. Falla en abr-2020 (prácticamente un
  empate) y en abr-2022 y oct-2022, cuando el BanRep subía tasas y el FIC, que sigue las tasas mes a mes, le ganó a
  los CDT comprados a la tasa anterior;
- el error absoluto medio del rendimiento nominal del FIC es 1,29 p.p. y tiende a subestimarlo (−0,78 p.p. en
  promedio) cuando las tasas suben; el mayor error fue 5,87 p.p. en oct-2022;
- el error de $\rho_\tau$ es mayor, 3,57 p.p. en promedio, y viene sobre todo de la inflación, no del FIC: el
  escenario alto lo sesga a propósito hacia abajo (−3,44 p.p. en promedio, es decir, es pesimista);
- **si el último mes del FIC fue negativo**, $\rho_\tau$ queda muy negativo (oct-2021:
  $\bar r^{\text{FIC}}_\tau$ = −0,91 % E.A., $\rho_\tau$ = −8,81 % E.A.). El LP no falla: guarda en caja solo lo
  indispensable, aparta un poco más para compensar la pérdida esperada y pone el resto en CDT. Después de oct-2021 el
  FIC rindió +2,69 %, así que el pronóstico fue pesimista, sin costo. El caso que sí puede afectar es el contrario
  (pronóstico positivo y mes real negativo), en el que la caja queda un poco corta; el índice solo tuvo 4 meses
  negativos en 10 años (el peor, −0,16 % mensual). No se pone un piso al pronóstico.

## Plan 3 – LDI: piso en CDT y crecimiento en ETF

Es un plan de inversión guiada por los pasivos (*liability-driven investment*, LDI). Divide el dinero en dos partes:

1. **Una parte protegida:** una escalera de CDT (la del plan 2) que cubre **todos** los pagos que faltan del crédito.
2. **Una parte de crecimiento:** acciones (ICOLCAP y CSPX), compradas solo con el dinero que sobra por encima de esa
   protección.

Los ETF solo reciben dinero que sobra sobre la protección. Por eso, aunque los ETF perdieran el 100 %, la escalera
seguiría cubriendo los pagos, mientras la inflación no supere el escenario alto con el que se calcula. Es la forma más simple de la regla CPPI (*constant proportion portfolio insurance*),
con multiplicador $\kappa = 1$.

### Instrumentos

| Instrumento | Rol | Dato que se usa |
|---|---|---|
| **CDT a 3, 6 y 12 meses** | Cobertura: escalera del LP del plan 2 | $r_j(\tau)$: DTF, CDT 180 y 360 días (series 65, 67, 68) |
| **FIC a la vista** | Caja de la escalera | Índice de FIC de mercado monetario (Superfinanciera) |
| **ICOLCAP** | Crecimiento: renta variable colombiana | Precio ajustado en COP (Yahoo, `ICOLCAP.CL`) |
| **CSPX** | Crecimiento: S&P 500 (iShares Core S&P 500 UCITS, irlandés, de acumulación) | Precio ajustado en USD (Yahoo, `CSPX.L`) × TRM |

CSPX se escogió con información de 2016: diversifica fuera de Colombia (su correlación con ICOLCAP es baja), existe
desde 2010 y su precio ya incluye la retención del 15 % sobre los dividendos, que es lo que de verdad recibe un
inversionista colombiano. Los TES (UVR y tasa fija) quedan como tema pendiente para todos los planes.

### Notación del plan 3

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $B^{\min}_\tau$ | **Piso**: el menor presupuesto con el que una escalera cubre todos los pagos que faltan | UVR | función `ladder_floor` |
| $\Pi_\tau$ | El piso en pesos: $B^{\min}_\tau\,\text{UVR}_\tau$ | COP | columna `floor_cop` |
| $b$ | Margen sobre el piso (5 %) | decimal | YAML `ldi.floor_buffer` |
| $\kappa$ | Multiplicador de la regla CPPI (aquí $\kappa = 1$) | – | – |
| $\mathcal A$ | Conjunto de ETF de crecimiento: {ICOLCAP, CSPX}; $i, l \in \mathcal A$ | – | YAML `ldi.growth_assets` |
| $G_\tau$ | Parte de crecimiento (dinero para los ETF) en $\tau$ | COP | variable `growth_cop` |
| $w_i$ | Peso del ETF $i$ dentro de $G_\tau$ (suman 1) | decimal | función `inverse_volatility_weights` |
| $\sigma_i(\tau)$ | Volatilidad anual del ETF $i$: desviación estándar muestral de sus últimos 36 rendimientos mensuales en COP × $\sqrt{12}$, con datos hasta $\tau$ (YAML `data.vol_window_months`; ICOLCAP desde mayo de 2013 y CSPX desde 2013, así que en oct-2016 ya hay 36 meses) | decimal | columnas `<nombre>_vol_ea` |

Los símbolos parecidos son cosas distintas: $\Pi_\tau$ es el piso, $\pi_\tau$ la inflación y $P_m$ el pago; $b$ es el
margen y $B$ el presupuesto del LP.

### En cada revisión $\tau$

**Paso 1: calcular el piso.** El piso $\Pi_\tau$ es la menor cantidad de dinero que, invertida en una escalera de CDT
a 3, 6 y 12 meses más el FIC, cubre **todos** los pagos que faltan hasta el final del crédito. Lo calcula un programa
lineal (LP) en UVR, la unidad del crédito:

- Usa las tasas de CDT de hoy y el rendimiento del FIC, pasados a rendimientos reales ($\tilde r_j(\tau)$ y
  $\rho_\tau$) con el escenario de inflación **alto**, $\pi^{\text{alto}}_\tau$ (`ldi.floor_scenario`).
- Los CDT comprados en revisiones anteriores que todavía no vencen cuentan como dinero ya reservado: el piso solo
  cubre lo que ellos no cubren.

Es el LP del plan 2 con el objetivo cambiado: en vez de maximizar $c_H$ con el presupuesto dado, el presupuesto $B$
es una variable más y se minimiza, exigiendo igual que todos los pagos se cubran ($c_m \ge 0$):

$$
\begin{aligned}
B^{\min}_\tau = \min_{B,\,y,\,c} \quad & B \\
\text{s.a.} \quad & c_\tau + \sum_j y_{\tau,j} = B, \qquad B \ge 0
\end{aligned}
$$

y las mismas restricciones de cada mes y de signo del LP del plan 2. Después, $\Pi_\tau = B^{\min}_\tau\,\text{UVR}_\tau$.
El piso es lo que de verdad costaría la escalera, así que no hace falta suponer una tasa para descontar los pagos.

**Paso 2: comprar la escalera.** La escalera recibe $\min\bigl(W_\tau,\ (1 + b)\,\Pi_\tau\bigr)$: normalmente
$(1 + b)\,\Pi_\tau$, el piso más un margen $b$ = 5 %. Con ese presupuesto se resuelve el LP del plan 2
(`ladder_purchases`, mismas tasas del escenario alto). No basta con comprar la solución del LP del piso, porque esa
solución gasta exactamente $\Pi_\tau$: el margen también hay que invertirlo, y el LP del plan 2 decide cómo se reparte
todo el presupuesto, margen incluido, entre los plazos de CDT y el FIC (una parte pequeña queda en el FIC para los
meses entre vencimientos). $W_\tau$ no incluye los CDT vivos: ellos ya están descontados del piso como vencimientos
$M_m$, por eso se compara $W_\tau$ con el piso.

**Paso 3: poner el resto en acciones.** Todo lo que pasa de $(1 + b)\,\Pi_\tau$ va a los ETF:

$$
G_\tau = \kappa\,\Bigl[W_\tau - \min\bigl(W_\tau,\ (1 + b)\,\Pi_\tau\bigr)\Bigr], \qquad \kappa = 1
$$

Con $\kappa = 1$ los ETF reciben exactamente lo que sobra, nunca dinero de la escalera. $G_\tau$ se reparte en
proporción inversa a la volatilidad (el ETF menos volátil recibe más, así cada uno aporta más o menos el mismo
riesgo):

$$
w_i = \frac{1/\sigma_i(\tau)}{\sum_{l \in \mathcal A} 1/\sigma_l(\tau)}, \qquad i \in \mathcal A
$$

Con estos pesos, $w_i\,\sigma_i(\tau)$ es igual para todos los ETF. Con dos ETF eso significa que cada uno aporta el
mismo riesgo a la parte de crecimiento, sin importar la correlación (paridad de riesgo); con más de dos solo es cierto
si todas las correlaciones son iguales. Se venden o compran ETF hasta que cada uno tenga $w_i\,G_\tau$.

**La parte en ETF no es un monto fijo: se recalcula en cada revisión.** En cada revisión se suman el FIC y el valor de
mercado de los ETF (el dinero libre $W_\tau$), se calcula el piso nuevo y se reparte todo otra vez. Si la escalera
necesita más dinero, sale de vender ETF. Si los ETF subieron, la ganancia se queda en ETF, porque el piso solo depende
de los pagos. Como cada cuota pagada baja el piso, todo lo que el piso libera va a los ETF, y por eso la parte en ETF
crece con el tiempo.

**La parte en ETF puede ser cero.** Si $W_\tau$ es menor que $(1 + b)\,\Pi_\tau$, no va nada a los ETF. Si es
menor que el piso, no hay escalera posible: todo queda en el FIC y los déficits se registran, como en el plan 2. Con
los datos reales esto no pasó.

### Entre revisiones (cada mes)

- El FIC crece con su rentabilidad realizada del mes, $r^{\text{FIC}}_m$.
- Cada CDT crece a la tasa fijada al comprarlo, $r_j(\tau)$, y al vencer entra al FIC; lo que no se usa para pagar
  espera en el FIC hasta la siguiente revisión (S13).
- El pago del mes sale del FIC. Los ETF se mantienen sin rebalancear y solo se venden (a prorrata, S9) si el FIC no
  alcanza.

### Ejemplos (backtest con datos reales)

| Revisión | $W_\tau$ | Piso $\Pi_\tau$ (COP) | $\Phi_\tau$ | Escalera (CDT + FIC) | ICOLCAP | CSPX |
|---|---|---|---|---|---|---|
| oct-2016 | 760,0M | 419,9M | 1,81 | 440,9M | 161,2M | 157,9M |
| oct-2019 | 755,4M | 261,9M | 1,96 | 275,0M | 233,4M | 246,9M |

En oct-2016 la inflación alta era 7,34 % (4,34 % + 3 p.p.); la escalera compró 198,4M en CDT a 6 meses (7,24 %) y
242,5M a 12 meses (8,18 %). Las volatilidades eran 17,7 % (ICOLCAP) y 18,0 % (CSPX), así que los pesos quedaron casi
iguales (50,5 % y 49,5 %). En oct-2019 $W_\tau$ no incluye los CDT comprados antes que siguen vivos (su valor más el de
la escalera nueva suma 513,6M en CDT y 11,0M en el FIC); por eso el piso es menor que en 2016 aunque faltan los mismos
pagos. $\Phi_\tau$ es el indicador de cobertura (ver el final de "Riesgo y resultados").

### Riesgo y resultados

- Sin meses con déficit. Dos veces el FIC quedó corto por muy poco y se vendieron ETF: jun-2021 (41.468 COP) y jun-2022
  (9.651 COP).
- La protección de los pagos la comprueba un test: los ETF pierden 99 % y no falta ningún pago
  (`test_a_crash_of_the_etfs_does_not_reach_the_payments`).
- Riqueza final 1.352,5M (plan 1: 701,0M; plan 2: 780,1M). Rentabilidad anual 11,9 %, volatilidad 8,3 %, máxima caída
  7,1 % (los planes 1 y 2 tienen volatilidad cercana a 1 % y no tienen caídas).
- La protección de los pagos no depende del mercado accionario (siempre está la escalera con $(1 + b)$ × piso); la
  riqueza final sí.
- **El riesgo no entra en la decisión.** Todo lo que sobra sobre el piso va a los ETF, sin un tope y sin mirar cómo
  van: la parte en ETF sube de 42 % del dinero en oct-2016 a 96 % en abr-2026. La regla protege el pago de las
  cuotas, no la riqueza.

**Indicador reportado (no interviene en la decisión).** Sea $V_\tau$ el valor acumulado de los CDT vivos en $\tau$,
antes de comprar los nuevos (COP). El indicador de cobertura del portafolio completo es
$\Phi_\tau = (W_\tau + V_\tau) / (\Pi_\tau + V_\tau)$ (columna `funding_ratio_total`). Suma el valor de los CDT vivos
arriba y abajo: así no salta cuando hay CDT vivos (el piso del dinero libre baja porque ellos cubren parte de los
pagos, e incluso llega a 0 cuando los cubren todos) y no divide por cero mientras queden pagos. Con $k = 6$ su menor
valor fue 1,64 (abr-2017) y sube a medida que se pagan las cuotas: 2,30 en oct-2020, 3,77 en oct-2023 y 25,7 en
abr-2026.

### Simplificaciones propias del plan 3

- **Multiplicador $\kappa = 1$:** no se pone en ETF más que $G_\tau$. Con $\kappa > 1$ la escalera ya no cubriría
  todos los pagos: los ETF recibirían más de lo que sobra, es decir, dinero de la escalera, y el LP necesitaría
  permitir cobertura parcial.
- **Piso solo en las revisiones:** no se revisa cada mes. Con $\kappa = 1$ no hace falta, porque una caída de los ETF
  no reduce la escalera.
- **Sin regla para asegurar ganancias:** aunque $\Phi_\tau$ sea alto, no se pasa dinero de los ETF a la escalera.
- **Sin cobertura cambiaria (S19)**, venta inmediata (S16) y conversión a la TRM (S17).
- Además aplican los supuestos comunes.

## Plan 4 – LDI con filtro de tendencia

Es el [plan 3](#plan-3--ldi-piso-en-cdt-y-crecimiento-en-etf) con un solo cambio, en la parte de crecimiento: un ETF
que viene perdiendo no recibe dinero, y su parte queda en el FIC. Todo lo que no se describe aquí es igual al plan 3.

### Instrumentos

Los mismos del plan 3.

### Notación del plan 4

Además de la del plan 3:

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $g_i(\tau)$ | Rendimiento del ETF $i$ en los últimos 12 meses, en COP, conocido en $\tau$: $P_i(\tau) / P_i(\tau - 12) - 1$, con $P_i$ el precio del ETF | decimal | columnas `<nombre>_trend_ret`, YAML `data.trend_window_months` |
| $\underline g$ | Rendimiento mínimo para recibir dinero (0) | decimal | YAML `trend_ldi.min_trailing_return` |

### En cada revisión $\tau$

**Pasos 1 y 2:** iguales al plan 3 (piso y escalera).

**Paso 3 (cambia):** $G_\tau$ y los pesos $w_i$ se calculan como en el plan 3. El ETF $i$ recibe $w_i\,G_\tau$ solo si
$g_i(\tau) \ge \underline g$; si no, esa parte queda en el FIC. No se le pasa al otro ETF, para que un ETF que pierde no
aumente la exposición al otro. Si los dos fallan, todo $G_\tau$ queda en el FIC. En la siguiente revisión se vuelve a
evaluar: un ETF vuelve cuando su $g_i$ es otra vez $\ge \underline g$.

Código: `trend_ldi_strategy` en `src/uvr_loan/backtest.py`.

### Entre revisiones (cada mes)

Igual que el plan 3.

### Ejemplos (backtest con datos reales)

Revisiones en que el filtro dejó un ETF por fuera:

| Revisión | ICOLCAP $g$ | CSPX $g$ | Fuera | Parte en ETF |
|---|---|---|---|---|
| abr-2020 | −23,5 % | +23,9 % | ICOLCAP | 28 % |
| oct-2020 | −25,6 % | +24,7 % | ICOLCAP | 32 % |
| oct-2022 | −9,2 % | +8,7 % | ICOLCAP | 39 % |
| abr-2023 | −19,0 % | +17,3 % | ICOLCAP | 38 % |
| oct-2023 | −3,5 % | −8,0 % | los dos | 0 % |

### Riesgo y resultados

- Sin meses con déficit.
- Riqueza final 1.211,5M. Rentabilidad anual 11,0 %, volatilidad 7,7 %, máxima caída 7,1 %.
- **Limitaciones del filtro:** solo ve pérdidas que ya pasaron (los últimos 12 meses) y decide cada $k$ meses: puede
  sacar un ETF después de la caída y volver a comprarlo después de la subida. No pone un tope a la parte en ETF.

### Simplificaciones propias del plan 4

Las mismas del plan 3.

## Prueba de estrés: ETF con mal desempeño

`python -m uvr_loan.stress` (`src/uvr_loan/stress.py`) repite el backtest de los planes 2, 3 y 4 cambiando solo los
precios de los ETF desde $t_0$; tasas, UVR, FIC y pagos son los observados. Resultados en `results/stress_summary.csv`.

| Escenario | Cómo se construye |
|---|---|
| Real | Precios observados |
| ETF −50 % | Cada ETF conserva sus rendimientos mensuales observados menos una constante, y termina en 50 % de su precio de oct-2016 |
| ETF −80 % | Igual, terminando en 20 % |
| Caída −60 % | Precios observados hasta oct-2019 (la revisión antes de la primera cuota), caída de 60 % en nov-2019 y precios planos después |

El rendimiento de 12 meses $g_i(\tau)$ del plan 4 se recalcula con los precios del escenario. Las volatilidades
$\sigma_i(\tau)$ quedan las observadas: solo cambian el reparto entre los dos ETF.

**Riqueza neta final** (después de pagar el crédito y de restar lo que quedó sin pagar):

| Escenario | Plan 2 | Plan 3 | Plan 4 |
|---|---|---|---|
| Real | 780,1M | 1.352,5M | 1.211,5M |
| ETF −50 % | 780,1M | 252,0M | 432,3M |
| ETF −80 % | 780,1M | 128,1M | 421,9M |
| Caída −60 % | 780,1M | 254,3M | 272,5M |

**Máxima caída:**

| Escenario | Plan 2 | Plan 3 | Plan 4 |
|---|---|---|---|
| Real | 0 | 7,1 % | 7,1 % |
| ETF −50 % | 0 | 11,9 % | 6,3 % |
| ETF −80 % | 0 | 14,4 % | 8,2 % |
| Caída −60 % | 0 | 28,5 % | 28,5 % |

**Meses con déficit:** 0 para los planes 3 y 4 en todos los escenarios; 2 para el plan 2 en todos (no tiene ETF, así
que los escenarios no lo cambian).

## Referencias bibliográficas

- Sharpe, W. F. y Tint, L. G. (1990). "Liabilities – A New Approach". *Journal of Portfolio Management*, invierno de
  1990, 5–10.
- Black, F. y Perold, A. F. (1992). "Theory of constant proportion portfolio insurance". *Journal of Economic Dynamics
  and Control*, 16(3–4), 403–426.
- Martellini, L. y Milhau, V. (2012). "Dynamic allocation decisions in the presence of funding ratio constraints".
  *Journal of Pension Economics and Finance*, 11(4), 549–580.
- Maillard, S., Roncalli, T. y Teiletche, J. (2010). "The Properties of Equally Weighted Risk Contribution
  Portfolios". *Journal of Portfolio Management*, 36(4), 60–70.
- DeMiguel, V., Garlappi, L. y Uppal, R. (2009). "Optimal versus Naive Diversification: How Inefficient is the 1/N
  Portfolio Strategy?". *Review of Financial Studies*, 22(5), 1915–1953.
