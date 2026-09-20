#!/usr/bin/env python3
"""Real customers, uneven capture: buyer value and recovery sensitivities.

Python 3.10+, standard library only; no network requests or file modifications.
Save beside demand-observations.csv, then run:
  python demand-calculations.py
or supply --observations /path/to/demand-observations.csv.

This reader companion implements Demand analysis's supplied equations, assumptions
and checks. Source inputs are identified by observation ID. All other parameters
are illustrative assumptions, NOT measured industry averages. The recovery
model preserves the whole-system assessment’s hypothetical cohort, not an actual fleet valuation.
"""
from __future__ import annotations
import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_observations(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            key = row['observation_id']
            require(bool(key) and key not in out, f'Missing/duplicate ID: {key}')
            require(math.isfinite(float(row['value'])), f'Nonfinite value: {key}')
            out[key] = row
    require(bool(out), 'Observation file is empty')
    return out


def number(data: dict[str, dict[str, str]], key: str, unit: str) -> float:
    row = data[key]
    require(row['unit'] == unit, f'Unexpected unit for {key}: {row["unit"]}')
    return float(row['value'])


@dataclass(frozen=True)
class SupportAssumptions:
    """Illustrative monthly buyer cash parameters; not Fin customer averages."""
    contacts: int = 10_000
    billed_fraction: float = 0.60
    cash_avoidable_cost_per_contact: float = 4.0
    review_cost_per_contact: float = 0.20
    fixed_implementation_and_governance: float = 2_000.0


def support_net(avoided_fraction: float, price: float,
                a: SupportAssumptions = SupportAssumptions()) -> float:
    require(0 <= avoided_fraction <= 1 and 0 <= a.billed_fraction <= 1,
            'Fractions must lie in [0,1]')
    require(a.contacts > 0 and min(price, a.cash_avoidable_cost_per_contact,
            a.review_cost_per_contact, a.fixed_implementation_and_governance) >= 0,
            'Invalid support cost input')
    return a.contacts * (avoided_fraction * a.cash_avoidable_cost_per_contact
                         - a.billed_fraction * price - a.review_cost_per_contact) \
        - a.fixed_implementation_and_governance


def support_break_even(price: float, a: SupportAssumptions) -> float:
    require(a.cash_avoidable_cost_per_contact > 0, 'No cash saving when avoidable cost is zero')
    return (a.billed_fraction * price + a.review_cost_per_contact
            + a.fixed_implementation_and_governance / a.contacts) \
        / a.cash_avoidable_cost_per_contact


@dataclass(frozen=True)
class OfficeAssumptions:
    """Illustrative buyer year-one parameters, not study-measured wages/costs."""
    working_weeks: int = 46
    loaded_hour_value: float = 40.0
    additional_year_one_cost: float = 180.0


def office_economics(hours_saved: float, monthly_fee: float,
                     a: OfficeAssumptions = OfficeAssumptions()) -> tuple[float, float, float]:
    require(hours_saved > 0 and monthly_fee >= 0 and a.working_weeks > 0
            and a.loaded_hour_value > 0 and a.additional_year_one_cost >= 0,
            'Invalid office assumptions')
    capacity_value = hours_saved * a.working_weeks * a.loaded_hour_value
    cost = 12 * monthly_fee + a.additional_year_one_cost
    return capacity_value, cost, cost / capacity_value


def annuity_factor(years: int, rate: float) -> float:
    require(years > 0 and rate > -1, 'Invalid annuity assumptions')
    return sum((1 + rate) ** (-year) for year in range(1, years + 1))


@dataclass(frozen=True)
class RecoveryAssumptions:
    """the whole-system assessment’s zero-residual, level annual pre-financing cash model.

    Baseline revenue = 100; variable cash costs = 35; fixed cash costs = 15.
    This 35/15 split is wholly assumed, not company disclosure. Costs include
    operating, tax and maintenance needs in aggregate. Actual tax and maintenance
    need not behave this way. Discounting is all-capital: do not deduct interest
    again. No growth capex or residual value is included.
    """
    years: int = 4
    rate: float = 0.10
    base_revenue_units: float = 100.0
    variable_cost_units: float = 35.0
    fixed_cost_units: float = 15.0


@dataclass(frozen=True)
class Stress:
    label: str
    price_ratio: float
    volume_ratio: float
    unit_variable_cost_ratio: float


def recovery_stress(cost: float, s: Stress,
                    a: RecoveryAssumptions = RecoveryAssumptions()) -> tuple[float, float, float, float]:
    require(cost > 0 and min(s.price_ratio, s.volume_ratio,
                            s.unit_variable_cost_ratio) >= 0, 'Invalid stress')
    base_cash = a.base_revenue_units - a.variable_cost_units - a.fixed_cost_units
    require(base_cash > 0, 'Baseline cash must be positive')
    revenue = a.base_revenue_units * s.price_ratio * s.volume_ratio
    variable_cost = a.variable_cost_units * s.unit_variable_cost_ratio * s.volume_ratio
    cash = revenue - variable_cost - a.fixed_cost_units
    scale = cost / (base_cash * annuity_factor(a.years, a.rate))
    npv = -cost + cash * scale * annuity_factor(a.years, a.rate)
    return revenue, variable_cost, cash, npv


def volume_to_restore_cash(price_ratio: float, unit_cost_ratio: float,
                           a: RecoveryAssumptions = RecoveryAssumptions()) -> float:
    contribution = a.base_revenue_units * price_ratio - a.variable_cost_units * unit_cost_ratio
    require(contribution > 0, 'No finite volume restores cash with nonpositive contribution')
    return (a.base_revenue_units - a.variable_cost_units) / contribution


def close(actual: float, expected: float) -> None:
    require(math.isclose(actual, expected, abs_tol=1e-8, rel_tol=1e-10),
            f'Check failed: {actual} != {expected}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path,
                        default=Path(__file__).resolve().with_name('demand-observations.csv'))
    args = parser.parse_args()
    data = read_observations(args.observations)
    gain = number(data, 'SUP01', 'fraction')
    print(f'SUPPORT: {gain:.1%} throughput gain -> {gain/(1+gain):.4%} fewer hours for fixed output')
    price = number(data, 'PRI01', 'USD_per_outcome')
    a = SupportAssumptions()
    for q in (0.50, 0.20):
        print(f'  Avoided-contact fraction {q:.0%}: monthly buyer cash benefit ${support_net(q,price,a):,.2f}')
    threshold = support_break_even(price, a)
    print(f'  Break-even truly avoided-contact fraction: {threshold:.4%}')
    close(support_net(threshold, price, a), 0)
    close(support_net(.50, price), 10060)
    close(support_net(.20, price), -1940)

    fee = number(data, 'PRI02', 'USD_per_user_month')
    hours = number(data, 'OFF02', 'hours_per_worker_week')
    capacity, cost, fraction = office_economics(hours, fee)
    print(f'OFFICE: gross annual capacity value ${capacity:,.2f}; year-one incremental cost ${cost:,.2f}')
    print(f'  Break-even realized-value share {fraction:.4%}; equivalent minutes/week {hours*fraction*60:.4f}')
    for share in (.10, .25, .50):
        print(f'  Realized share {share:.0%}: net annual buyer value ${capacity*share-cost:,.2f}')
    close(capacity, 2576); close(cost, 540)

    current_rev = number(data, 'KLA01', 'USD_million')
    prior_rev = number(data, 'KLA02', 'USD_million')
    current_cost = number(data, 'KLA03', 'USD_million')
    prior_cost = number(data, 'KLA04', 'USD_million')
    print(f'KLARNA reported expense/revenue: {prior_cost/prior_rev:.4%} -> {current_cost/current_rev:.4%}')
    print(f'  Absolute expense growth {current_cost/prior_cost-1:.4%}; revenue growth {current_rev/prior_rev-1:.4%}')
    price_decline = number(data,'RAM04','USD_per_million_tokens') / number(data,'RAM03','USD_per_million_tokens') - 1
    tail_change = number(data,'RAM06','USD_per_employee_month') / number(data,'RAM05','USD_per_employee_month') - 1
    print(f'RAMP arithmetic only: mix-sensitive token price {price_decline:.4%}; revised tail spend {tail_change:.4%}')

    c = number(data, 'BASE01', 'USD_million')
    r = RecoveryAssumptions()
    af = annuity_factor(r.years, r.rate)
    close(af, (1-(1+r.rate)**(-r.years))/r.rate)
    base_revenue = c / (.5 * af)
    print(f'WHOLE-SYSTEM BRIDGE: hypothetical cost ${c/1000:.3f}bn; annual revenue ${base_revenue/1000:.6f}bn')
    print('  All NPVs below are USD billion; not actual project estimates.')
    scenarios = [
        Stress('Unchanged baseline',1,1,1),
        Stress('Price -20%; volume flat; unit cost flat',.8,1,1),
        Stress('Price -20%; volume +25%; unit cost flat',.8,1.25,1),
        Stress('Price -20%; volume +25%; unit cost -20%',.8,1.25,.8),
        Stress('Volume -20%; price and unit cost flat',1,.8,1),
    ]
    expected_npvs = (0, -.4*c, -.175*c, 0, -.26*c)
    for s, expected in zip(scenarios, expected_npvs):
        revenue, variable, cash, npv = recovery_stress(c, s, r)
        close(npv, expected)
        print(f'  {s.label}: revenue {revenue:.2f}; variable cost {variable:.2f}; cash {cash:.2f}; NPV {npv/1000:+.6f}')
    flatcost_volume = volume_to_restore_cash(.8, 1)
    improvedcost_volume = volume_to_restore_cash(.8, .8)
    close(flatcost_volume, 13/9); close(improvedcost_volume,1.25)
    print(f'  Volume increase to restore baseline cash after 20% price cut: {flatcost_volume-1:.4%} with flat unit cost; {improvedcost_volume-1:.4%} with 20% lower unit cost')
    for bad in (Stress('bad',-1,1,1), Stress('bad',1,-1,1)):
        try:
            recovery_stress(c, bad)
        except ValueError:
            pass
        else:
            raise ValueError('Negative-input validation failed')
    print(f'All identity, unit, numerical and invalid-input checks passed; {len(data)} source observations read.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit(f'Calculation failed: {error}') from error
