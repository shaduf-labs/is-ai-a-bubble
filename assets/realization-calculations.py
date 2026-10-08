#!/usr/bin/env python3
"""Realized receipts and historical claim allocation, not a current valuation.

Python 3.10+, standard library only. No network, trades or input modifications.
Run beside realization-data.csv or the matching delivery-prefixed ledger:
    python realization-calculations.py [--data PATH] [--no-tests]

Outputs use USD and nominal shares. Decimal arithmetic preserves disclosed
precision; share counts reported in thousands remain rounded observations.
The sale model freezes March 2025 capital and compares a then-live put with its
absence. The actual put terminated in September 2025. It is NOT a 2026 liability,
a prediction of a company sale, a bankruptcy waterfall or an investor IRR.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from fractions import Fraction
import json
from pathlib import Path
import random
from typing import Callable

getcontext().prec = 40
D = Decimal
ZERO, ONE = D(0), D(1)
STATUSES = {
    'executed_terms', 'contractual_limit', 'issuer_estimate',
    'prospectus_pro_forma', 'reported_rounded', 'reported_receipt',
    'reported_acquisition', 'reported_actual', 'source_conflict',
    'inherited_reported', 'research_assumption',
}
UNITS = {'USD', 'USD_per_share', 'shares', 'fraction', 'multiple'}
FIELDS = ('id','entity','claim','metric','value','unit','observation_period',
          'status','source_id','source_date','source_url','locator','qualification')

@dataclass(frozen=True)
class Observation:
    value: Decimal
    unit: str
    status: str
    row: dict[str, str]

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

def finite(x: Decimal, name: str, *, positive: bool = False) -> None:
    require(x.is_finite(), f'{name}: finite value required')
    require(x > 0 if positive else x >= 0, f'{name}: invalid sign')

def load_inputs(path: Path) -> dict[str, Observation]:
    with path.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        require(tuple(reader.fieldnames or ()) == FIELDS, 'Unexpected CSV schema')
        result: dict[str, Observation] = {}
        for line, row in enumerate(reader, 2):
            require(None not in row and all(isinstance(row.get(k), str) and row[k].strip() for k in FIELDS),
                    f'Line {line}: incomplete record')
            key = row['id']
            require(key not in result, f'Duplicate id {key}')
            require(row['status'] in STATUSES, f'{key}: unknown status')
            require(row['unit'] in UNITS, f'{key}: unknown unit')
            require(row['source_url'].startswith(('https://','../','report.md')),
                    f'{key}: invalid source path')
            try:
                value = D(row['value'])
            except InvalidOperation as exc:
                raise ValueError(f'{key}: invalid decimal') from exc
            require(value.is_finite(), f'{key}: non-finite value')
            if row['unit'] in {'shares','USD_per_share','fraction','multiple'}:
                require(value >= 0, f'{key}: negative noncash-domain input')
            if row['unit'] == 'shares':
                require(value == value.to_integral_value(), f'{key}: fractional shares')
            if row['unit'] == 'fraction':
                require(value <= 1, f'{key}: fraction exceeds one')
            if row['status'] == 'research_assumption':
                require(row['source_id'] == 'MODEL', f'{key}: assumption provenance')
            result[key] = Observation(value, row['unit'], row['status'], row)
    require(bool(result), 'Empty ledger')
    return result

def get(data: dict[str, Observation], key: str, unit: str,
        *, status: str | None = None, allow_conflict: bool = False) -> Decimal:
    require(key in data, f'Missing input {key}')
    row = data[key]
    require(row.unit == unit, f'{key}: expected {unit}, got {row.unit}')
    require(allow_conflict or row.status != 'source_conflict',
            f'{key}: source conflict cannot become an ordinary model input')
    if status is not None:
        require(row.status == status, f'{key}: expected evidence status {status}')
    return row.value

def offering(primary: Decimal, secondary: Decimal, price: Decimal,
             discount: Decimal) -> dict[str, Decimal]:
    """One cash offering; primary and secondary proceeds are NOT two issuer receipts."""
    for x, name in [(primary,'primary'),(secondary,'secondary'),(discount,'discount')]:
        finite(x,name)
    finite(price,'price',positive=True)
    require(discount < price, 'Discount must be smaller than public price')
    total = primary + secondary
    require(total > 0, 'Offering must contain shares')
    return {
        'public_cash': total*price,
        'issuer_gross': primary*price,
        'seller_gross': secondary*price,
        'issuer_underwriting': primary*discount,
        'seller_underwriting': secondary*discount,
        'issuer_net_before_other_costs': primary*(price-discount),
        'seller_net_before_other_costs': secondary*(price-discount),
        'total_underwriting': total*discount,
        'primary_fraction': primary/total,
    }

def sale_allocation(total_shares: Decimal, protected_shares: Decimal,
                    floor: Decimal, equity_pot: Decimal,
                    *, live_right: bool) -> dict[str, Decimal]:
    """Solvent company-sale comparison under the disclosed historical greater-of term.

    Equity pot is AFTER ALL non-equity claims, transaction costs and funding needs.
    Existing share count is frozen; no future issuance, vesting or further cost is
    silently free. Cash below the protected floor is rejected: this function does
    not invent a creditor/bankruptcy recovery rule. No Put Note is also added to
    this company-sale branch. Terminated-right comparison changes rights only.
    """
    finite(total_shares,'total shares',positive=True)
    finite(protected_shares,'protected shares')
    finite(floor,'floor')
    finite(equity_pot,'equity pot')
    require(protected_shares < total_shares, 'Need unprotected shares')
    unprotected = total_shares - protected_shares
    all_common = equity_pot/total_shares
    if live_right and all_common < floor and protected_shares > 0:
        require(equity_pot >= protected_shares*floor,
                'Insufficient pot: recovery/legal allocation not modeled')
        protected_per_share = floor
        ordinary_per_share = (equity_pot-protected_shares*floor)/unprotected
    else:
        protected_per_share = ordinary_per_share = all_common
    pp = protected_shares*protected_per_share
    op = unprotected*ordinary_per_share
    return {'ordinary_per_share': ordinary_per_share,
            'protected_per_share': protected_per_share,
            'protected_total': pp, 'ordinary_total': op,
            'transfer_relative_all_common': pp-protected_shares*all_common,
            'equity_pot': equity_pot}

def simple_return(receipt: Decimal, cost: Decimal) -> Decimal:
    """Single undated nominal gain/cost; NEVER an IRR. May describe a scenario."""
    finite(receipt,'receipt')
    finite(cost,'cost',positive=True)
    return receipt/cost-ONE

def recap(face: Decimal, issue_price: Decimal, cash_fees: Decimal,
          reserve_at_close: Decimal, bridge_principal: Decimal,
          bridge_interest_other: Decimal) -> dict[str, Decimal]:
    """Conditional closing allocation; caller must establish eligible cash inputs.

    Principal returned is not investment income. Reserve remains an asset at the
    borrower. Same old bridge is retired, not left beside new debt. A negative
    residual flags an inconsistent assumed account, not an observed default.
    """
    for x,name in [(face,'face'),(cash_fees,'cash fees'),(reserve_at_close,'reserve'),
                   (bridge_principal,'bridge'),(bridge_interest_other,'other uses')]:
        finite(x,name)
    require(ZERO < issue_price <= ONE, 'Invalid note issue price')
    cash = face*issue_price
    return {'new_cash_before_fees': cash,
            'original_issue_discount': face-cash,
            'net_after_assumed_cash_fees': cash-cash_fees,
            'parent_net_after_bridge_reference':
                cash-cash_fees-reserve_at_close-bridge_principal-bridge_interest_other,
            'new_principal_less_old_principal': face-bridge_principal}

def calculate(data: dict[str, Observation]) -> dict[str, object]:
    def v(k: str, unit: str='USD', **kw: object) -> Decimal:
        return get(data,k,unit,**kw)
    p,s,price,uw = v('IPO_PRIMARY','shares'),v('IPO_SECONDARY','shares'),v('IPO_PRICE','USD_per_share'),v('IPO_UW','USD_per_share')
    o=offering(p,s,price,uw)
    funding_keys=('CW_DEBT_IN','CW_DEBT_OUT','CW_DIV_Q1','CW_OPTION_EXERCISE',
                  'CW_IPO_CASH','CW_TAX','CW_OFFER_PAID','CW_OTHER_FIN')
    other_cost = v('CW_IPO_CASH')-v('CW_IPO_EQUITY_NET')
    cw={
      'reported_financing_components': sum((v(k) for k in funding_keys),ZERO),
      'cash_end_reconstructed': v('CW_OPEN')+v('CW_OCF')+v('CW_ICF')+v('CW_FCF'),
      'cash_end_by_restriction': v('CW_UNRESTRICTED')+v('CW_RESTRICTED_CURRENT')+v('CW_RESTRICTED_LONG'),
      'operating_less_cash_ppe': v('CW_OCF')+v('CW_PPE'),
      'other_offering_cost_accrual_reconstructed': other_cost,
      'unallocated_prior_cost_reconciliation': other_cost+v('CW_OFFER_PAID')-v('CW_OFFER_UNPAID'),
      'option_gross': v('CW_OPTION_ACTUAL','shares')*price,
      'option_terms_only_net': v('CW_OPTION_ACTUAL','shares')*(price-uw),
      'option_reported_net': v('CW_OPTION_NET_ACTUAL'),
      'option_terms_minus_reported_unreconciled': v('CW_OPTION_ACTUAL','shares')*(price-uw)-v('CW_OPTION_NET_ACTUAL'),
      'preferred_dividend_cumulative_difference': -v('CW_DIV_H1')+v('CW_DIV_Q1'),
      'openai_noncash_value': v('CW_OPENAI_SHARES','shares')*price,
    }
    tender={
      'founder_groups_2023_gross': sum((v(f'{who}_2023_GROSS') for who in ('INTRATOR','VENTURO','MCBEE')),ZERO),
      'founder_groups_2024_gross': sum((v(f'{who}_2024_GROSS') for who in ('INTRATOR','VENTURO','MCBEE')),ZERO),
      'mcveety_2023_cash_after_exercise_before_other_costs_tax': v('MCV_2023_GROSS')-v('MCV_2023_EXERCISE'),
      'mcveety_ipo_gross': v('MCV_IPO_SHARES','shares')*price,
      'mcveety_ipo_after_underwriting_before_other_costs_tax': v('MCV_IPO_SHARES','shares')*(price-uw),
      'hjelm_ipo_after_underwriting_before_other_costs_tax': v('HJELM_IPO_SHARES','shares')*(price-uw),
      'agrawal_ipo_after_underwriting_before_other_costs_tax': v('AGRAWAL_IPO_SHARES','shares')*(price-uw),
      'fidelity_2023_effective_cash_basis_per_share': v('FID_T2023_COST')/v('FID_T2023_SHARES','shares'),
    }
    tender['founder_groups_two_tenders_gross']=tender['founder_groups_2023_gross']+tender['founder_groups_2024_gross']
    # Round the aggregate denominator to the precision of the balance sheet.
    puts=v('CW_PUT_SHARES','shares')
    total=v('CW_A','shares')+v('CW_B','shares')+puts.quantize(D('1E3'))
    floor=v('PUT_K','USD_per_share')
    rights: dict[str, object]={'rounded_march_share_denominator':total,
                              'eligible_put_count': puts,
                              'face_of_historical_put_at_disclosed_rounded_oip': puts*floor,
                              'vwap_termination_threshold_from_rounded_oip': floor*v('PUT_MULTIPLE','multiple')}
    cases={}
    for name,key in [('low','A_EXIT_LOW'),('reference','A_EXIT_MID'),('high','A_EXIT_HIGH')]:
        eq=total*v(key,'USD_per_share',status='research_assumption')
        live=sale_allocation(total,puts,floor,eq,live_right=True)
        gone=sale_allocation(total,puts,floor,eq,live_right=False)
        cases[name]={'live_historical_right':live,'without_right_frozen_capital':gone,
          'ipo_buyer_nominal_return_live':simple_return(live['ordinary_per_share'],price),
          'ipo_buyer_nominal_return_without':simple_return(gone['ordinary_per_share'],price),
          'fidelity_retained_2023_lot_return_live':simple_return(live['ordinary_per_share']*v('FID_T2023_SHARES','shares'),v('FID_T2023_COST')),
          'fidelity_retained_2023_lot_return_without':simple_return(gone['ordinary_per_share']*v('FID_T2023_SHARES','shares'),v('FID_T2023_COST'))}
    rights['illustrative_cases']=cases
    r=recap(v('CS_FACE'),v('CS_ISSUE_PRICE','fraction'),
       v('A_ISSUE_COST_CASH',status='research_assumption'),
       v('A_RESERVE_CLOSING',status='research_assumption'),v('CS_BRIDGE'),
       v('A_OTHER_USES',status='research_assumption'))
    r.update({
       'full_face_annual_coupon':v('CS_FACE')*v('CS_COUPON','fraction'),
       'coupon_per_issue_cash':v('CS_COUPON','fraction')/v('CS_ISSUE_PRICE','fraction'),
       'sofr_nominal_coupon_equality':v('CS_COUPON','fraction')-v('CS_BRIDGE_SPREAD','fraction'),
       'estimate_minus_recorded_cost_reference':v('CS_NET_EST')-(v('CS_FACE')*v('CS_ISSUE_PRICE','fraction')-v('CS_ISSUE_COST')),
       'group_financing_reconstructed':sum((v(k) for k in ('CS_GROUP_DEBT_IN','CS_GROUP_REPAY','CS_GROUP_FEES','CS_GROUP_TAX','CS_GROUP_OTHER')),ZERO),
       'group_cash_end_reconstructed':v('CS_OPEN')+v('CS_OCF')+v('CS_ICF')+v('CS_FCF'),
       'after_100m_additional_eligible_cash_use':r['parent_net_after_bridge_reference']-v('A_EXTRA_DRAIN')})
    g={'cash_excess_over_original_outlay':v('GECC_DISTR')-v('GECC_ORIGINAL'),
       'cumulative_cash_to_original_outlay_not_irr':v('GECC_DISTR')/v('GECC_ORIGINAL'),
       'retained_fair_value_still_exposed':v('GECC_RETAINED_FV')}
    return {'ipo_base_allocation':o,'coreweave_accounts_and_reconciliation':cw,
            'named_tender_and_ipo_outcomes':tender,'historical_right_allocation':rights,
            'core_scientific_recap_reference':r,'gecc_inherited_context':g}

def run_tests(data: dict[str, Observation], result: dict[str, object]) -> dict[str,int]:
    count=0
    def close(a: Decimal, b: Decimal, message: str, tol: Decimal=D('0.000001')) -> None:
        nonlocal count
        count+=1
        require(abs(a-b) <= tol, message)
    def yes(x: bool,message: str) -> None:
        nonlocal count
        count+=1
        require(x,message)
    def reject(fn: Callable[[],object]) -> None:
        nonlocal count
        count+=1
        try:
            fn()
        except ValueError:
            return
        raise ValueError('Invalid input unexpectedly accepted')
    o=result['ipo_base_allocation']; c=result['coreweave_accounts_and_reconciliation']
    t=result['named_tender_and_ipo_outcomes']; r=result['core_scientific_recap_reference']
    h=result['historical_right_allocation']
    for obj,key,expected in [(o,'public_cash','1500000000'),(o,'issuer_net_before_other_costs','1422619200'),
      (o,'seller_net_before_other_costs','35380800'),(o,'total_underwriting','42000000'),
      (c,'reported_financing_components','1853866000'),(c,'cash_end_reconstructed','2517816000'),
      (c,'cash_end_by_restriction','2517816000'),(c,'other_offering_cost_accrual_reconstructed','31104000'),
      (c,'unallocated_prior_cost_reconciliation','2335000'),(c,'option_terms_minus_reported_unreconciled','759800'),
      (c,'preferred_dividend_cumulative_difference','2592000'),(c,'operating_less_cash_ppe','-1346191000'),
      (t,'founder_groups_two_tenders_gross','487855191'),
      (t,'mcveety_2023_cash_after_exercise_before_other_costs_tax','1247692'),
      (t,'mcveety_ipo_after_underwriting_before_other_costs_tax','2895004.8'),
      (r,'new_cash_before_fees','3275250000'),(r,'original_issue_discount','24750000'),
      (r,'parent_net_after_bridge_reference','1888450000'),
      (r,'full_face_annual_coupon','255750000'),(r,'group_financing_reconstructed','3191955000'),
      (r,'group_cash_end_reconstructed','2551391000'),(r,'sofr_nominal_coupon_equality','0.0525'),
      (h,'rounded_march_share_denominator','465407000'),
      (h,'face_of_historical_put_at_disclosed_rounded_oip','1163594870.70')]:
        close(obj[key],D(expected),f'Frozen check {key}')
    close(o['public_cash'],o['issuer_net_before_other_costs']+o['seller_net_before_other_costs']+o['total_underwriting'],'IPO cash conservation')
    close(r['new_cash_before_fees'],r['parent_net_after_bridge_reference']+get(data,'A_ISSUE_COST_CASH','USD')+get(data,'A_RESERVE_CLOSING','USD')+get(data,'CS_BRIDGE','USD')+get(data,'A_OTHER_USES','USD'),'Recap cash conservation')
    yes(get(data,'CW_OPTION_ACTUAL','shares')<get(data,'IPO_OPTION_MAX','shares'),'Actual option not full permission')
    # Independent rational reconstruction of the central rights calculation.
    n=Fraction(465407000); p=Fraction(29874066); k=Fraction(3895,100)
    pot=n*20
    per=(pot-p*k)/(n-p)
    frac_to_dec=lambda z:D(z.numerator)/D(z.denominator)
    live=h['illustrative_cases']['low']['live_historical_right']
    close(live['ordinary_per_share'],frac_to_dec(per),'Independent Fraction per-share allocation')
    close(live['transfer_relative_all_common'],frac_to_dec(p*(k-20)),'Independent Fraction transferred amount')
    independent=2
    # Deterministic random cases test conservation and monotonicity, not probabilities.
    rng=random.Random(14036)
    synthetic=400
    for _ in range(synthetic):
        n=D(rng.randint(100,100000)); p=D(rng.randint(0,int(n)-1))
        k=D(rng.randint(1,100)); e=p*k+D(rng.randint(0,100000))*n
        a=sale_allocation(n,p,k,e,live_right=True)
        b=sale_allocation(n,p,k,e,live_right=False)
        close(a['ordinary_total']+a['protected_total'],e,'Synthetic live conservation')
        close(b['ordinary_total']+b['protected_total'],e,'Synthetic common conservation')
        yes(a['ordinary_per_share']<=b['ordinary_per_share'],'Floor cannot help ordinary at fixed pot')
        yes(a['protected_per_share']>=b['protected_per_share'],'Protected allocation direction')
        larger=sale_allocation(n,p,k,e+n,live_right=True)
        yes(larger['ordinary_per_share']>=a['ordinary_per_share'],'More distributable value must not lower ordinary receipt')
    # Domain rejection guards against silently invented legal or financial results.
    reject(lambda:sale_allocation(D(10),D(10),D(2),D(30),live_right=True))
    reject(lambda:sale_allocation(D(10),D(5),D(20),D(99),live_right=True))
    reject(lambda:sale_allocation(D(10),D(-1),D(2),D(20),live_right=True))
    reject(lambda:simple_return(D(1),ZERO))
    reject(lambda:offering(D(1),D(1),D(2),D(2)))
    reject(lambda:recap(D(100),D('1.1'),ZERO,ZERO,ZERO,ZERO))
    reject(lambda:recap(D(100),ONE,D(-1),ZERO,ZERO,ZERO))
    reject(lambda:get(data,'MCV_2024_GROSS','USD'))
    reject(lambda:get(data,'SERIES_C_OIP_OTHER','USD_per_share'))
    reject(lambda:get(data,'CW_PUT_SHARES','USD'))
    reject(lambda:get(data,'A_EXIT_LOW','USD_per_share',status='reported_actual'))
    reject(lambda:get(data,'NONEXISTENT','USD'))
    return {'checks_passed':count,'synthetic_cases':synthetic,
            'independent_fraction_reconstructions':independent,'domain_rejections':12}

def default_data_path() -> Path:
    here=Path(__file__).resolve()
    # Prefer the exact paired filename, rather than an unrelated data.csv.
    paired=here.with_name(here.name.removesuffix('calculations.py')+'data.csv')
    if paired.is_file():
        return paired
    normal=here.with_name('data.csv')
    require(normal.is_file(),'No paired data file; use --data PATH')
    return normal

def json_value(obj: object) -> object:
    if isinstance(obj,D):
        return format(obj,'f')
    raise TypeError(type(obj).__name__)

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data',type=Path,help='Source-linked ledger; defaults to paired sibling')
    ap.add_argument('--no-tests',action='store_true',help='Skip implementation checks')
    args=ap.parse_args()
    try:
        data=load_inputs(args.data if args.data else default_data_path())
        result=calculate(data)
        tests={} if args.no_tests else run_tests(data,result)
    except (OSError,ValueError,InvalidOperation) as exc:
        ap.exit(2,f'Error: {exc}\n')
    print(json.dumps({'input_records':len(data),'results':result,'checks':tests},
                     indent=2,sort_keys=True,default=json_value))

if __name__=='__main__':
    main()
