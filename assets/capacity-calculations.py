#!/usr/bin/env python3
"""Capacity and investment recovery: reproducible conditional calculations.

Python 3.10+, standard library only. No network access or input-file changes.
Usage: python capacity-calculations.py [--data capacity-data.csv]
The prefixed download filenames also work together without renaming.

Model money is USD billions. Rates are effective annual required returns.
A synchronized 200-MW IT cohort uses 60 equal service months, not the actual
phase-by-phase calendar. Customer advances are credited from later collections.
The results are not appraisals, actual project IRRs, forecasts or lender losses.
"""
from __future__ import annotations
import argparse
import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    source: str

def load_inputs(path: Path) -> dict[str, Input]:
    result: dict[str, Input] = {}
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        required = {'id', 'value', 'unit', 'status', 'source_id', 'source_url', 'period', 'notes'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Input ledger is missing required columns')
        for row in reader:
            key = row['id']
            if not key or key in result:
                raise ValueError(f'Empty/duplicate input ID: {key!r}')
            if None in row or any(row.get(k) is None for k in required):
                raise ValueError(f'Malformed row: {key}')
            value = float(row['value'])
            if not math.isfinite(value):
                raise ValueError(f'Non-finite value: {key}')
            if not row['status'] or not row['period'] or not row['source_url'] or not row['notes']:
                raise ValueError(f'Missing evidence boundary: {key}')
            result[key] = Input(value, row['unit'], row['status'], row['source_id'])
    if not result:
        raise ValueError('Input ledger is empty')
    return result

def val(data: dict[str, Input], key: str, unit: str | None = None) -> float:
    rec = data[key]
    if unit is not None and rec.unit != unit:
        raise ValueError(f'Unit mismatch for {key}: {rec.unit}, expected {unit}')
    return rec.value

def bn(data: dict[str, Input], key: str) -> float:
    return val(data, key, 'USD_million') / 1000.0

def finite_nonnegative(name: str, x: float) -> None:
    if not math.isfinite(x) or x < 0:
        raise ValueError(f'{name} must be finite and nonnegative')

@dataclass(frozen=True)
class Cohort:
    value: float
    advance: float
    capital: float
    direct_cost_share: float = .15
    extra_cost_share: float = 0.
    discount: float = .10
    months: int = 60
    credit_start: int = 25
    delay: int = 0
    advance_month: int = 0
    fee_loss: float = 0.
    residual: float = 0.
    early_refresh_month: int = 0
    early_refresh_cost: float = 0.

    def __post_init__(self) -> None:
        for field in ('value','advance','capital','direct_cost_share','extra_cost_share',
                      'discount','fee_loss','residual','early_refresh_cost'):
            finite_nonnegative(field, getattr(self, field))
        for field in ('months','credit_start','delay','advance_month','early_refresh_month'):
            x = getattr(self, field)
            if isinstance(x, bool) or not isinstance(x, int) or x < 0:
                raise ValueError(f'{field} must be a nonnegative integer')
        if self.months <= 0 or not 1 <= self.credit_start <= self.months:
            raise ValueError('Invalid service/credit term')
        if self.advance > self.value or self.fee_loss > .5:
            raise ValueError('Advance exceeds value or fee-loss stress exceeds model domain')
        if self.direct_cost_share + self.extra_cost_share > 1:
            raise ValueError('Cost shares exceed original revenue')
        if self.advance_month > self.delay:
            raise ValueError('Advance is modeled no later than service commencement')
        if self.early_refresh_month > self.months:
            raise ValueError('Early refresh falls outside initial service term')
        if bool(self.early_refresh_month) != bool(self.early_refresh_cost):
            raise ValueError('Specify both early-refresh month and cost, or neither')

@dataclass(frozen=True)
class Flow:
    month: int
    amount: float
    kind: str

def initial_flows(c: Cohort) -> list[Flow]:
    """No invented pre-service carrying costs. Fee-loss stress keeps original cost base."""
    flows = [Flow(0, -c.capital, 'initial capital'),
             Flow(c.advance_month, c.advance, 'contract advance')]
    monthly_gross = c.value / c.months
    monthly_credit = c.advance / (c.months - c.credit_start + 1)
    monthly_cost = c.value * (c.direct_cost_share + c.extra_cost_share) / c.months
    for m in range(1, c.months + 1):
        receipt = monthly_gross * (1 - c.fee_loss)
        if m >= c.credit_start:
            receipt -= monthly_credit
        flows.append(Flow(c.delay + m, receipt, 'service collection after advance credit'))
        flows.append(Flow(c.delay + m, -monthly_cost, 'cash operating costs and allowance'))
    if c.early_refresh_cost:
        flows.append(Flow(c.delay + c.early_refresh_month, -c.early_refresh_cost, 'premature capital renewal'))
    if c.residual:
        flows.append(Flow(c.delay + c.months, c.residual, 'net residual realization'))
    return flows

def npv(flows: Iterable[Flow], rate: float) -> float:
    finite_nonnegative('discount rate', rate)
    total = 0.
    for f in flows:
        if not math.isfinite(f.amount) or not isinstance(f.month, int) or f.month < 0:
            raise ValueError('Invalid cash flow')
        total += f.amount / (1 + rate) ** (f.month / 12)
    return total

def value_of(c: Cohort) -> float:
    return npv(initial_flows(c), c.discount)

def residual_required(c: Cohort) -> float:
    """Signed net cash equivalent at term-end, before lender/equity allocation.
    Negative means initial-term cash already exceeds the selected hurdle.
    """
    base = replace(c, residual=0)
    return -value_of(base) * (1 + c.discount) ** ((c.delay + c.months) / 12)

def annuity_years_paid_monthly(years: int, rate: float) -> float:
    if isinstance(years, bool) or not isinstance(years, int) or years <= 0:
        raise ValueError('Positive integer years required')
    finite_nonnegative('discount rate', rate)
    return sum((1 + rate) ** (-m / 12) / 12 for m in range(1, years * 12 + 1))

def total_collections(c: Cohort) -> float:
    return sum(f.amount for f in initial_flows(c) if f.kind in
               {'contract advance','service collection after advance credit'})

def first_cash_payback_month(c: Cohort) -> int | None:
    by_month: dict[int, float] = {}
    for flow in initial_flows(c):
        by_month[flow.month] = by_month.get(flow.month, 0.) + flow.amount
    cash = 0.
    for month in sorted(by_month):
        cash += by_month[month]
        if cash >= -1e-10:
            return month
    return None

def follow_on(c: Cohort, capital: float, annual_full_sales: float,
              utilization: float, price_factor: float, annual_variable_at_full: float,
              annual_fixed: float, years: int = 5) -> tuple[float, float]:
    """Alternative second cycle. No sale plus reuse; no new advance or final residual."""
    if c.residual:
        raise ValueError('Cannot sell first-cycle residual and reuse the entire cohort')
    for name, x in (('capital',capital),('sales',annual_full_sales),('price',price_factor),
                    ('variable cost',annual_variable_at_full),('fixed cost',annual_fixed)):
        finite_nonnegative(name, x)
    if not math.isfinite(utilization) or not 0 <= utilization <= 1:
        raise ValueError('Utilization outside [0,1]')
    if isinstance(years, bool) or not isinstance(years, int) or years <= 0:
        raise ValueError('Invalid second-cycle term')
    annual_cash = annual_full_sales * utilization * price_factor - annual_variable_at_full * utilization - annual_fixed
    end = c.delay + c.months
    flows = initial_flows(c) + [Flow(end, -capital, 'second-cycle capital')]
    flows += [Flow(end + m, annual_cash / 12, 'second-cycle net cash') for m in range(1, years * 12 + 1)]
    return npv(flows, c.discount), annual_cash

def required_tail_cash(c: Cohort, tail_capital: float, years: int = 5) -> float:
    finite_nonnegative('tail capital', tail_capital)
    return (residual_required(c) + tail_capital) / annuity_years_paid_monthly(years, c.discount)

def required_utilization(c: Cohort, tail_capital: float, annual_full_sales: float,
                         price_factor: float, annual_variable_at_full: float,
                         annual_fixed: float, years: int = 5) -> float:
    for name, x in (('sales',annual_full_sales),('price factor',price_factor),
                    ('variable costs',annual_variable_at_full),('fixed costs',annual_fixed)):
        finite_nonnegative(name, x)
    denom = annual_full_sales * price_factor - annual_variable_at_full
    if denom <= 0:
        return math.inf
    return (required_tail_cash(c, tail_capital, years) + annual_fixed) / denom

def annual_energy_twh(it_mw: float, pue: float, load: float) -> float:
    finite_nonnegative('IT MW', it_mw)
    if not math.isfinite(pue) or pue < 1 or not math.isfinite(load) or not 0 <= load <= 1:
        raise ValueError('Invalid PUE or electrical load')
    return it_mw * pue * load * 8760 / 1e6

def power_increment_bn(it_mw: float, pue: float, load: float, delta_per_kwh: float,
                       unhedged: float = 1.) -> float:
    finite_nonnegative('power-price increase', delta_per_kwh)
    if not math.isfinite(unhedged) or not 0 <= unhedged <= 1:
        raise ValueError('Invalid unhedged share')
    return annual_energy_twh(it_mw, pue, load) * delta_per_kwh * unhedged

def make_base(data: dict[str, Input]) -> Cohort:
    dc_mid = (val(data,'IR_DC_LOW') + val(data,'IR_DC_HIGH')) / 2
    cap = bn(data,'IR_GPU_CAPEX') + dc_mid * val(data,'IR_IT_MW') / 1000
    return Cohort(value=bn(data,'IR_TRANCHE_VALUE'), advance=bn(data,'IR_PREPAY'),
                  capital=cap, direct_cost_share=1-val(data,'IR_PROJECT_MARGIN'),
                  discount=val(data,'A_RATE'), months=int(val(data,'IR_AVG_YEARS')*12),
                  credit_start=int(val(data,'IR_FIRST_CREDIT_MONTH')))

def check(actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8):
        raise AssertionError(f'{actual} != {expected}')

def run_tests(data: dict[str, Input]) -> None:
    gpu=bn(data,'IR_GPU_CAPEX')
    c = make_base(data)
    check(c.advance, .2*c.value)
    check(total_collections(c), c.value)
    check(total_collections(replace(c, fee_loss=.1)), .9*c.value)
    check(sum(f.amount for f in initial_flows(c)), c.value*(1-c.direct_cost_share)-c.capital)
    check(annuity_years_paid_monthly(5,0),5)
    check(value_of(replace(c,residual=residual_required(c))),0)
    check(value_of(replace(c,discount=0,advance=0)),value_of(replace(c,discount=0)))
    check(value_of(replace(c,capital=gpu))-value_of(c),3.)
    check(annual_energy_twh(200,1.2,.9),1.89216)
    check(power_increment_bn(200,1.2,.9,.01),.0189216)
    check(power_increment_bn(200,1.2,.9,.01,0),0)
    check(val(data,'IR_DC_CORE_LOW')+val(data,'IR_DC_FLEX')+val(data,'IR_DC_ACCEL'),val(data,'IR_DC_LOW'))
    check(val(data,'IR_DC_CORE_HIGH')+val(data,'IR_DC_FLEX')+val(data,'IR_DC_ACCEL'),val(data,'IR_DC_HIGH'))
    for weaker in (replace(c,capital=c.capital+.2),replace(c,extra_cost_share=.05),replace(c,delay=6),replace(c,advance=0)):
        if value_of(weaker) >= value_of(c): raise AssertionError('Monotonicity failed')
    if value_of(replace(c,delay=6,advance_month=6)) >= value_of(replace(c,delay=6)):
        raise AssertionError('Advance timing failed')
    check(follow_on(c,6,required_tail_cash(c,6),1,1,0,0)[0],0)
    if data['IR_PREPAY'].status != 'contractual_obligation_not_receipt': raise AssertionError('Advance status')
    if data['IR_NEW_ARR_PER_MW'].status != 'company_claim_greater_than': raise AssertionError('Price status')
    if data['CW_DDTL4_COVER'].status != 'rating_projection': raise AssertionError('Rating status')
    if bn(data,'IR_TRANCHE_VALUE') >= bn(data,'IR_TCV_CEILING'): raise AssertionError('Contract totals')
    if bn(data,'IR_DDTL_DRAW')+bn(data,'IR_NOTES_ISSUED') >= bn(data,'IR_DDTL_LIMIT')+bn(data,'IR_NOTES_LIMIT'):
        raise AssertionError('Commitments and funding confused')
    invalid = [lambda: replace(c,discount=-.1), lambda: replace(c,months=0),
       lambda: replace(c,fee_loss=.9), lambda: replace(c,delay=1.5),
       lambda: replace(c,advance_month=1), lambda: replace(c,early_refresh_month=36),
       lambda: follow_on(replace(c,residual=1),6,4,.9,1,1,.2),
       lambda: annual_energy_twh(200,.9,.9), lambda: power_increment_bn(200,1.2,.9,.01,1.1),
       lambda: val(data,'IR_IT_MW','USD_million'),lambda: npv([Flow(1,float('nan'),'bad')],.1)]
    for fn in invalid:
        try: fn()
        except ValueError: continue
        raise AssertionError('Invalid input was accepted')

def print_results(data: dict[str, Input]) -> None:
    c = make_base(data); full = replace(c,extra_cost_share=val(data,'A_EXTRA_COST'))
    gpu = bn(data,'IR_GPU_CAPEX'); it = val(data,'IR_IT_MW','MW_IT')
    low_cap = gpu + it*val(data,'IR_DC_LOW')/1000
    high_cap = gpu + it*val(data,'IR_DC_HIGH')/1000
    print(f'{len(data)} inputs. USD billions unless labeled. All outputs are conditional, not actual project returns.')
    print(f'Tranche fees {c.value:.9f}; advance {c.advance:.9f}; midpoint capital {c.capital:.3f}')
    print(f'Unreconciled ceiling/table difference: {(bn(data,"IR_TCV_CEILING")-c.value)*1000:.6f} USD million')
    print('\nFIRST TERM: capital | cash share | NPV without residual | signed required end-value')
    for k in (gpu,low_cap,c.capital,high_cap):
        for extra in (0,val(data,'A_EXTRA_COST'),val(data,'A_EXTRA_HIGH')):
            m=replace(c,capital=k,extra_cost_share=extra)
            print(f'{k:.3f} | {1-m.direct_cost_share-extra:.0%} | {value_of(m):.6f} | {residual_required(m):.6f}')
    print(f'Equipment-only simple earnings payback: {gpu/(c.value/(c.months/12)*(1-c.direct_cost_share)):.6f} years')
    print(f'Equipment-only credited-advance cash payback: month {first_cash_payback_month(replace(c,capital=gpu))}')
    print(f'Combined 85% undiscounted cash before residual: {sum(f.amount for f in initial_flows(c)):.6f}')
    print(f'Advance timing NPV benefit, not extra fees: {value_of(c)-value_of(replace(c,advance=0)):.6f}')
    for r in (val(data,'A_RATE_LOW'),val(data,'A_RATE'),val(data,'A_RATE_HIGH')):
        m=replace(full,discount=r);print(f'80% cash, hurdle {r:.0%}: required end-value {residual_required(m):.6f}')
    print('\nDELAY: service months preserved; capital remains at modeled start')
    for delay in (0,int(val(data,'A_DELAY_6')),int(val(data,'A_DELAY_12'))):
        for advance_month in sorted({0,delay}):
            m=replace(c,delay=delay,advance_month=advance_month)
            print(f'Delay {delay} months; advance {advance_month}: NPV {value_of(m):.6f}; end-value {residual_required(m):.6f}')
    refresh=replace(full,early_refresh_month=int(val(data,'A_EARLY_REFRESH_MONTH')),early_refresh_cost=bn(data,'A_EARLY_REFRESH_COST'))
    good=replace(full,capital=low_cap,discount=val(data,'A_RATE_LOW'),residual=bn(data,'A_RESIDUAL'))
    bad=replace(full,capital=c.capital+(c.capital-gpu)*val(data,'A_DC_OVERRUN'),delay=int(val(data,'A_DELAY_12')),fee_loss=val(data,'A_FEE_LOSS'),residual=bn(data,'A_LOW_RESIDUAL'))
    print(f'Early major renewal, 80% case: {value_of(refresh):.6f}')
    print(f'Combined favorable: {value_of(good):.6f}; combined adverse: {value_of(bad):.6f}')
    print('\nFINANCING: separate from all-capital model')
    committed=bn(data,'IR_DDTL_LIMIT')+bn(data,'IR_NOTES_LIMIT')
    funded=bn(data,'IR_DDTL_DRAW')+bn(data,'IR_NOTES_ISSUED')
    print(f'Committed {committed:.3f}; funded/issued June {funded:.3f}, not all unrestricted')
    print(f'Commitments plus advance / equipment: {(committed+c.advance)/gpu:.6%}; other gross funding {c.capital-committed-c.advance:.6f}')
    finance_rate=val(data,'IR_FINANCE_RATE')
    for amount in (funded,committed): print(f'Constant {finance_rate:.0%} six-month carry on {amount:.3f}: {amount*finance_rate*.5:.6f}')
    print('\nELECTRICITY: assumed load/PUE; only incremental unhedged cost')
    for pue,load in ((val(data,'A_PUE_LOW'),val(data,'A_LOAD_LOW')),(val(data,'A_PUE'),val(data,'A_LOAD')),(val(data,'A_PUE_HIGH'),val(data,'A_LOAD_HIGH'))):
        e=annual_energy_twh(it,pue,load);inc=power_increment_bn(it,pue,load,val(data,'A_POWER_DELTA'))
        print(f'{pue} / {load:.0%}: {e:.6f} TWh; annual increment {inc:.6f}; five-year PV {inc*annuity_years_paid_monthly(5,c.discount):.6f}')
    print('\nCONTINUATION: no residual sale plus reuse')
    renewal=bn(data,'A_REPLACE')+bn(data,'A_RETROFIT')
    sales=it*val(data,'IR_NEW_ARR_PER_MW')/1000
    variable=val(data,'A_TAIL_VARIABLE','USD_million_per_year')/1000
    fixed=val(data,'A_TAIL_FIXED','USD_million_per_year')/1000
    tail_years=int(val(data,'A_TAIL_YEARS')); facility_years=int(val(data,'A_BUILD_TAIL'))
    weak_price=val(data,'A_TAIL_P_WEAK')
    for model,label in ((c,'85% initial cash'),(full,'80% initial cash')):
        print(f'{label}: 15-year facility-only annual cash {required_tail_cash(model,0,facility_years):.6f}')
        print(f'{label}: annual cash with 6bn replacement {required_tail_cash(model,renewal,tail_years):.6f}; paid utilization {required_utilization(model,renewal,sales,1,variable,fixed,tail_years):.6%}; 20% lower price {required_utilization(model,renewal,sales,weak_price,variable,fixed,tail_years):.6%}')
    for u,p in ((val(data,'A_TAIL_U_GOOD'),1),(.8,1),(val(data,'A_TAIL_U_WEAK'),weak_price)):
        n,annual=follow_on(full,renewal,sales,u,p,variable,fixed,tail_years)
        print(f'80% initial cash; second cycle u={u}, price={p}: annual cash {annual:.6f}; ten-year NPV {n:.6f}')
    print('\nMEASUREMENT RECONCILIATIONS, not utilization or appraisal')
    print(f'CoreWeave active/contracted {val(data,"CW_ACTIVE")/val(data,"CW_CONTRACTED"):.6%}; construction/gross PPE {val(data,"CW_CIP")/val(data,"CW_GROSS_PPE"):.6%}')
    print(f'Core Scientific annualized GAAP revenue/billing MW: {val(data,"CS_ARR")/val(data,"CS_BILL_MW"):.6f} USDm/MW-year')
    r=val(data,'CS_Q_REV');p=val(data,'CS_POWER');g=val(data,'CS_GP')
    print(f'Gross profit {g:.3f} USDm unchanged; margin with power {g/r:.6%}; without matching power {g/(r-p):.6%}')
    print('All conservation, status, unit, monotonicity and invalid-input checks passed.')

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path)
    args=parser.parse_args()
    own=Path(__file__).resolve()
    default=own.with_name(own.name.replace('calculations.py','data.csv'))
    data=load_inputs(args.data or default)
    run_tests(data)
    print_results(data)

if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,KeyError,AssertionError) as error:
        raise SystemExit(f'Calculation/check failed: {error}') from error
