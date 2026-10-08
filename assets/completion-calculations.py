#!/usr/bin/env python3
"""Completion-to-cash constraints, not an October balance or compliance opinion.

Python 3.10+. Standard-library calculations/tests; optional SVG requires matplotlib.
Run beside completion-data.csv, or use --data to select the ledger:
  python completion-calculations.py [--data completion-data.csv] [--figure completion-cash.svg]

Core Scientific's June accounts are actuals. Forward results condition on no note
redemption/amendment, no principal due in November 2026, and explicit intervening
net eligible cash. The reserve calculation follows the printed indenture formula;
missing certificates, other qualifying collateral and account movements are NOT
silently imputed. Group uses are separate from the project-account test.
"""
from __future__ import annotations
import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Iterable

# A delivery-prefixed script can locate its matching ledger without renaming.
DATA_NAME = Path(__file__).name.replace('completion-calculations.py', 'completion-data.csv')
STATUSES = {'reported_actual','reported_inherited','issuer_estimate','contractual',
            'issuer_illustration','issuer_reported_status','registered_estimate',
            'research_assumption'}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def finite(value: float, name: str, *, nonnegative: bool = False) -> None:
    require(not isinstance(value, bool) and math.isfinite(value), f'{name}: finite number required')
    require(not nonnegative or value >= 0, f'{name}: negative value')


def close(a: float, b: float, tolerance: float = 1e-8) -> None:
    require(math.isclose(a,b,rel_tol=1e-10,abs_tol=tolerance), f'Identity failed: {a} != {b}')


@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    entity: str
    period: str
    source: str


def load_inputs(path: Path) -> dict[str, Input]:
    fields = {'id','entity','metric','value','unit','status','period','source_id',
              'source_url','locator','notes'}
    out: dict[str,Input] = {}
    with path.open(encoding='utf-8',newline='') as f:
        reader = csv.DictReader(f)
        require(fields.issubset(reader.fieldnames or []),'Missing ledger columns')
        for row in reader:
            require(None not in row,'Excess columns in ledger row')
            require(all(isinstance(row[k],str) and row[k].strip() for k in fields),'Empty ledger field')
            key = row['id']; require(key not in out, f'Duplicate ID: {key}')
            x=float(row['value']); finite(x,key)
            require(row['status'] in STATUSES,f'Invalid status: {key}')
            require(row['source_url'].startswith(('https://','report.md#')),f'Invalid source: {key}')
            out[key]=Input(x,row['unit'],row['status'],row['entity'],row['period'],row['source_id'])
    require(bool(out),'Empty ledger')
    return out


def val(d: Mapping[str,Input], key: str, unit: str = 'USD_million',
        status: str | None = None) -> float:
    r=d[key]
    require(r.unit==unit, f'Unit mismatch: {key}: {r.unit} != {unit}')
    require(status is None or r.status==status, f'Status mismatch: {key}')
    return r.value


def actual_account(d: Mapping[str,Input]) -> dict[str,float]:
    """No addition of post-June events to a purported October stock."""
    close(val(d,'CS_START')+val(d,'CS_OCF')+val(d,'CS_ICF')+val(d,'CS_FCF'),val(d,'CS_END'))
    restricted=val(d,'CS_RESTRICTED_CURRENT')+val(d,'CS_RESTRICTED_NONCURRENT')
    close(val(d,'CS_UNRESTRICTED')+restricted,val(d,'CS_END'))
    close(val(d,'CS_DEBT_GROSS')-val(d,'CS_BRIDGE_REPAY')-val(d,'CS_ISSUANCE_COSTS')
          -val(d,'CS_RSU_TAX')+val(d,'CS_FIN_OTHER'),val(d,'CS_FCF'))
    close(val(d,'CS_INTEREST_INCURRED')-val(d,'CS_INTEREST_CAP'),val(d,'CS_INTEREST_EXP'))
    out={
      'restricted_total':restricted,
      'restricted_unallocated':restricted-val(d,'CS_RESERVE')-val(d,'CS_POLARIS_ESCROW'),
      'nonfinancing_flow':val(d,'CS_OCF')+val(d,'CS_ICF'),
      'customer_ap_implied':val(d,'CS_CUSTOMER_REC')-val(d,'CS_CUSTOMER_ACCRUAL'),
      'customer_rounded_residual':val(d,'CS_CUSTOMER_ACCRUAL')+val(d,'CS_CUSTOMER_AP_ROUND')-val(d,'CS_CUSTOMER_REC'),
      'receivable_change':val(d,'CS_CUSTOMER_REC')-val(d,'CS_CUSTOMER_REC_PRIOR'),
      'net_commitment_reference':val(d,'CS_COMMIT')-val(d,'CS_COMMIT_CUSTOMER'),
      'Polaris_unescrowed':val(d,'CS_POLARIS_PRICE')-val(d,'CS_POLARIS_ESCROW'),
      'detailed_IT_MW':sum(val(d,'SITE_'+s,'MW_IT') for s in ['AUSTIN','DENTON','DALTON1','DALTON4','MARBLE','MUSKOGEE']),
      'note_cash_before_fees':val(d,'N_FACE')*val(d,'N_ISSUE_PRICE','fraction'),
      'IREN_funded':val(d,'IR_DDTL_FUNDED')+val(d,'IR_NOTES_FUNDED'),
      'IREN_conditional_unfunded':val(d,'IR_DDTL_LIMIT')+val(d,'IR_NOTES_LIMIT')-val(d,'IR_DDTL_FUNDED')-val(d,'IR_NOTES_FUNDED'),
      'IREN_cash_including_restrictions':val(d,'IR_CASH')+val(d,'IR_RESTRICT_CUR')+val(d,'IR_RESTRICT_NC'),
      'IREN_funded_note_annual_coupon':val(d,'IR_NOTES_FUNDED')*val(d,'IR_NOTE_COUPON','fraction'),
    }
    # The source narrative rounds AP to one decimal million.
    require(abs(out['customer_rounded_residual']) < .05,'Construction matching exceeds AP rounding precision')
    return out


def group_room(d: Mapping[str,Input], incremental_ppe: float=0.,
               incremental_acquisition: float=0., conditional_extra: float=0.,
               net_operating_and_other: float=0.) -> float:
    """A limited group resource bound, NOT project cash or a full funding plan.

    Incremental parameters include only amounts not already inside the disclosed
    commitment bucket. No unknown overlap is resolved by adding the same bill twice.
    The signed final parameter includes ALL other net operating/financing cash uses.
    """
    for n,x in [('incremental PPE',incremental_ppe),('acquisition',incremental_acquisition),('extra',conditional_extra)]:
        finite(x,n,nonnegative=True)
    finite(net_operating_and_other,'other net cash')
    require(incremental_ppe <= val(d,'CS_PPE_PAYABLE'),'PPE parameter exceeds identified balance')
    require(incremental_acquisition <= val(d,'CS_POLARIS_PRICE')-val(d,'CS_POLARIS_ESCROW'),'Acquisition parameter exceeds unescrowed base')
    require(conditional_extra <= val(d,'CS_POLARIS_EXTRA'),'Extra parameter exceeds disclosed condition')
    return val(d,'CS_UNRESTRICTED')-(val(d,'CS_COMMIT')-val(d,'CS_COMMIT_CUSTOMER')) \
        -incremental_ppe-incremental_acquisition-conditional_extra+net_operating_and_other


def cash_path(events: Iterable[tuple[int,float]], opening: float=0.) -> tuple[float,float]:
    """Return terminal balance and minimum external bridge. Equal-day flows net.

    Day indices are order labels for the illustrative matching test, not observed
    invoice dates. Intraday ordering on an identical day is not represented.
    """
    finite(opening,'opening',nonnegative=True)
    by_day: dict[int,float]={}
    for day,amount in events:
        require(type(day) is int and day>=0,'Invalid event day')
        finite(amount,'event amount')
        by_day[day]=by_day.get(day,0.)+amount
    balance=opening; low=opening
    for day in sorted(by_day):
        balance+=by_day[day]; low=min(low,balance)
    return balance,max(0.,-low)


def matching_bridge(d: Mapping[str,Input], early_vendor_share: float) -> tuple[float,float]:
    finite(early_vendor_share,'early-vendor share')
    require(0<=early_vendor_share<=1,'Share outside [0,1]')
    total=val(d,'CS_CUSTOMER_REC')
    return cash_path([(0,-early_vendor_share*total),(1,total),(2,-(1-early_vendor_share)*total)])


def days_30_360(start: date, end: date) -> int:
    """30/360 for the chosen dates; no February/end-month convention is needed."""
    require(end>start,'Nonpositive interest interval')
    require(start.day<30 and end.day<30,'This helper excludes end-month ambiguity')
    return (end.year-start.year)*360+(end.month-start.month)*30+end.day-start.day


def reserve_terms(d: Mapping[str,Input], remaining_earnings: float=0.) -> dict[str,float]:
    finite(remaining_earnings,'future reserve earnings',nonnegative=True)
    face=val(d,'N_FACE'); coupon=val(d,'N_COUPON','fraction','contractual')
    first_days=days_30_360(date(2026,5,6),date(2026,11,15))
    first_coupon=face*coupon*first_days/val(d,'N_CALENDAR_DAYS','days')
    regular_coupon=face*coupon/2
    first_principal=face*val(d,'N_ANNUAL_AMORT','fraction')/2
    floor=regular_coupon+first_principal
    literal=max(floor,val(d,'N_RESERVE_BASE')-first_coupon+floor-remaining_earnings)
    return dict(first_days=first_days,first_coupon=first_coupon,regular_coupon=regular_coupon,
                first_installment=first_principal,construction_minimum=floor,
                construction_literal=literal,completed_credits_remain=regular_coupon,
                earnings_at_floor=val(d,'N_RESERVE_BASE')-first_coupon)


def required_net_resources(opening_reserve: float, payment: float, closing_reserve: float,
                           net_eligible_cash: float=0., other_eligible_support: float=0.) -> float:
    """Signed requirement. Negative is modeled room, NOT distribution permission.

    A reserve is a closing stock. It is not charged again as an expense. Net cash
    includes costs/actual earnings during the interval; future reserve earnings
    used in the legal formula are not also a current inflow.
    """
    for name,x in [('opening',opening_reserve),('payment',payment),('closing reserve',closing_reserve),('other support',other_eligible_support)]:
        finite(x,name,nonnegative=True)
    finite(net_eligible_cash,'net eligible cash')
    return payment+closing_reserve-opening_reserve-net_eligible_cash-other_eligible_support


def transition_cases(d: Mapping[str,Input]) -> dict[str,float]:
    t=reserve_terms(d,val(d,'A_REMAINING_EARNINGS'))
    return {k:required_net_resources(val(d,'CS_RESERVE'),t['first_coupon'],t[k],val(d,'A_INTERVENING_NET'))
            for k in ['completed_credits_remain','construction_minimum','construction_literal']}


def eligible_funding_route(d: Mapping[str,Input], delivered_fraction: float,
                          days_before_window_end: int, accepted: bool,
                          equity_purchase_complete: bool, other_conditions_met: bool) -> bool:
    """Two explicit §3.3(o) routes only, not a full legal eligibility engine.

    Supplied day count must already reflect permitted deadline extensions. Other
    conditions are an external supplied fact, not determined by this function.
    """
    finite(delivered_fraction,'delivery fraction')
    require(0<=delivered_fraction<=1,'Delivery fraction outside [0,1]')
    require(type(days_before_window_end) is int,'Integer deadline distance required')
    require(all(type(v) is bool for v in [accepted,equity_purchase_complete,other_conditions_met]),'Boolean states required')
    timely=delivered_fraction>=val(d,'IR_DELIVERY_FRACTION','fraction') and days_before_window_end>=val(d,'IR_DELIVERY_LEAD','days')
    reimbursable=accepted and equity_purchase_complete
    return other_conditions_met and (timely or reimbursable)


def parent_liquidity_floor(d: Mapping[str,Input], accepted_tranches: int) -> float:
    """Sequential acceptance states after first funding and before commitment termination.

    Earlier contract-termination alternatives are outside this scoped state test.
    This returns a qualifying-liquid-assets floor, not a segregated cash balance.
    """
    require(type(accepted_tranches) is int and 0<=accepted_tranches<=4,'Invalid acceptance state')
    return val(d,f'IR_PARENT_LIQ_{accepted_tranches}')


def spare_cure_reserve(d: Mapping[str,Input], extension_days: int,
                       no_customer_credits: bool, eligible_source: bool) -> float:
    require(type(extension_days) is int and 0<=extension_days<=val(d,'IR_SPARE_MAX','days'),'Cure outside contract maximum')
    require(type(no_customer_credits) is bool and type(eligible_source) is bool,'Boolean conditions required')
    require(extension_days==0 or (no_customer_credits and eligible_source),'Cure conditions not met')
    return math.ceil(extension_days/30)*val(d,'IR_SPARE_CURE')


def delay_credit(d: Mapping[str,Input], adjusted_delay_days: int) -> float:
    require(type(adjusted_delay_days) is int and 0<=adjusted_delay_days<=val(d,'DELAY_TERM','days'),'Delay outside modeled nonterminated window')
    a=int(val(d,'DELAY_FREE','days')); b=int(val(d,'DELAY_STEP','days'))
    return max(0,min(adjusted_delay_days,b)-a)*val(d,'DELAY_RATE1','USD_million_per_day') \
        +max(0,adjusted_delay_days-b)*val(d,'DELAY_RATE2','USD_million_per_day')


def results(d: Mapping[str,Input]) -> dict[str,float]:
    out=actual_account(d)
    out.update({'reserve_'+k:v for k,v in reserve_terms(d).items()})
    out.update({'net_required_'+k:v for k,v in transition_cases(d).items()})
    out['group_room_before_other_uses']=group_room(d)
    out['group_room_with_incremental_acquisition']=group_room(d,incremental_acquisition=out['Polaris_unescrowed'])
    out['group_room_with_incremental_ppe']=group_room(d,val(d,'CS_PPE_PAYABLE'),out['Polaris_unescrowed'])
    out['group_room_including_conditional_extra']=group_room(d,val(d,'CS_PPE_PAYABLE'),out['Polaris_unescrowed'],val(d,'CS_POLARIS_EXTRA'))
    for share in (0,.25,.5,1): out[f'bridge_early_share_{share}']=matching_bridge(d,share)[1]
    out['delay_credit_90_days']=delay_credit(d,90)
    out['IREN_spare_cure_60_days']=spare_cure_reserve(d,60,True,True)
    out['annual_coupon_difference_April_May']=val(d,'N_FACE')*(val(d,'N_ASSUMED_COUPON_APRIL','fraction','issuer_illustration')-val(d,'N_COUPON','fraction','contractual'))
    return out


def run_tests(d: Mapping[str,Input]) -> None:
    r=results(d)
    close(r['restricted_total'],781.656);close(r['restricted_unallocated'],316.856)
    close(r['customer_ap_implied'],81.575);close(r['receivable_change'],46.6)
    close(r['reserve_first_coupon'],134.26875);close(r['reserve_regular_coupon'],127.875)
    close(r['reserve_first_installment'],189.75)
    close(r['net_required_completed_credits_remain'],-82.65625)
    close(r['net_required_construction_minimum'],107.09375)
    close(r['net_required_construction_literal'],315.825)
    close(r['group_room_with_incremental_ppe'],605.215)
    close(r['IREN_conditional_unfunded'],2707)
    close(r['annual_coupon_difference_April_May'],16.5)
    close(delay_credit(d,30),0); close(delay_credit(d,60),.6);close(delay_credit(d,90),1.5)
    close(spare_cure_reserve(d,60,True,True),50)
    for i in range(101):
        share=i/100
        terminal,bridge=matching_bridge(d,share)
        close(terminal,0);close(bridge,share*val(d,'CS_CUSTOMER_REC'))
        t=reserve_terms(d,float(i)*3)
        require(t['construction_literal']>=t['construction_minimum'],'Reserve below minimum')
        need=required_net_resources(val(d,'CS_RESERVE'),t['first_coupon'],t['construction_literal'])
        close(required_net_resources(val(d,'CS_RESERVE'),t['first_coupon'],t['construction_literal'],i),need-i)
    require(not eligible_funding_route(d,.96,45,False,False,True),'Below-threshold draw allowed')
    require(eligible_funding_route(d,.97,45,False,False,True),'Valid pre-acceptance route rejected')
    require(not eligible_funding_route(d,.97,44,False,False,True),'Late delivery route allowed')
    require(not eligible_funding_route(d,.97,45,False,False,False),'Other conditions ignored')
    require(eligible_funding_route(d,1,0,True,True,True),'Equity-first accepted route rejected')
    require([parent_liquidity_floor(d,i) for i in range(5)]==[200,150,100,50,0],'Parent milestone sequence')
    for f in [lambda:matching_bridge(d,1.1),lambda:spare_cure_reserve(d,91,True,True),
              lambda:spare_cure_reserve(d,30,False,True),lambda:parent_liquidity_floor(d,True),
              lambda:group_room(d,incremental_ppe=128),lambda:delay_credit(d,121),
              lambda:required_net_resources(-1,1,1),lambda:eligible_funding_route(d,.97,45,0,False,True)]:
        try:f()
        except ValueError:pass
        else:raise ValueError('Invalid input was accepted')


def render_figure(d: Mapping[str,Input], destination: Path) -> None:
    import matplotlib.pyplot as plt
    r=transition_cases(d)
    vals=list(r.values())
    fig,ax=plt.subplots(figsize=(11.8,6.8))
    labels=['Completed; credits remain\nNext-period interest reserved',
            'Still constructing\nMinimum branch only — lower bound',
            'Still constructing\nFull printed formula; E = 0']
    bars=ax.barh([2,1,0],vals)
    ax.axvline(0,linewidth=1)
    ax.set_yticks([2,1,0],labels,fontsize=10)
    ax.set_xlim(-125,390)
    ax.set_xlabel('Additional net resources required beyond the June reserve (USD millions)',fontsize=10)
    for bar,x in zip(bars,vals):
        ax.annotate(f'{x:+.1f}',(x,bar.get_y()+bar.get_height()/2),
                    xytext=(6 if x>=0 else -6,0),textcoords='offset points',
                    ha='left' if x>=0 else 'right',va='center',fontsize=12)
    ax.set_title('Completion changes the cash that must remain protected',loc='left',fontsize=15,pad=30)
    fig.text(.03,.08,'Conditional first-payment test: May 6–November 15, 2026 coupon; June reserve of $344.8m.\n'
             'Zero intervening net eligible cash is a reference for solving the requirement, not a receipts forecast.\n'
             'E is estimated remaining reserve earnings. The middle row is not the complete legal formula.\n'
             'Negative means modeled room, not a dividend permission; positive is not an observed shortfall or default.\n'
             'Sources: executed indenture §1.01 / Art.14; June note 7; completion chapter §5; companion data and calculations.',fontsize=9)
    fig.subplots_adjust(left=.34,right=.96,bottom=.30,top=.80)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Is AI a Bubble? Completion and cash before stabilization'})
    plt.close(fig)


def main() -> None:
    folder=Path(__file__).resolve().parent
    default=folder/'completion-data.csv'
    if not default.exists():default=folder/DATA_NAME
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=default)
    p.add_argument('--figure',type=Path)
    a=p.parse_args(); d=load_inputs(a.data);run_tests(d)
    for key,value in results(d).items():print(f'{key}: {value:.9f}')
    print(f'All built-in checks passed; {len(d)} input records. Outputs are conditional where identified.')
    if a.figure:render_figure(d,a.figure)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError) as e:raise SystemExit(f'Calculation failed: {e}') from e
