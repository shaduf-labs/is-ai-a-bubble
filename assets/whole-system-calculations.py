#!/usr/bin/env python3
"""Reproduce the whole-system reader account; Python 3.10+, standard library only.

Usage: python whole-system-calculations.py [--ledger /path/to/whole-system-financial-ledger.csv]
Save the companion CSV in the same folder or supply its path with --ledger.
Source-linked input periods and statuses are in the CSV. Evidence retrieval
boundary: 18 September 2026; it is not a current-data feed or publication date.

All financial inputs are USD millions unless noted. Whole-parent figures are
not AI-only. The trailing year and half-year overlap. OCF minus gross purchases
is a limited subtraction, not company-defined free cash flow. Revenue and
operating income along a supply chain are not summed as independent demand.

Recovery and valuation assumptions are conditional, not company forecasts,
fair-value estimates or measured funding shortfalls. The Microsoft equity
input comes from an unreconciled timestamped observation without a durable
vendor URL; it is used only as a scenario, not a verified current quotation.
The original mathematical functions are retained. No network access,
fetched code, or external packages. Run without Python's -O flag so the
arithmetic checks remain enabled. Passing them does not fact-check sources.
"""
from __future__ import annotations
import argparse
import csv
import math
from pathlib import Path
from typing import Iterable


def read_ledger(path: Path) -> dict[tuple[str, str, str, str], float]:
    out: dict[tuple[str, str, str, str], float] = {}
    with path.open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            key = tuple(row[k] for k in ('entity', 'metric', 'period_start', 'period_end'))
            if key in out:
                raise ValueError(f'Duplicate input: {key}')
            value = float(row['value'])
            if not math.isfinite(value):
                raise ValueError(f'Nonfinite input: {key}')
            out[key] = value
    if not out:
        raise ValueError('Empty ledger')
    return out


def annuity_factor(years: int, rate: float, delay: int = 0,
                   annual_revenue_decline: float = 0.0) -> float:
    """PV of revenue 1 in first operating year, then a specified decline.

    delay=1 moves all operating-year receipts back one calendar year; it does
    not shorten the operating life. Receipts occur at year end.
    """
    if years < 1 or rate <= -1 or delay < 0 or not 0 <= annual_revenue_decline < 1:
        raise ValueError('Invalid discounting assumptions')
    return sum((1 - annual_revenue_decline) ** (t - 1) /
               (1 + rate) ** (t + delay) for t in range(1, years + 1))


def recovery_revenue(cost: float, margin: float, years: int, rate: float,
                     delay: int = 0, decline: float = 0.0) -> float:
    """Required first-year revenue; zero residual value, all cost at time zero.

    margin is hypothetical cash available to all capital providers after
    operating costs, taxes and maintenance, before financing payments. Do not
    also deduct debt interest: rate is an illustrative all-capital hurdle.
    """
    if cost <= 0 or not 0 < margin <= 1:
        raise ValueError('Cost and margin must be positive; margin <= 1')
    return cost / (margin * annuity_factor(years, rate, delay, decline))


def equity_dcf(initial_cash: float, growth: float, rate: float,
               terminal_growth: float = .03, years: int = 10) -> float:
    if initial_cash <= 0 or rate <= terminal_growth or growth <= -1:
        raise ValueError('Invalid DCF assumptions')
    explicit = sum(initial_cash * (1 + growth) ** t / (1 + rate) ** t
                   for t in range(1, years + 1))
    terminal_cash = initial_cash * (1 + growth) ** years * (1 + terminal_growth)
    terminal = terminal_cash / (rate - terminal_growth) / (1 + rate) ** years
    return explicit + terminal


def reverse_growth(value: float, initial_cash: float, rate: float,
                   terminal_growth: float = .03, years: int = 10) -> float:
    low, high = -.90, 1.0
    if not equity_dcf(initial_cash, low, rate, terminal_growth, years) < value < \
            equity_dcf(initial_cash, high, rate, terminal_growth, years):
        raise ValueError('Root not bracketed')
    for _ in range(150):
        mid = (low + high) / 2
        if equity_dcf(initial_cash, mid, rate, terminal_growth, years) < value:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def delayed_distribution_hurdle(value: float, rate: float, terminal_growth: float,
                               no_distribution_years: int) -> float:
    """FCF in year n+1 needed if years 1..n distribute zero, then perpetuity."""
    if value <= 0 or rate <= terminal_growth or no_distribution_years < 0:
        raise ValueError('Invalid endpoint assumptions')
    return value * (rate - terminal_growth) * (1 + rate) ** no_distribution_years


def self_test() -> None:
    assert math.isclose(annuity_factor(4, .10), (1 - 1.1 ** -4) / .10)
    base = recovery_revenue(14117, .5, 4, .10)
    assert math.isclose(base * .5 * annuity_factor(4, .1), 14117)
    assert math.isclose(recovery_revenue(14117, .5, 4, .1, delay=1), base * 1.1)
    growth = reverse_growth(3692273.3, 63886, .1)
    assert math.isclose(equity_dcf(63886, growth, .1), 3692273.3, rel_tol=1e-12)
    hurdle = delayed_distribution_hurdle(852000, .1, .03, 10)
    assert math.isclose(hurdle / (.1 - .03) / 1.1 ** 10, 852000)


def main() -> None:
    folder = Path(__file__).resolve().parent
    default = folder/'whole-system-financial-ledger.csv'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, default=default)
    args = parser.parse_args()
    data = read_ledger(args.ledger)
    self_test()

    def get(entity: str, metric: str, start: str, end: str) -> float:
        return data[(entity, metric, start, end)]
    def ttm(entity: str, metric: str) -> float:
        if entity in ('Microsoft', 'Amazon'):
            return get(entity, metric, '2025-07-01', '2026-06-30')
        return (get(entity, metric, '2025-01-01', '2025-12-31') +
                get(entity, metric, '2026-01-01', '2026-06-30') -
                get(entity, metric, '2025-01-01', '2025-06-30'))
    metrics = ('revenue', 'operating_income', 'operating_cash_flow', 'cash_ppe')
    entities = ('Microsoft', 'Alphabet', 'Amazon', 'Meta')
    print('MATCHED WHOLE-PARENT WINDOWS: July 2025–June 2026, USD billions; NOT AI-only')
    print('The residual is a limited subtraction, not issuer-defined free cash flow. Do not sum revenues as final demand.')
    print('Entity | Revenue | Operating income | OCF | Cash PP&E | OCF minus cash PP&E')
    total_ocf = total_ppe = 0.0
    for entity in entities:
        vals = [ttm(entity, metric) / 1000 for metric in metrics]
        total_ocf += vals[2]; total_ppe += vals[3]
        print(entity, '|', ' | '.join(f'{x:.3f}' for x in vals), '|', f'{vals[2]-vals[3]:.3f}')
    print(f'Four-parent OCF {total_ocf:.3f}; PP&E {total_ppe:.3f}; residual {total_ocf-total_ppe:.3f}; share {total_ppe/total_ocf:.2%}')
    assert math.isclose(total_ppe, 510.703)
    print('\nJANUARY-JUNE 2026 CASH WINDOW, USD billions; contained within the trailing year, not additive')
    h1_ocf = h1_ppe = 0.0
    for entity in entities:
        if entity == 'Microsoft':
            ocf = ttm(entity, 'operating_cash_flow') - get(entity, 'operating_cash_flow', '2025-07-01', '2025-12-31')
            ppe = ttm(entity, 'cash_ppe') - get(entity, 'cash_ppe', '2025-07-01', '2025-12-31')
        else:
            ocf = get(entity, 'operating_cash_flow', '2026-01-01', '2026-06-30')
            ppe = get(entity, 'cash_ppe', '2026-01-01', '2026-06-30')
        h1_ocf += ocf; h1_ppe += ppe
        print(f'{entity}: OCF {ocf/1000:.3f}; cash PP&E {ppe/1000:.3f}; difference {(ocf-ppe)/1000:.3f}')
    print(f'Total OCF {h1_ocf/1000:.3f}; PP&E {h1_ppe/1000:.3f}; share {h1_ppe/h1_ocf:.2%}')
    assert math.isclose(h1_ppe, 294800)
    amazon_fc = ttm('Amazon', 'operating_cash_flow') - ttm('Amazon', 'cash_ppe') + get('Amazon','ppe_disposal_proceeds_and_incentives','2025-07-01','2026-06-30')
    assert amazon_fc == get('Amazon','company_free_cash_flow','2025-07-01','2026-06-30')
    print(f'Amazon issuer-FCF reconciliation: {amazon_fc/1000:.3f}')

    principal = get('CoreWeave', 'debt_principal', '', '2026-06-30')
    buckets = [get('CoreWeave', 'debt_due_'+key, '', '2026-06-30') for key in
               ('remaining_2026','2027','2028','2029','2030','later')]
    assert sum(buckets) == principal
    print('\nJUNE SNAPSHOT ONLY: not a September balance; later proposals are not verified proceeds.')
    print(f'CoreWeave principal {principal/1000:.3f}; through 2027 {sum(buckets[:2])/1000:.3f}; share {sum(buckets[:2])/principal:.2%}')
    print('CoreWeave H1 OCF less cash investment: '
          f"{(get('CoreWeave','operating_cash_flow','2026-01-01','2026-06-30')-get('CoreWeave','cash_ppe','2026-01-01','2026-06-30'))/1000:.3f}")
    cost = get('CoreWeave','cash_ppe','2026-01-01','2026-06-30')
    print('\nRECOVERY HURDLES: required annual revenue, USD billions; 10% hurdle; zero residual')
    for life in (3,4,6):
        print(life, 'years:', ', '.join(f'{margin:.0%} margin -> {recovery_revenue(cost,margin,life,.10)/1000:.3f}' for margin in (.4,.5,.6)))
    base = recovery_revenue(cost,.5,4,.1)
    for description, delay, decline in [('Base',0,0),('One-year delay',1,0),('10% annual revenue decline',0,.1),('20% annual revenue decline',0,.2)]:
        print(f'{description}: first-year revenue {recovery_revenue(cost,.5,4,.1,delay,decline)/1000:.3f}')
    print(f'20% level revenue shortfall, constant margin: NPV {-0.2*cost/1000:.3f}; fixed costs can worsen this.')

    value = get('Microsoft','market_equity_value','','2026-09-17T19:29:50Z')
    cash = ttm('Microsoft','operating_cash_flow') - ttm('Microsoft','cash_ppe') - get('Microsoft','finance_lease_principal','2025-07-01','2026-06-30')
    sbc = get('Microsoft','stock_compensation','2025-07-01','2026-06-30')
    print('\nSCENARIO ONLY: timestamped equity input lacks a durable vendor URL and share-count reconciliation; not a verified current quote.')
    print(f'MICROSOFT conditional reverse equity DCF: assumed value {value/1000:.3f}bn, cash proxy {cash/1000:.3f}bn, proxy less SBC {(cash-sbc)/1000:.3f}bn')
    print(f'Assumed value/cash proxy {value/cash:.2f}x; conditional proxy/value {cash/value:.2%}')
    for rate in (.08,.10,.12):
        for label, initial in [('cash proxy',cash),('less full grant-date SBC expense',cash-sbc)]:
            growth = reverse_growth(value, initial, rate)
            terminal_cash = initial*(1+growth)**10*1.03
            terminal_pv = terminal_cash/(rate-.03)/(1+rate)**10
            print(f'r={rate:.0%}, {label}: ten-year annual growth {growth:.2%}; year10 cash {initial*(1+growth)**10/1000:.3f}bn; terminal PV share {terminal_pv/value:.2%}')
    print('\nPRIVATE ENDPOINT TEST: no distributions years 1–10, then perpetual growth 3%')
    for entity, date in [('OpenAI','2026-03-31'),('Anthropic','2026-05-28')]:
        equity = get(entity,'round_postmoney_equity_value','',date)
        runrate = get(entity,'monthly_revenue_claim','',date)*12 if entity == 'OpenAI' else get(entity,'annual_revenue_run_rate_claim','',date)
        print(f'{entity}: dated equity/run-rate {equity/runrate:.2f}x')
        for rate in (.08,.10,.12):
            fcf11 = delayed_distribution_hurdle(equity, rate, .03, 10)
            print(f'  r={rate:.0%}: year11 cash {fcf11/1000:.3f}bn; revenue at 25% all-cost cash margin {fcf11/.25/1000:.3f}bn')
    print('\nAll reconstruction, schedule, reconciliation and model identity checks passed. This verifies arithmetic, not sources or economic assumptions.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit(f'Calculation failed: {exc}') from exc
