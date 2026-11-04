# Reglas de inversión

Cómo se decide dónde y cuánto invertir en cada plan: el **plan 1 (conservador)**, el **plan 2 (escalera de CDT
optimizada)** y el **plan 3 (LDI: piso en CDT y crecimiento en ETF)**.

**Criterio de los resultados:** las decisiones pueden usar estimaciones (por ejemplo, la inflación esperada), siempre
con datos conocidos en la fecha de la revisión. El dinero reportado sale solo de rendimientos observados de
instrumentos reales: tasas de CDT del BanRep, el índice de FIC de la Superfinanciera, precios del ETF y la UVR. Ningún
resultado es un límite ni usa un rendimiento supuesto.

Código: `conservative_allocation`, `ladder_purchases`, `ladder_floor` e `inverse_volatility_weights` en
`src/uvr_loan/portfolio.py`. Simulación:
`src/uvr_loan/backtest.py` (un plan por estrategia, en `PLANS`). Parámetros: `config/assumptions.yaml`.

## Notación

**Convención de tiempo.** El tiempo se cuenta en meses desde $t_0$ (oct-2016, mes 0). El mes $m$ va del cierre del
mes $m-1$ al cierre del mes $m$; el pago $P_m$ y la $\text{UVR}_m$ son del cierre del mes $m$. Las revisiones son los
meses $\tau = 0, k, 2k, \dots$, así que la siguiente a $\tau$ es $\tau + k$ (no $\tau + 1$). Todo símbolo con subíndice
$\tau$ es un dato conocido al cierre del mes $\tau$. El orden dentro de un mes está en S12.

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
| $\pi_\tau$ | Inflación del escenario que usa cada plan en $\tau$ (ver abajo) | decimal E.A. | función `scenarios` |
| $\widehat{\text{UVR}}_{m\mid\tau}$ | UVR proyectada en $\tau$ para el mes $m > \tau$ | COP por UVR | función `project_uvr` |
| $r^{\text{FIC}}_m$ | Rentabilidad **realizada** del FIC durante el mes $m$ (índice de FIC de mercado monetario, S10) | decimal mensual | columna `fic_ret_m` |
| $\bar r^{\text{FIC}}_m$ | La misma, anualizada: conocida al cierre del mes $m$, se usa para decidir | decimal E.A. | columna `fic_rate_ea` |
| $r_j(\tau)$ | Tasa observada del CDT de plazo $j$ meses comprado en $\tau$ ($j$ = 3, 6, 12: DTF, CDT 180 y 360 días) | decimal E.A. | columnas `cdt_90d_ea`, `cdt_180d_ea`, `cdt_360d_ea` |
| $F_m$ | Saldo del FIC al cierre del mes $m$ (después de crecer, recibir lo que vence y pagar) | COP | columna `fic_cop` |
| $W$ | Dinero libre en $\tau$: FIC + ETF a precio de mercado (lo que vence en $\tau$ ya está en el FIC; los CDT vivos no cuentan) | COP | variable `free_cop` |
| $L$ | Necesidad de liquidez del plan 1 en $\tau$ | COP | función `projected_payments_cop` |
| $w$ | Plan 1: parte de $W - L$ que va al CDT (0,90); el resto queda en el FIC | decimal | YAML `conservative.cdt_weight` |
| $E_m$ | Valor de los ETF al cierre del mes $m$, a precio de mercado (suma de todos; cada uno en `<nombre>_cop`) | COP | columna `etf_cop` |
| — | **Liquidez:** FIC + ETF ($F_m + E_m$); los CDT no son liquidez hasta que vencen | COP | métrica `min_liquid_at_payment_cop` |
| $D_m$ | Déficit del mes $m$: parte del pago que no cubren ni el FIC ni el ETF | COP | columna `shortfall_cop` |
| — | **Riqueza neta:** riqueza menos el déficit acumulado, $F_m + \text{CDT}_m + E_m - \sum_{m' \le m} D_{m'}$ (un pago sin cubrir sigue debiéndose) | COP | columna `wealth_net_cop` |

**Escenarios de inflación.** En cada $\tau$ hay tres: base $=\pi^{\text{base}}_\tau$, alto
$=\pi^{\text{base}}_\tau + 0{,}03$ y bajo $=\pi^{\text{base}}_\tau - 0{,}015$. El plan 1 usa el alto para dimensionar el
FIC (YAML `conservative.fic_sizing_scenario`); el plan 2 usa el base para pasar tasas nominales a reales (YAML
`cdt_ladder.deflator_scenario`). $\pi_\tau$ denota el que usa cada plan.

**Plan 2 (variables del LP):**

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $j$ | Plazo de un CDT: 3, 6 o 12 | meses | YAML `cdt_ladder.term_columns` |
| $\tilde r_j(\tau)$ | Rentabilidad real **esperada** del CDT de plazo $j$ (solo para decidir) | decimal E.A. | variable `cdt_real_ea` |
| $\rho_\tau$ | Rentabilidad real **esperada** de la caja (solo para decidir) | decimal E.A. | variable `fic_real_ea` |
| $\mathcal R_\tau$ | Meses en que se puede comprar: $\{\tau, \tau + k, \tau + 2k, \dots\}$ | meses | – |
| $y_{s,j}$ | Monto invertido en el mes $s \in \mathcal R_\tau$ en un CDT de plazo $j$, con $s + j \le H$ | UVR | variable del LP |
| $c_m$ | Caja (FIC) al cierre del mes $m$ dentro del LP | UVR | variable del LP |
| $M_m$ | Lo que vence en el mes $m$ de los CDT comprados antes de $\tau$ | UVR | variable `maturities_uvr` |
| $B$ | Dinero libre en $\tau$, en UVR | UVR | variable `budget_uvr` |

**Definiciones:**

$$
\pi^{\text{base}}_\tau = \left(\frac{\text{UVR}_\tau}{\text{UVR}_{\tau-6}}\right)^{2} - 1
\qquad
\widehat{\text{UVR}}_{m\mid\tau} = \text{UVR}_\tau\,(1 + \pi_\tau)^{(m-\tau)/12}
\qquad
\bar r^{\text{FIC}}_m = \bigl(1 + r^{\text{FIC}}_m\bigr)^{12} - 1
$$

El 6 de $\pi^{\text{base}}_\tau$ es `base_lookback_months`, no $k$.

$$
\tilde r_j(\tau) = \frac{1 + r_j(\tau)}{1 + \pi_\tau} - 1
\qquad
\rho_\tau = \frac{1 + \bar r^{\text{FIC}}_\tau}{1 + \pi_\tau} - 1
\qquad
B = \frac{F_\tau}{\text{UVR}_\tau}
$$

$$
M_m = \sum_{\text{CDT vivos que vencen en } m} \frac{V}{\widehat{\text{UVR}}_{m\mid\tau}}
\qquad (M_m = 0 \text{ si } m \le \tau)
$$

donde $V$ es el valor del CDT al vencer, en COP: capital $\times\,(1 + \text{tasa})^{\text{plazo}/12}$.

$$
D_m = \max\bigl(P_m\,\text{UVR}_m - F^{-}_m - E^{-}_m,\ 0\bigr)
$$

donde $F^{-}_m$ es el saldo del FIC en el mes $m$ después de crecer y recibir lo que vence, y antes de pagar, y
$E^{-}_m$ el valor del ETF a precio del mes $m$ antes de pagar.

## Supuestos comunes a todos los planes

- **Orden dentro de un mes (S12):** primero crecen los activos, luego vencen los CDT, luego se paga la cuota y, si es
  mes de revisión, se decide. Un CDT que vence en el mes $m$ sirve para el pago del mes $m$. Si el primer CDT que
  vence después de $\tau$ lo hace en el mes $m^\star$, la caja de hoy solo debe cubrir los pagos
  $\tau+1, \dots, m^\star-1$ (regla $n - 1$).
- **Solo se compra en las revisiones (S13):** lo que vence entre $\tau$ y $\tau + k$ y no se usa para pagar queda en
  el FIC hasta la siguiente revisión.
- **Sin información futura:** en cada revisión la estrategia recibe los datos solo hasta $\tau$.
- **Inflación proyectada (S14):** la base es la inflación de los últimos 6 meses medida con la UVR
  ($\pi^{\text{base}}_\tau$). Es un modelo provisional hasta que exista el modelo de inflación (`scenarios` en
  `src/uvr_loan/inflation.py`). Con 6 meses la base tiene estacionalidad: en abril ve los meses de inflación alta de
  comienzo de año y en octubre los de inflación baja.
- **Liquidez y déficit (S9):** el pago sale primero del FIC; si no alcanza, se venden unidades de los ETF al precio de
  ese mes (columna `etf_sold_cop`). Si hay varios ETF, se vende de cada uno en proporción a su valor (a prorrata), así
  los pesos no cambian hasta la siguiente revisión. Solo si el FIC y los ETF juntos no alcanzan se registra el déficit
  $D_m$. Los CDT nunca se redimen antes del vencimiento. Los ETF se tratan como liquidez en tiempo, pero no en valor:
  se venden al precio del mes, que puede estar en pérdida.
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
- **FIC (S10):** rinde lo que rindió un índice de los FIC de mercado monetario reales: el valor de la unidad de cada
  fondo, publicado a diario por la Superfinanciera, promediado según el tamaño de cada fondo. Ver `data/SOURCES.md`.
- **Sin costos ni impuestos (S3, S6):** comprar, vender y rebalancear no cuesta nada.

## Plan 1 – Conservador

Es una regla fija, no una optimización, y solo usa renta fija: FIC y CDT, sin renta variable (como el perfil
conservador del plan del proyecto). No usa rentabilidades esperadas, volatilidades ni el indicador de cobertura: sirve
como punto de comparación para los planes más elaborados.

### Instrumentos

| Instrumento | Rol | Dato que se usa |
|---|---|---|
| **FIC a la vista** | Liquidez para las cuotas y una parte fija del resto | Índice de FIC de mercado monetario (Superfinanciera) |
| **CDT a 180 días** | Renta fija; vence justo en la siguiente revisión | $r_6(\tau)$: tasa observada del CDT a 180 días del mes de compra |

Las fuentes de cada serie están en [`data/SOURCES.md`](../data/SOURCES.md).

### Cuándo se decide

En cada revisión $\tau$, cada $k$ = `backtest.review_every_months` meses (hoy 6), desde `backtest.t0` (oct-2016):
oct-2016, abr-2017, oct-2017, …, abr-2026.

### Cómo se decide: tres pasos

**1. Cuánto dinero libre hay ($W$)**

$W$ = saldo del FIC, que ya incluye el CDT que vence ese mes.

En $t_0$, $W$ = 760.000.000 COP (`initial_capital_cop`).

**2. Cuánto se necesita hasta que venza el nuevo CDT ($L$)**

El CDT que se compra hoy vence en $\tau + k$ y, por S12, paga $P_{\tau+k}$. El FIC solo cubre los pagos anteriores:

$$
L = \sum_{m=\tau+1}^{\tau+k-1} P_m\,\widehat{\text{UVR}}_{m\mid\tau}
$$

con la UVR proyectada al escenario **alto** (`conservative.fic_sizing_scenario`; en oct-2016,
4,34 % + 3 p.p. = 7,34 %), para que el FIC alcance aunque la inflación sea mayor que la esperada.

**3. Repartir $W$**

| Instrumento | Monto |
|---|---|
| CDT | $w\,(W - L)$, con $w$ = 90 % hoy |
| FIC | el resto: $L + (1 - w)(W - L)$ |

**Durante la gracia** (revisiones con $\tau$ < 36, antes de la primera cuota) no hay pagos, así que no hace falta
colchón: se usa $w$ = 100 % (`conservative.grace_cdt_weight`) y todo el dinero va al CDT. Desde la revisión de
oct-2019 se vuelve al 90 %.

Si los pagos proyectados superan el dinero libre ($L > W$), todo va al FIC; la parte que no alcanza solo se convierte
en déficit $D_m$ si al llegar el pago el FIC no lo cubre.

### Entre revisiones (cada mes)

- El FIC crece con su rentabilidad realizada del mes: $F^{-}_m = F_{m-1}\,(1 + r^{\text{FIC}}_m)$ más lo que vence.
- El CDT crece a la tasa fijada al comprarlo: $\bigl(1 + r_6(\tau)\bigr)^{1/12}$ por mes.
- Se paga la cuota del mes en COP, $P_m\,\text{UVR}_m$ (con la UVR **observada**), sacándola del FIC. Como el plan 1
  no tiene ETF, lo que falte es el déficit $D_m$.

En la siguiente revisión el CDT vence, entra al FIC, paga el pago de ese mes y lo que queda forma el nuevo $W$. Así el
FIC se ajusta a los pagos que vienen y el CDT vuelve a ser el 90 % del resto.

### Ejemplos (backtest con datos reales)

| Revisión | $W$ | $L$ (pagos de los próximos 5 meses) | FIC | CDT |
|---|---|---|---|---|
| oct-2016 (gracia, $w$ = 100 %) | 760,0M | 0 | 0 | 760,0M |
| oct-2019 (antes de la primera cuota, $w$ = 90 %) | 897,6M | 27,9M | 114,9M | 782,7M |

### Riesgo

El 10 % que queda en el FIC además de $L$ funciona como colchón: el saldo mínimo del FIC en un mes de pago fue
71,8M, y no hubo déficit. A cambio, ese dinero rinde lo del FIC y no lo del CDT. Poner también ese 10 % en el CDT
durante la gracia sube la riqueza final de 696,9M a 701,0M: entre oct-2016 y oct-2019 el CDT a 180 días rindió en
promedio 5,51 % frente a 4,82 % del FIC. Con el 10 % en ETF (versión anterior del plan) la riqueza final fue 734,8M:
la diferencia viene sobre todo de 2025, cuando ICOLCAP subió 39 %, algo que no se sabía en 2016.

### Simplificaciones propias del plan 1

- **Plazo del CDT (S10):** se usa la tasa de 180 días aunque se pruebe $k$ = 3 o 12.
- Además aplican los supuestos comunes.

### Qué decide la regla y qué no

- **Dónde invertir:** los tres instrumentos son fijos, elegidos de antemano. La regla no compara alternativas.
- **Cuánto:** lo fijan solo los pagos próximos (FIC), `cdt_weight` (CDT) y `grace_cdt_weight` (CDT durante la
  gracia). El 90 % es una elección, no el resultado de un cálculo.

## Plan 2 – Escalera de CDT optimizada

En lugar de poner todo en un CDT a 180 días (plan 1), escoge con un **programa lineal (LP)** cuánto invertir en CDT de
tasa fija a 3, 6 y 12 meses para que vayan venciendo cuando llegan los pagos. No hay renta variable. Los CDT y la caja
rinden sus tasas **observadas** (BanRep e índice de FIC); solo la decisión usa la inflación esperada.

### Instrumentos

| Instrumento | Rol | Dato que se usa (resultado) |
|---|---|---|
| **CDT a 3 meses** | Escalera | $r_3(\tau)$: DTF del mes de compra (serie 65) |
| **CDT a 6 meses** | Escalera | $r_6(\tau)$: CDT a 180 días del mes de compra (serie 67) |
| **CDT a 12 meses** | Escalera | $r_{12}(\tau)$: CDT a 360 días del mes de compra (serie 68) |
| **FIC a la vista** | Caja para los pagos que caen antes del siguiente vencimiento | Índice de FIC de mercado monetario (Superfinanciera) |

### Cómo se decide en cada revisión $\tau$

Los pagos están fijos en UVR, así que el LP trabaja en UVR. Como los CDT y el FIC pagan en pesos, el LP necesita su
rendimiento en UVR, que no se conoce de antemano: usa el **esperado**, $\tilde r_j(\tau)$ y $\rho_\tau$, con la
inflación base (`cdt_ladder.deflator_scenario`).

1. **Datos (en UVR):** los pagos $P_m$ de los meses $\tau+1, \dots, H$; lo que vence de los CDT vivos, $M_m$; el
   dinero libre $B$; los rendimientos reales esperados $\tilde r_j(\tau)$ y $\rho_\tau$.
2. **Variables:** $y_{s,j} \ge 0$ para $s \in \mathcal R_\tau$ y $s + j \le H$ (incluyen las reinversiones futuras
   previstas); $y_{s,j} = 0$ en los demás casos. $c_m \ge 0$, caja al cierre de cada mes, después de pagar.
3. **Problema:**

$$
\begin{aligned}
\max_{y,\,c} \quad & c_H \\
\text{s.a.} \quad & c_\tau + \sum_j y_{\tau,j} = B \\
& c_m = c_{m-1}(1 + \rho_\tau)^{1/12} + \sum_j y_{m-j,\,j}\,\bigl(1 + \tilde r_j(\tau)\bigr)^{j/12} \\
& \qquad\quad + M_m - \sum_j y_{m,j} - P_m, \qquad m = \tau+1, \dots, H \\
& y_{s,j} \ge 0, \quad c_m \ge 0
\end{aligned}
$$

   Por S12, lo que vence en $m$ sirve para $P_m$.

4. **Desempate:** el LP suele tener varias soluciones con el mismo $c_H$ (sobre todo en la gracia, donde dos CDT a 6
   meses seguidos rinden casi lo mismo que uno a 12). Por eso se resuelve en dos etapas: primero el máximo $c_H$, y
   después, entre las soluciones que lo alcanzan (con tolerancia relativa $10^{-9}$), la que minimiza
   $\sum_j j\,y_{\tau,j}$, es decir, la compra de hoy con los plazos más cortos. Así la compra no depende del método
   del solver.
5. **Ejecución:** solo se compran los $y_{\tau,j}$ de hoy, convertidos a COP con $\text{UVR}_\tau$; $c_\tau$ queda en
   el FIC. Cada CDT rinde después su tasa observada $r_j(\tau)$. En la siguiente revisión se vuelve a resolver con los
   CDT vivos como $M_m$.
6. **Sin escalera posible:** si el LP no tiene solución (con la inflación esperada, el dinero libre no alcanza para
   todos los pagos), no se compra nada, todo queda en el FIC y los déficits se registran (S9). Cualquier otra falla del
   solver detiene el backtest con un error, para que no se confunda con este caso.

### Ejemplos (backtest con datos reales)

| Revisión | Dinero libre | FIC | CDT 3 meses | CDT 6 meses | CDT 12 meses |
|---|---|---|---|---|---|
| oct-2016 (gracia) | 760,0M | 0 | 0 | 164,5M | 595,5M |
| oct-2019 (antes de la primera cuota) | 711,3M | 11,0M | 16,5M | 12,3M | 671,5M |

En oct-2016 las tasas eran 6,99 % (90 días), 7,24 % (180) y 8,18 % (360): sin pagos durante la gracia, casi todo va al
plazo más largo. En oct-2019 el dinero libre es menor que la riqueza total porque hay CDT comprados antes que siguen
vivos.

### Riesgo

Los CDT son de tasa fija: si la inflación supera la esperada, los pagos en COP crecen más que el dinero. Con la
inflación base, el backtest tiene 9 meses con déficit (1,18M COP en total); el mayor es sep-2026 (0,70M). En
abr-2026 no hubo escalera posible y el dinero quedó en el FIC. La riqueza final es 782,3M; descontando los pagos que
quedaron sin cubrir, la riqueza neta es 781,1M.

### Simplificaciones propias del plan 2

- Los CDT se compran a la tasa promedio del mercado de su plazo (no a la de un banco concreto), por cualquier monto,
  solo en las revisiones, y se mantienen hasta el vencimiento.
- **Pronóstico de la caja (S15):** para decidir, el LP supone que el FIC seguirá rindiendo, durante todo el horizonte,
  lo mismo que rindió el último mes, anualizado ($\bar r^{\text{FIC}}_\tau$). Así obtiene $\rho_\tau$ y lo compara con
  los CDT. Como la caja y los CDT se descuentan con la misma inflación, preferir la caja depende solo de comparar
  $\bar r^{\text{FIC}}_\tau$ con las $r_j(\tau)$ del día. Evaluado contra lo que pasó en los 6 meses siguientes a cada
  revisión:
  - acierta en 17 de 20 revisiones cuál rinde más, la caja o el CDT a 180 días. Falla en abr-2020 (prácticamente un
    empate) y en abr-2022 y oct-2022, cuando el BanRep subía tasas y el FIC, que sigue las tasas mes a mes, le ganó a
    los CDT comprados a la tasa anterior;
  - el error absoluto medio del rendimiento nominal del FIC es 1,29 p.p. y tiende a subestimarlo (−0,78 p.p. en
    promedio) cuando las tasas suben; el mayor error fue 5,87 p.p. en oct-2022;
  - el error de $\rho_\tau$ es mayor, 2,30 p.p. en promedio, y viene sobre todo de la inflación base (S14), no del FIC;
  - **si el último mes del FIC fue negativo**, $\rho_\tau$ queda muy negativo (oct-2021:
    $\bar r^{\text{FIC}}_\tau$ = −0,91 %, $\rho_\tau$ = −6,22 %). El LP no falla: guarda en caja solo lo
    indispensable, aparta un poco más para compensar la pérdida esperada (alrededor del 0,5–1 % de esa caja) y pone
    el resto en CDT. Después de oct-2021 el FIC rindió +2,69 %, así que el pronóstico fue pesimista, sin costo. El
    caso que sí puede afectar es el contrario (pronóstico positivo y mes real negativo), en el que la caja queda un
    poco corta; el índice solo tuvo 4 meses negativos en 10 años (el peor, −0,16 %). No se pone un piso al pronóstico.
- Además aplican los supuestos comunes.

## Plan 3 – LDI: piso en CDT y crecimiento en ETF

Separa el dinero en dos partes, como en la inversión guiada por los pasivos (*liability-driven investment*, LDI): una
**parte de cobertura**, la escalera de CDT del plan 2, que cubre todos los pagos que faltan, y una **parte de
crecimiento**, en ETF de renta variable, con solo el dinero que sobra por encima de esa cobertura. Es la forma más
simple de la regla CPPI (*constant proportion portfolio insurance*) con multiplicador $m = 1$: los ETF reciben
exactamente el colchón, así que una caída de los ETF, incluso del 100 %, nunca toca el dinero de los pagos.

### Instrumentos

| Instrumento | Rol | Dato que se usa (resultado) |
|---|---|---|
| **CDT a 3, 6 y 12 meses** | Cobertura: escalera del LP del plan 2 | $r_j(\tau)$: DTF, CDT 180 y 360 días (series 65, 67, 68) |
| **FIC a la vista** | Caja de la escalera | Índice de FIC de mercado monetario (Superfinanciera) |
| **ICOLCAP** | Crecimiento: renta variable colombiana | Precio ajustado en COP (Yahoo, `ICOLCAP.CL`) |
| **CSPX** | Crecimiento: S&P 500 (iShares Core S&P 500 UCITS, irlandés, de acumulación) | Precio ajustado en USD (Yahoo, `CSPX.L`) × TRM |

CSPX se escogió con información de 2016: diversifica fuera de Colombia (su correlación con ICOLCAP es baja), existe
desde 2010 y su precio ya incluye la retención del 15 % sobre los dividendos, que es lo que de verdad recibe un
inversionista colombiano. Los TES (UVR y tasa fija) quedan como tema pendiente para todos los planes.

### Notación adicional

| Símbolo | Significado | Unidad | En el código |
|---|---|---|---|
| $B^{\min}_\tau$ | **Piso**: el menor presupuesto con el que una escalera cubre todos los pagos que faltan | UVR | función `ladder_floor` |
| $b$ | Margen sobre el piso (5 %) | decimal | YAML `ldi.floor_buffer` |
| $G$ | Parte de crecimiento (ETF) en $\tau$ | COP | – |
| $V_\tau$ | Valor de los CDT vivos en $\tau$ (antes de comprar los nuevos) | COP | – |
| $F_\tau$ | Indicador de cobertura del portafolio completo: $(W + V_\tau) / (B^{\min}_\tau\,\text{UVR}_\tau + V_\tau)$. Solo se reporta; no interviene en la decisión | – | columna `funding_ratio_total` |
| $\sigma_i(\tau)$ | Volatilidad anual del ETF $i$: desviación estándar de sus últimos 36 rendimientos mensuales en COP × $\sqrt{12}$ | decimal | columnas `<nombre>_vol_ea` |

### Cómo se decide en cada revisión $\tau$

1. **Piso.** Es el LP del plan 2 con el presupuesto como variable, minimizando:

$$
\begin{aligned}
B^{\min}_\tau = \min_{B,\,y,\,c} \quad & B \
\text{s.a.} \quad & c_\tau + \sum_j y_{\tau,j} = B \
& c_m = c_{m-1}(1 + \rho_\tau)^{1/12} + \sum_j y_{m-j,\,j}\,\bigl(1 + \tilde r_j(\tau)\bigr)^{j/12}
  + M_m - \sum_j y_{m,j} - P_m, \qquad m = \tau+1, \dots, H \
& B \ge 0, \quad y_{s,j} \ge 0, \quad c_m \ge 0
\end{aligned}
$$

   Las tasas reales esperadas $\tilde r_j(\tau)$ y $\rho_\tau$ se calculan con la inflación del escenario **alto**
   (`ldi.floor_scenario`), que es el margen para el riesgo de que la inflación supere lo esperado: los CDT son de tasa
   fija y los pagos están en UVR. Como en el plan 2, las compras futuras se suponen a las tasas reales de hoy y los CDT
   vivos entran como vencimientos conocidos $M_m$. El piso es lo que de verdad costaría la escalera, así que no hace
   falta una curva real para descontar los pagos.
2. **Escalera.** Recibe $\min\bigl(W,\ (1 + b)\,B^{\min}_\tau\,\text{UVR}_\tau\bigr)$ y se resuelve con el LP del
   plan 2 (`ladder_purchases`, mismas tasas del escenario alto). Si $W$ es menor que el piso no hay escalera posible:
   el dinero queda en el FIC y los déficits se registran, como en el plan 2.
3. **Crecimiento.** $G = W - \min\bigl(W,\ (1 + b)\,B^{\min}_\tau\,\text{UVR}_\tau\bigr)$, repartido entre los ETF
   en proporción inversa a su volatilidad:

$$
w_i = \frac{1/\sigma_i(\tau)}{\sum_k 1/\sigma_k(\tau)}
$$

   Con dos activos, estos pesos hacen que cada uno aporte el mismo riesgo ($w_1\sigma_1 = w_2\sigma_2$), sin importar
   la correlación (paridad de riesgo). Las volatilidades se calculan con datos hasta $\tau$ (ICOLCAP desde mayo de
   2013 y CSPX desde 2013), así que en oct-2016 ya hay 36 meses.

Entre revisiones, los pagos salen del FIC y de los CDT que vencen; si no alcanzan, se venden ETF a prorrata (S9).

### Ejemplos (backtest con datos reales)

| Revisión | $W$ | Piso ($B^{\min}$, COP) | $F$ | Escalera (CDT + FIC) | ICOLCAP | CSPX |
|---|---|---|---|---|---|---|
| oct-2016 | 760,0M | 419,9M | 1,81 | 440,9M | 161,2M | 157,9M |
| oct-2019 | 755,4M | 261,9M | 1,96 | 275,0M | 233,4M | 246,9M |

En oct-2016 la inflación alta era 7,34 % (4,34 % + 3 p.p.); la escalera compró 198,4M en CDT a 6 meses (7,24 %) y
242,5M a 12 meses (8,18 %). Las volatilidades eran 17,7 % (ICOLCAP) y 18,0 % (CSPX), así que los pesos quedaron casi
iguales (50,5 % y 49,5 %). En oct-2019 $W$ no incluye los CDT comprados antes que siguen vivos (su valor más el de
la escalera nueva suma 513,6M en CDT y 11,0M en el FIC); por eso el piso es menor que en 2016 aunque faltan los mismos
pagos.

### Riesgo y resultados

- Sin meses con déficit. Dos veces el FIC quedó corto por muy poco y se vendieron ETF: jun-2021 (41.468 COP) y jun-2022
  (9.651 COP).
- Riqueza final 1.352,5M (plan 1: 701,0M; plan 2: 782,3M). Rentabilidad anual 11,9 %, volatilidad 8,3 %, máxima caída
  7,1 % (los planes 1 y 2 tienen volatilidad cercana a 1 % y no tienen caídas).
- **Cuidado con leer el resultado como una predicción.** Buena parte de la diferencia viene de 2024–2025, cuando
  ICOLCAP y el S&P 500 subieron mucho, algo que no se sabía en 2016. Además, a medida que se pagan las cuotas el piso
  baja y la parte en ETF crece: en abr-2026 los ETF eran el 96 % del dinero. La protección de los pagos no depende de
  eso (siempre está la escalera con 1,05 × piso), pero la riqueza final sí depende del mercado accionario.
- $F$ suma el valor de los CDT vivos arriba y abajo. Así no salta cuando hay CDT vivos (el piso del dinero libre
  baja porque ellos cubren parte de los pagos, e incluso llega a 0 cuando los cubren todos) y no divide por cero
  mientras queden pagos. Con $k = 6$ su menor valor fue 1,64 (abr-2017) y sube a medida que se pagan las cuotas:
  2,30 en oct-2020, 3,77 en oct-2023 y 25,7 en abr-2026.

### Simplificaciones propias del plan 3

- **Multiplicador $m = 1$:** no se pone en ETF más que el colchón. Con $m > 1$ la escalera ya no cubriría todos los
  pagos y el LP necesitaría permitir cobertura parcial.
- **Piso solo en las revisiones:** no se revisa cada mes. Con $m = 1$ no hace falta, porque una caída de los ETF no
  reduce la escalera.
- **Sin trinquete:** cuando $F$ es alto no se pasa dinero de los ETF a la escalera.
- **Sin cobertura cambiaria (S19)**, venta inmediata (S16) y conversión a la TRM (S17).
- Además aplican los supuestos comunes.

### Referencias

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
