#!/usr/bin/env python3
"""Is AI a Bubble? Cash, contractual thresholds and conditional recovery.

Python 3.10+, standard library only. No network access or file modification.
Run: python financing-calculations.py [financing-data.csv]

All money is USD millions; rates are decimal fractions. The source-linked CSV
separates reported actuals, rating expectations, contract terms, prospective
financing and explicit assumptions. These calculations do NOT establish actual
covenant compliance, a collateral valuation, a default probability or a complete
cash forecast. The report explains missing schedules, cash costs, reserve and
letter-of-credit balances, hedge payments and claim priorities.
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Observation:
    value: float
    unit: str
    status: str
    source: str


def finite(value: float, name: str, minimum: float | None = None,
           maximum: float | None = None) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def load(path: Path) -> dict[str, Observation]:
    fields = {"id", "entity", "metric", "period_start", "period_end", "value",
              "unit", "status", "source_id", "locator", "source_url", "notes"}
    result: dict[str, Observation] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not fields.issubset(set(reader.fieldnames or [])):
            raise ValueError("Input ledger is missing required columns")
        for line, row in enumerate(reader, start=2):
            key = row["id"].strip()
            if not key or key in result:
                raise ValueError(f"Blank or duplicate observation id on line {line}")
            value = finite(float(row["value"]), key)
            if row["status"] != "research_assumption" and not row["source_url"].startswith("https://"):
                raise ValueError(f"Observed input {key} lacks a source URL")
            if not row["notes"] or not row["period_end"] or not row["locator"]:
                raise ValueError(f"Input {key} lacks its boundary or locator")
            result[key] = Observation(value, row["unit"], row["status"], row["source_id"])
    if not result:
        raise ValueError("Input ledger is empty")
    return result


def get(data: dict[str, Observation], key: str, unit: str = "USD_million") -> float:
    if key not in data:
        raise ValueError(f"Missing observation {key}")
    obs = data[key]
    if obs.unit != unit:
        raise ValueError(f"{key}: expected {unit}, found {obs.unit}")
    return obs.value


def quarter_interest(principal: float, annual_cash_rate: float) -> float:
    """Constant-principal 3/12-year sensitivity, not actual daily accruals."""
    return finite(principal, "principal", 0) * finite(annual_cash_rate, "rate", 0) / 4


def collection_threshold(prior_costs: float, interest: float, amortization: float,
                         net_hedge_payment: float = 0, coverage: float = 1.15) -> float:
    """K + coverage*(I+A+H), without cure equity or other noncustomer receipts.

    Match the contract's eligible costs and period. Excluded initial/final
    principal and reserve replenishment require separate cash tests.
    """
    k = finite(prior_costs, "prior costs", 0)
    debt_service = (finite(interest, "interest", 0) + finite(amortization, "amortization", 0)
                    + finite(net_hedge_payment, "net hedge payment"))
    finite(debt_service, "net debt service", 0)
    return k + finite(coverage, "coverage", 1) * debt_service


def reserve_requirement(interest: Iterable[float], amortization: Iterable[float],
                        hedges: Iterable[float], operating: Iterable[float],
                        post_ctd: bool) -> float:
    """Each input contains candidate three-month totals, not monthly amounts.

    Before commitment termination use the next window; afterwards maximize
    categories separately. This abstracts the contract's exact inclusions.
    """
    groups = [tuple(x) for x in (interest, amortization, hedges, operating)]
    if any(not x for x in groups) or len({len(x) for x in groups}) != 1:
        raise ValueError("Reserve categories need nonempty equally sized windows")
    for i, group in enumerate(groups):
        for v in group:
            finite(v, f"reserve category {i}", 0)
    return sum(max(x) for x in groups) if post_ctd else sum(x[0] for x in groups)


def loss_allocation(principal: float, book_noncurrent: float,
                    realized_fraction: float, cash_recovery: float,
                    sale_cost_fraction: float, senior_claims: float = 0,
                    pari_passu_swap_claim: float = 0) -> tuple[float, float, float]:
    """Return (pool after prior claims, principal recovery, principal shortfall).

    Prior claims include fees, accrued interest and applicable premiums. Swap
    claims here rank alongside principal. Cash recovery is a scenario, not a
    claim that all reported current collateral is liquid or recoverable.
    """
    d = finite(principal, "principal", 0)
    b = finite(book_noncurrent, "book collateral", 0)
    q = finite(realized_fraction, "realized/book fraction", 0)
    c = finite(cash_recovery, "cash recovery", 0)
    x = finite(sale_cost_fraction, "sale cost fraction", 0, 1)
    h = finite(senior_claims, "prior claims", 0)
    t = finite(pari_passu_swap_claim, "pari-passu claim", 0)
    pool = max(0.0, b * q * (1 - x) + c - h)
    recovery = min(d, pool * d / (d + t)) if d + t else 0.0
    return pool, recovery, d - recovery


def gross_recovery_threshold(principal: float, book_noncurrent: float,
                             cash_recovery: float, sale_cost_fraction: float,
                             senior_claims: float = 0, pari_passu_swap_claim: float = 0) -> float:
    d = finite(principal, "principal", 0)
    b = finite(book_noncurrent, "book collateral", 0)
    c = finite(cash_recovery, "cash recovery", 0)
    x = finite(sale_cost_fraction, "sale costs", 0, 1)
    h = finite(senior_claims, "prior claims", 0)
    t = finite(pari_passu_swap_claim, "pari-passu claim", 0)
    if b <= 0 or x >= 1:
        raise ValueError("Positive collateral net of costs is required")
    return max(0.0, (d + h + t - c) / (b * (1 - x)))


def meta_partial_bridge(start_liquidity: float, h1_ocf: float, h2_multiplier: float,
                        full_year_capex: float, h1_capex: float,
                        repeated_other_uses: float) -> tuple[float, float, float]:
    """H2 sensitivity only, not a complete December cash forecast.

    OCF includes operating interest/taxes; capex includes finance-lease principal.
    May borrowing is already in June liquidity. Do not add it again or double
    deduct purchase commitments. Restricted escrow is outside starting liquidity.
    """
    for name, val in [("liquidity", start_liquidity), ("OCF", h1_ocf),
                      ("multiplier", h2_multiplier), ("full-year capex", full_year_capex),
                      ("H1 capex", h1_capex), ("other uses", repeated_other_uses)]:
        finite(val, name, 0)
    if full_year_capex < h1_capex:
        raise ValueError("Annual capex cannot be below the observed H1 in this model")
    h2_capex = full_year_capex - h1_capex
    h2_ocf = h1_ocf * h2_multiplier
    return h2_ocf, h2_capex, start_liquidity + h2_ocf - h2_capex - repeated_other_uses


def check_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7):
        raise AssertionError(f"{label}: {actual} != {expected}")


def run(data: dict[str, Observation]) -> None:
    v = lambda key: get(data, key)
    frac = lambda key: get(data, key, "fraction")
    rate = lambda key: get(data, key, "fraction_per_year")
    print(f"Ledger validated: {len(data)} unique rows. Currency: USD millions.")
    print("Scenarios are conditional; none establishes current compliance.\n")

    print("COREWEAVE: January-June 2026 consolidated cash")
    check_close(v("CW09") - v("CW04") - v("CW11") + v("CW10") - v("CW12"), v("CW08"), "financing")
    change = v("CW02") + v("CW07") + v("CW08")
    check_close(v("CW17") + change, v("CW16"), "cash including restricted")
    check_close(v("CW18") + v("CW19") + v("CW20"), v("CW16"), "restricted split")
    before_interest = v("CW02") + v("CW05")
    debt_cash = v("CW04") + v("CW05") + v("CW06")
    debt_residual = before_interest - debt_cash
    noninterest_ppe = v("CW03") - v("CW06")
    all_residual = debt_residual - noninterest_ppe
    check_close(all_residual, v("CW02") - v("CW03") - v("CW04"), "no duplicate interest")
    print(f"Before expensed interest {before_interest:,.3f}; principal plus total interest {debt_cash:,.3f}")
    print(f"Residual before non-interest PPE {debt_residual:,.3f}; after {all_residual:,.3f}")
    print(f"Cash change {change:,.3f}; ending including restricted {v('CW16'):,.3f}")
    print(f"Deferred balance change {v('CW23')-v('CW24'):,.3f}; cash-flow adjustment {v('CW14'):,.3f}")
    schedule = sum(v(f"CW{i}") for i in range(26,32))
    check_close(schedule, v("CW21"), "principal schedule")
    print(f"June principal {schedule:,.3f}; remainder-2026 plus 2027 {v('CW26')+v('CW27'):,.3f}\n")

    print("DDTL 4.0: required cash, actual costs and installments unknown")
    d, c = v("D01"), v("D03")
    coverage = get(data,"D05","times")
    for key in ("S01","S02","S03"):
        i = quarter_interest(d, rate(key))
        print(f"Assumed cash rate {rate(key):.1%}: three-month interest {i:,.4f}; coverage intercept {coverage*i:,.4f}")
        print(f"  Cash-only upper-bound reserve capacity after interest {c-i:,.4f}")
    example_i = quarter_interest(d, rate("S02"))
    requirement = collection_threshold(v("S11"),example_i,v("S10"),coverage=coverage)
    payment = collection_threshold(v("S11"),example_i,v("S10"),coverage=1)
    check_close(requirement,166.43825,"illustrative collection threshold")
    check_close(payment,152.555,"illustrative payment floor")
    print(f"Assumed K=60, A=50, H=0, rate=6%: collection {requirement:,.5f}; payment {payment:,.5f}")
    projected = get(data,"D06","times")
    print(f"IF comparable starting coverage is 1.20: NOI decline to 1.15 {1-coverage/projected:.4%}; to 1.00 {1-1/projected:.4%}")
    early = reserve_requirement([10,8],[20,30],[1,2],[40,35],False)
    later = reserve_requirement([10,8],[20,30],[1,2],[40,35],True)
    check_close(early,71,"reserve next window")
    check_close(later,82,"reserve separate maxima")
    print("Synthetic reserve test: next window 71; separate category maxima 82, not max-combined-window 75.\n")

    print("DDTL 4.0: backup realization, NOT expected loan loss")
    b, x = v("D02"), frac("S04")
    for cash in (c,0):
        threshold = gross_recovery_threshold(d,b,cash,x)
        print(f"Assumed recovered cash {cash:,.1f}: required gross noncurrent realization {threshold:.4%} of book")
        for key in ("S07","S06","S05"):
            pool,recovery,loss = loss_allocation(d,b,frac(key),cash,x)
            check_close(recovery+loss,d,"principal allocation")
            print(f"  {frac(key):.0%} of book: pool {pool:,.3f}; principal paid {recovery:,.3f}; shortfall {loss:,.3f}")
    stress = loss_allocation(d,b,frac("S06"),c,x,senior_claims=100,pari_passu_swap_claim=100)
    print(f"At 75%, $155m cash, plus assumed $100m prior and $100m pari-passu claims: shortfall {stress[2]:,.3f}\n")

    print("SEPTEMBER NOTES: priced 18 September; expected settlement 22 September")
    available = v("N02")-v("N03")
    coupon = v("N01")*rate("N04")
    check_close(available,3145.7,"prospective proceeds after capped calls")
    check_close(coupon,106.375,"nominal annual cash coupon")
    print(f"Face {v('N01'):,.3f}; prospective available cash {available:,.3f} before other expenses")
    print(f"Annual coupon {coupon:,.3f}; option not assumed; no received proceeds at the 20 September evidence boundary.\n")

    print("META: partial H2 sensitivity, no new financing assumed")
    h1_capex = v("M02")+v("M03")
    other = v("M04")+v("M05")
    check_close(v("M01")-h1_capex,13170,"H1 free cash flow definition")
    print(f"H1 capex with lease principal {h1_capex:,.3f}; repeated RSU-tax/dividend uses assumed {other:,.3f}")
    expected = iter((63863,48863,44636.6,29636.6))
    for mult_key in ("S09","S08"):
        for capex_key in ("M21","M22"):
            ocf,capex,residual = meta_partial_bridge(v("M09"),v("M01"),frac(mult_key),v(capex_key),h1_capex,other)
            check_close(residual,next(expected),"Meta partial bridge")
            print(f"OCF multiplier {frac(mult_key):.0%}, FY capex {v(capex_key):,.0f}: H2 OCF {ocf:,.3f}; H2 capex {capex:,.3f}; residual {residual:,.3f}")

    if data["V07"].status != "contractual_obligation_receipt_unverified":
        raise AssertionError("Prepaid-forward receipt correction was not preserved")
    print("\nNVIDIA: $1.5bn forward is an obligation with receipt unverified; no cash adjustment.")
    print("The $105bn guarantee ceiling is not added to current debt, cash or modeled losses.")
    check_close(loss_allocation(100,100,0,0,.05)[2],100,"zero recovery")
    check_close(loss_allocation(100,100,2,0,.05)[2],0,"surplus recovery")
    check_close(loss_allocation(0,100,1,0,.05)[1],0,"zero principal")
    invalid_calls = [lambda: quarter_interest(float('nan'),.06),
                     lambda: quarter_interest(-1,.06),
                     lambda: loss_allocation(1,1,1,1,1.1),
                     lambda: gross_recovery_threshold(1,0,0,.05),
                     lambda: reserve_requirement([],[],[],[],True),
                     lambda: meta_partial_bridge(1,1,1,0,1,0)]
    for call in invalid_calls:
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid-input test failed")
    print("\nAll identity, allocation, status, unit and invalid-input checks passed.")


def main() -> None:
    here = Path(__file__).resolve()
    sibling = here.with_name(here.name.replace("calculations.py", "data.csv"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", nargs="?", type=Path,
                        default=sibling if sibling.exists() else here.with_name("financing-data.csv"))
    args = parser.parse_args()
    run(load(args.data))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        raise SystemExit(f"Calculation failed: {exc}") from exc
