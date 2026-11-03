# Reglas de inversión

Cómo se decide dónde y cuánto invertir en cada plan. Hoy solo existe el **plan 1 (conservador)**; los planes 2 y 3
se agregarán aquí.

Código: `conservative_allocation` en `src/uvr_loan/portfolio.py`. Simulación: `src/uvr_loan/backtest.py`.
Parámetros: `config/assumptions.yaml`.

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

En cada revisión τ, cada k = `backtest.rebalance_every` meses (hoy 6), desde `backtest.t0` (oct-2016): oct-2016,
abr-2017, oct-2017, …, abr-2026.

### Cómo se decide: tres pasos

**1. Cuánto dinero hay (W)**

W = saldo del FIC + valor del CDT que vence ese día (capital más intereses) + valor del ETF a precio de mercado.

En t₀, W = 760.000.000 COP (`initial_capital_cop`).

**2. Cuánto se necesita hasta la siguiente revisión (L)**

1. Se toman los pagos en UVR de los meses τ+1 … τ+k de la tabla de amortización (cuotas y abonos).
2. Se pasan a COP con la UVR proyectada: la UVR real de τ creciendo a la inflación del escenario
   `conservative.liquidity_scenario` (hoy el **alto**: 3 % + 3 p.p. = 6 % anual).
3. La suma es la necesidad de liquidez L.

Se usa el escenario alto para que el FIC alcance aunque la inflación sea mayor que la esperada.

**3. Repartir W**

| Instrumento | Monto |
|---|---|
| FIC | L |
| ETF | `equity_weight` × (W − L), hoy 10 % |
| CDT | el resto: (1 − `equity_weight`) × (W − L) |

Si los pagos superan la riqueza (L > W), todo va al FIC y la diferencia se registra como déficit.

### Entre revisiones (cada mes)

- El FIC crece a la tasa del mes anterior, pasada a mensual: (1 + r)^(1/12).
- El CDT crece a la tasa fijada al comprarlo.
- El ETF vale las unidades compradas por su precio del mes.
- Se paga la cuota del mes en COP (pago en UVR × UVR **real** del mes) sacándola del FIC.

En la siguiente revisión el CDT vence, todo se vuelve a sumar en W y se repiten los tres pasos. Así el ETF vuelve al
10 % y el FIC se ajusta a los pagos que vienen.

### Ejemplos (backtest con datos reales)

| Revisión | W | L (pagos de los próximos 6 meses) | FIC | CDT | ETF |
|---|---|---|---|---|---|
| oct-2016 (gracia) | 760,0M | 0 | 0 | 684,0M | 76,0M |
| oct-2019 (antes de la primera cuota) | 906,5M | 33,6M | 33,6M | 785,6M | 87,3M |

### Simplificaciones

- **Déficit (S9):** si el FIC no alcanza para un pago, se registra el déficit y no se hace nada más: no se vende ETF
  ni se redime el CDT antes del vencimiento.
- **Plazo del CDT (S10):** se usa la tasa de 180 días aunque se pruebe k = 3 o 12.
- **FIC (S10):** su rentabilidad se aproxima con la DTF a 90 días.
- **Inflación proyectada:** el 3 % base es un valor provisional hasta que exista el modelo de inflación
  (`scenarios` en `src/uvr_loan/inflation.py`).
- **Sin costos ni impuestos (S3, S6):** comprar, vender y rebalancear no cuesta nada.

### Qué decide la regla y qué no

- **Dónde invertir:** los tres instrumentos son fijos, elegidos de antemano. La regla no compara alternativas.
- **Cuánto:** lo fijan solo los pagos próximos (FIC) y `equity_weight` (ETF). El 10 % es una elección, no el
  resultado de un cálculo.
- Para los planes 2 y 3 se propone (aún sin definir) estimar rentabilidades y volatilidades con los datos hasta τ y
  obtener la proporción en renta variable de una optimización ("maximizar el excedente sujeto a cero déficit",
  sección 5.3 del plan del proyecto).
