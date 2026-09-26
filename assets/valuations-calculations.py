#!/usr/bin/env python3
"""Ownership-price requirements, not fair values or investment recommendations.

Python 3.10+, standard library. Run beside valuations-data.csv:
    python valuations-calculations.py [--data PATH] [--json]
Optional --figure PATH requires matplotlib and redraws the Microsoft sensitivity.
Delivery-prefixed sibling filenames also work. No network access is used.

All money is USD billions unless explicitly labeled. The IREN bridge combines a
September 24 price, August 14 shares and June statements; it is not a synchronized
enterprise value. Childress values remaining cash, not sunk original expenditure.
Renewal is optional and pays for replacement. The other-portfolio value is a
requirement, not an appraisal. Microsoft solves for REVENUE growth, charges new
finance-lease assets as investment and existing lease liabilities in the bridge,
and does not also charge lease principal. Compensation is charged once. Frontier
funding participation and nonparticipation are alternatives, never two charges
for one raise. Every unmeasured operating parameter remains a scenario.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Any

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str

def finite(x: float, name: str, minimum: float | None = None,
           maximum: float | None = None) -> float:
    if not math.isfinite(x) or (minimum is not None and x < minimum) or (maximum is not None and x > maximum):
        raise ValueError(f'Invalid {name}: {x!r}')
    return x

def integer(x: int, name: str, minimum: int = 0) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or x < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return x

def load_inputs(path: Path) -> dict[str, Input]:
    result: dict[str, Input] = {}
    with path.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fields = {'id','value','unit','evidence_status','source_id','source_url',
                  'observation_period','source_location','retrieved','notes'}
        if not fields.issubset(reader.fieldnames or []):
            raise ValueError('Missing required CSV columns')
        for row in reader:
            key = (row['id'] or '').strip()
            if not key or key in result:
                raise ValueError(f'Blank or duplicate input: {key!r}')
            if None in row or any(not row.get(k) for k in fields - {'notes'}):
                raise ValueError(f'Missing or malformed input fields: {key}')
            x = finite(float(row['value']), key)
            if row['evidence_status'] != 'research_assumption' and not row['source_url'].startswith('https://'):
                raise ValueError(f'Observed input lacks source URL: {key}')
            result[key] = Input(x, row['unit'], row['evidence_status'])
    if not result:
        raise ValueError('Empty input file')
    return result

def value(d: dict[str, Input], key: str, unit: str | None = None) -> float:
    x = d[key]
    if unit is not None and x.unit != unit:
        raise ValueError(f'{key}: expected {unit}; got {x.unit}')
    return x.value

def discount(rate: float, years: float) -> float:
    finite(rate, 'discount rate'); finite(years, 'years', 0)
    if rate <= -1:
        raise ValueError('Rate must exceed -1')
    return (1 + rate) ** (-years)

def annuity(rate: float, years: int, delay: int = 0, growth: float = 0) -> float:
    integer(years,'annuity years',1); integer(delay,'annuity delay')
    finite(growth,'growth')
    if growth <= -1:
        raise ValueError('Growth must exceed -1')
    return sum((1 + growth) ** (t-1) * discount(rate,t+delay) for t in range(1,years+1))

def root_increasing(f: Callable[[float], float], target: float,
                    lo: float = -.2, hi: float = .8) -> float:
    finite(target,'root target')
    if not f(lo) <= target <= f(hi):
        raise ValueError('Root not bracketed')
    for _ in range(150):
        mid=(lo+hi)/2
        if f(mid)<target: lo=mid
        else: hi=mid
    return (lo+hi)/2

def iren_claim(d: dict[str, Input]) -> dict[str,float]:
    equity=value(d,'I_PRICE','USD_per_share')*value(d,'I_SHARES','million_shares')/1000
    debt=sum(value(d,k,'USD_billion') for k in ('I_CONVERT_FACE','I_DDTL_DRAW','I_NOTE_DRAW'))
    lease=value(d,'I_LEASE_DEBT','USD_billion'); cash=value(d,'I_CASH','USD_billion')
    return dict(paired_common_value=equity,debt_face=debt,finance_lease_claim=lease,
                unrestricted_cash=cash,debt_face_operating_requirement=equity+debt+lease-cash)

@dataclass(frozen=True)
class Childress:
    remaining_capital: float = 4.0
    received_advance: float = 1.013120
    cash_cost_share: float = .20
    delay_unstarted_months: int = 3
    elapsed_first_phase_months: int = 1
    rate: float = .10

def childress_forward(d: dict[str,Input], s: Childress) -> dict[str,float]:
    """Four equally weighted phases; retain advance credits and full service terms.

    Remaining capital is a net economic burden, not the unadjusted original budget.
    Received advance is a dated SPV allocation proxy, not a September bank record.
    All costs and service dates are assumptions, not observed monthly invoices.
    """
    fees=value(d,'P_FEE','USD_billion'); n=int(value(d,'P_MONTHS','months'))
    advance=fees*value(d,'P_ADVANCE_SHARE','fraction')
    finite(s.remaining_capital,'remaining capital',0)
    finite(s.received_advance,'received advance',0,advance)
    finite(s.cash_cost_share,'cash cost share',0)
    finite(s.rate,'rate',0)
    integer(s.delay_unstarted_months,'unstarted delay')
    integer(s.elapsed_first_phase_months,'elapsed months')
    if s.cash_cost_share>=1 or s.elapsed_first_phase_months>=n or s.rate<=0:
        raise ValueError('Invalid Childress assumptions')
    credit_start=int(value(d,'P_CREDIT_START','month'))
    if not 1<=credit_start<=n: raise ValueError('Invalid credit term')
    phase_fee=fees/4; advance_phase=advance/4; already=s.received_advance/4
    monthly_fee=phase_fee/n; monthly_credit=advance_phase/(n-credit_start+1)
    offsets=[-s.elapsed_first_phase_months]+[s.delay_unstarted_months]*3
    future_gross=past_gross=future_credits=past_invoice=future_collections=0.
    pv_collection=pv_cost=pv_advance=0.
    for off in offsets:
        pv_advance+=(advance_phase-already)*discount(s.rate,max(off,0)/12)
        for m in range(1,n+1):
            t=off+m; credit=monthly_credit if m>=credit_start else 0.; receipt=monthly_fee-credit
            if t<=0:
                past_gross+=monthly_fee; past_invoice+=receipt
            else:
                future_gross+=monthly_fee; future_credits+=credit; future_collections+=receipt
                pv_collection+=receipt*discount(s.rate,t/12)
                pv_cost+=monthly_fee*s.cash_cost_share*discount(s.rate,t/12)
    future_advance=advance-s.received_advance
    total=s.received_advance+past_invoice+future_advance+future_collections
    close(total,fees,'advance/credit conservation')
    return dict(project_forward_value=pv_collection+pv_advance-pv_cost-s.remaining_capital,
                pv_invoices=pv_collection,pv_unreceived_advance=pv_advance,pv_cash_costs=pv_cost,
                remaining_capital=s.remaining_capital,already_received_advance=s.received_advance,
                past_gross_service=past_gross,future_gross_service=future_gross,
                future_nominal_invoice_cash=future_collections,future_nominal_advance=future_advance,
                total_nominal_collections=total,future_nominal_credits=future_credits)

def childress_renewal(d: dict[str,Input], s: Childress, price_per_mw: float,
                      utilization: float, refresh: float=4.3, variable_share: float=.25,
                      annual_fixed: float=.25, years: int=5) -> dict[str,float]:
    """Optional finite replacement cycle: no terminal sale and no forced loss.

    Price is USD millions per fully paid IT MW-year. Costs include the assumed
    project-level cash-tax/maintenance allowance; remaining corporate costs stay
    in other-portfolio value. A declined negative extension has zero exercise
    value; this does not price a real option or value the retained facility.
    """
    finite(utilization,'utilization',0,1); finite(price_per_mw,'renewal price',0)
    finite(refresh,'refresh',0); finite(variable_share,'variable share',0)
    finite(annual_fixed,'fixed costs',0); integer(years,'renewal years',1)
    if variable_share>=1: raise ValueError('Variable cost share must be below one')
    revenue=value(d,'P_MW','MW')*price_per_mw*utilization/1000
    cash=revenue*(1-variable_share)-annual_fixed
    extension=-refresh+cash*annuity(s.rate,years)
    ends=[60-s.elapsed_first_phase_months]+[60+s.delay_unstarted_months]*3
    pv=sum(extension/4*discount(s.rate,t/12) for t in ends)
    return dict(annual_revenue=revenue,annual_net_cash=cash,incremental_value_at_renewal=extension,
                incremental_value_today=pv,voluntary_exercise_value=max(0,pv))

def other_cash_requirement(nav: float, remaining_build_pv: float, rate: float=.1,
                           operating_years: int=15, delay: int=2, net_margin: float=.4,
                           other_capacity_mw: float=600, price_million_per_mw: float=20) -> dict[str,float]:
    finite(nav,'other NAV',0); finite(remaining_build_pv,'other build',0)
    finite(net_margin,'net margin',0,1); finite(other_capacity_mw,'capacity',0)
    finite(price_million_per_mw,'price',0)
    if not net_margin or not other_capacity_mw or not price_million_per_mw:
        raise ValueError('Margin, capacity and price must be positive')
    cash=(nav+remaining_build_pv)/annuity(rate,operating_years,delay)
    revenue=cash/net_margin; u=revenue/(other_capacity_mw*price_million_per_mw/1000)
    return dict(annual_net_cash=cash,annual_revenue=revenue,required_paid_utilization=u,
                feasible_at_stated_capacity=float(u<=1))

def conversion_sensitivity(d: dict[str,Input]) -> dict[str,float]:
    shares=face=0.
    for y in ('2029','2030'):
        f=value(d,f'I_{y}_FACE'); strike=value(d,f'I_{y}_STRIKE')
        shares+=f*1000/strike; face+=f
    p=value(d,'I_PRICE'); n=value(d,'I_SHARES')
    offset=sum(value(d,f'I_{y}_FACE')/value(d,f'I_{y}_STRIKE')*
               max(0,min(p,value(d,f'I_{y}_CAP'))-value(d,f'I_{y}_STRIKE')) for y in ('2029','2030'))
    return dict(gross_conversion_shares_million=shares,debt_face_removed=face,
                additional_claim_before_hedge=p*shares/1000-face,
                hypothetical_remaining_notional_capped_offset=offset,
                vested_ceo_award_ownership_fraction=n/(n+value(d,'I_CEO_RSU')),
                nvidia_rights_intrinsic_only=max(0,p-value(d,'I_NV_STRIKE'))*value(d,'I_NV_RIGHTS')/1000)

def dilution(shares_million: float, new_money: float, issue_price: float) -> dict[str,float]:
    for name,x in [('shares',shares_million),('money',new_money),('issue price',issue_price)]:
        finite(x,name,0)
        if not x: raise ValueError(f'{name} must be positive')
    added=new_money*1000/issue_price
    return dict(new_shares_million=added,existing_fraction=shares_million/(shares_million+added),new_cash=new_money)

def microsoft_bridge(d: dict[str,Input], debt_basis: str='FV') -> dict[str,float]:
    rev=value(d,'M_REV','USD_billion')
    equity=value(d,'M_PRICE','USD_per_share')*value(d,'M_SHARES','million_shares')/1000
    adjustment=(value(d,'M_INTEREST_EXP')-value(d,'M_INTEREST_INC'))*(1-value(d,'S_TAX'))
    precap=value(d,'M_OCF')-value(d,'M_SBC')+adjustment
    investment=value(d,'M_CASH_PPE')+value(d,'M_NEW_FL')
    prior=value(d,f'M_DEBT_{debt_basis}')+value(d,'M_FL_DEBT')-value(d,'M_CASH')
    return dict(paired_common_value=equity,net_financial_claims=prior,pre_reinvestment_proxy=precap,
                initial_pre_reinvestment_share=precap/rev,economic_reinvestment=investment,
                initial_reinvestment_share=investment/rev,residual_economic_cash_proxy=precap-investment,
                operating_value_requirement_before_holdings=equity+prior)

def microsoft_value(d: dict[str,Input], revenue_growth: float, rate: float=.1,
                    operating_share: float=.49, terminal_reinvestment: float=.25,
                    terminal_growth: float=.03, finite_years: int|None=None) -> dict[str,Any]:
    for name,x in [('revenue growth',revenue_growth),('rate',rate),('operating share',operating_share),
                   ('investment share',terminal_reinvestment),('terminal growth',terminal_growth)]: finite(x,name)
    if rate<=terminal_growth or revenue_growth<=-1 or not 0<=terminal_reinvestment<operating_share<=1:
        raise ValueError('Invalid Microsoft cash assumptions')
    b=microsoft_bridge(d); rev0=value(d,'M_REV'); initial=b['initial_reinvestment_share']
    hold=int(value(d,'S_HOLD')); fade=int(value(d,'S_FADE')); horizon=int(value(d,'S_EXPLICIT'))
    if finite_years is not None: integer(finite_years,'finite years',horizon)
    if fade<=hold: raise ValueError('Invalid investment fade')
    end=horizon if finite_years is None else finite_years
    explicit=cf_last=rev_last=0.; path=[]
    for t in range(1,end+1):
        rev=rev0*(1+revenue_growth)**min(t,horizon)*(1+terminal_growth)**max(0,t-horizon)
        weight=min(1,max(0,(t-hold)/(fade-hold)))
        cap=initial+weight*(terminal_reinvestment-initial)
        cash=rev*(operating_share-cap)
        if t==1: cash-=value(d,'M_OAI_COMMIT')
        explicit+=cash*discount(rate,t)
        if t==horizon: cf_last=rev*(operating_share-terminal_reinvestment); rev_last=rev
        path.append(dict(year=t,revenue=rev,investment=rev*cap,preinvestment_cash=rev*operating_share,cash=cash))
    tail=0. if finite_years is not None else cf_last*(1+terminal_growth)/(rate-terminal_growth)*discount(rate,horizon)
    return dict(operating_value=explicit+tail,explicit_pv=explicit,terminal_pv=tail,
                terminal_share=tail/(explicit+tail),year10_revenue=rev_last,year10_cash=cf_last,path=path)

def microsoft_required_growth(d: dict[str,Input], rate: float=.1, operating_share: float=.49,
                               cap: float=.25, holding_credit: float=0,
                               finite_years: int|None=None) -> dict[str,float]:
    finite(holding_credit,'holding credit',0)
    target=microsoft_bridge(d)['operating_value_requirement_before_holdings']-holding_credit
    if target<=0: raise ValueError('Invalid target')
    f=lambda g: microsoft_value(d,g,rate,operating_share,cap,finite_years=finite_years)['operating_value']
    g=root_increasing(f,target)
    m=microsoft_value(d,g,rate,operating_share,cap,finite_years=finite_years)
    return dict(required_revenue_growth=g,target_operating_value=target,
                year10_revenue=m['year10_revenue'],year10_cash=m['year10_cash'],terminal_share=m['terminal_share'])

def frontier_requirement(price_value: float, new_funding: float=0, rate: float=.1,
                         terminal_growth: float=.03, no_distribution_years: int=5,
                         funding_year: int=3, participation: bool=True,
                         pre_money_multiple: float=1,
                         finite_distribution_years: int|None=None) -> dict[str,float]:
    for name,x in [('price',price_value),('funding',new_funding),('rate',rate),
                   ('terminal growth',terminal_growth),('pre-money multiple',pre_money_multiple)]: finite(x,name)
    integer(no_distribution_years,'non-distribution years'); integer(funding_year,'funding year')
    if price_value<=0 or new_funding<0 or rate<=terminal_growth or pre_money_multiple<=0:
        raise ValueError('Invalid frontier assumptions')
    if participation:
        target=price_value+new_funding*discount(rate,funding_year); retained=1.
    else:
        premoney=price_value*pre_money_multiple; retained=premoney/(premoney+new_funding)
        target=price_value/retained
    factor=(discount(rate,no_distribution_years)/(rate-terminal_growth) if finite_distribution_years is None
            else annuity(rate,finite_distribution_years,no_distribution_years,terminal_growth))
    cash=target/factor
    return dict(first_distribution_cash=cash,required_revenue_at_20pct=cash/.2,
                required_revenue_at_30pct=cash/.3,future_claim_fraction=retained,valuation_target=target)

def outputs(d: dict[str,Input]) -> dict[str,Any]:
    claim=iren_claim(d)
    s=Childress(value(d,'S_CAPEX_MID'),value(d,'S_ADV_ALLOC'),value(d,'S_PROJECT_COST'),
                int(value(d,'S_DELAY')),int(value(d,'S_H1_ELAPSED')),value(d,'S_RATE'))
    main=childress_forward(d,s); renewal=childress_renewal(d,s,16,.9)
    other=claim['debt_face_operating_requirement']-main['project_forward_value']-renewal['voluntary_exercise_value']
    sensitivities=[]
    for k in (2,4,6):
        for a in (0,value(d,'S_ADV_ALLOC'),value(d,'P_FEE')*.2):
            p=childress_forward(d,replace(s,remaining_capital=k,received_advance=a))
            remaining=claim['debt_face_operating_requirement']-p['project_forward_value']
            sensitivities.append(dict(remaining_capital=k,allocated_received_advance=a,
                                      project_value=p['project_forward_value'],required_other_value_no_tail=remaining,
                                      required_other_value_with_favorable_tail=remaining-renewal['voluntary_exercise_value']))
    timing=[]
    for delay,cost in [(0,.2),(3,.2),(12,.2),(12,.25)]:
        model=replace(s,delay_unstarted_months=delay,cash_cost_share=cost)
        p=childress_forward(d,model); tail=childress_renewal(d,model,16,.9)
        timing.append(dict(delay_unstarted_months=delay,cash_cost_share=cost,
                           project_value=p['project_forward_value'],favorable_tail=tail['voluntary_exercise_value'],
                           required_other_value=claim['debt_face_operating_requirement']-p['project_forward_value']-tail['voluntary_exercise_value']))
    paths=[]
    for name,r,g,m,k in [('favorable',.08,.18,.51,.20),('middle',.10,.18,.49,.25),('adverse',.12,.12,.45,.30)]:
        o=microsoft_value(d,g,r,m,k); eq=o['operating_value']-microsoft_bridge(d)['net_financial_claims']
        paths.append(dict(name=name,rate=r,rev_growth=g,operating_share=m,cap=k,
                          operating_value=o['operating_value'],equity_value=eq,
                          reference_equity_fraction=eq/microsoft_bridge(d)['paired_common_value'],terminal_share=o['terminal_share']))
    nv_cash=value(d,'N_OCF')-value(d,'N_CAPEX')-value(d,'N_SBC')
    nv_equity=value(d,'N_PRICE')*value(d,'N_SHARES')/1000
    return dict(inputs=len(d),iren_claim=claim,childress_main=main,childress_sensitivities=sensitivities,
        renewal_favorable=renewal,renewal_adverse=childress_renewal(d,s,8,.65),childress_timing_cost=timing,
        other_portfolio_required=other,other_requirement_if_full_restricted_cash_usable=other-value(d,'I_RESTRICTED'),
        other_portfolio=[dict(remaining_build_pv=b,**other_cash_requirement(other,b,rate=value(d,'S_RATE'),
            operating_years=int(value(d,'S_OTHER_YEARS')),delay=int(value(d,'S_OTHER_WAIT')),
            net_margin=value(d,'S_OTHER_MARGIN'),other_capacity_mw=value(d,'S_OTHER_MW'),
            price_million_per_mw=value(d,'S_OTHER_PRICE'))) for b in (0,5,15)],
        iren_funding_bridge=dict(vie_book_equity=value(d,'I_VIE_ASSETS')-value(d,'I_VIE_LIAB'),
            conditional_undrawn=value(d,'I_GPU_FULL')-value(d,'I_DDTL_DRAW')-value(d,'I_NOTE_DRAW'),restricted_cash=value(d,'I_RESTRICTED')),
        nvidia=dict(paired_equity_value=nv_equity,halfyear_cash_proxy=nv_cash,
            annualized_halfyear_proxy=2*nv_cash,multiple_to_annualized_proxy=nv_equity/(2*nv_cash)),
        iren_dilution=conversion_sensitivity(d),
        primary_funding=[dict(issue_price=p,**dilution(value(d,'I_SHARES'),2,p)) for p in (value(d,'I_PRICE'),30)],
        microsoft_bridge=microsoft_bridge(d),microsoft_grid=[dict(rate=r,terminal_reinvestment=k,
            **microsoft_required_growth(d,r,cap=k)) for r in (.08,.1,.12) for k in (.2,.25,.3)],
        microsoft_finite20=microsoft_required_growth(d,finite_years=20),
        microsoft_holding=[dict(holding_credit=h,**microsoft_required_growth(d,holding_credit=h)) for h in (0,100,200)],
        microsoft_paths=paths,
        frontier_cash_calls=[dict(new_funding=b,rate=r,**frontier_requirement(value(d,'O_VALUE'),b,r)) for r in (.1,.15) for b in (0,100,200)],
        frontier_dilution=[dict(pre_money_multiple=k,**frontier_requirement(value(d,'O_VALUE'),100,participation=False,pre_money_multiple=k)) for k in (.5,1,2)],
        frontier_finite15=frontier_requirement(value(d,'O_VALUE'),100,finite_distribution_years=15),
        frontier_two_year_delay=frontier_requirement(value(d,'O_VALUE'),100,no_distribution_years=7),
        anthropic_reference=frontier_requirement(value(d,'A_VALUE')),
        coreweave=dict(face=value(d,'CW_FACE'),net_before_expenses=value(d,'CW_NET'),
            net_after_capped_calls_before_expenses=value(d,'CW_NET')-value(d,'CW_CAPCOST'),
            annual_coupon=value(d,'CW_FACE')*value(d,'CW_COUPON'),
            initial_conversion_shares_million=value(d,'CW_FACE')*value(d,'CW_CONVRATE')))

def close(a: float,b: float,label: str='identity') -> None:
    if not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9):
        raise ValueError(f'{label} failed: {a} != {b}')

def run_tests(d: dict[str,Input]) -> None:
    close(annuity(.1,15,2),annuity(.1,15)/1.1**2)
    close(value(d,'S_ADV_ALLOC'),value(d,'I_VIE_DEFERRED'))
    if d['S_ADV_ALLOC'].status!='research_assumption': raise ValueError('Advance proxy status changed')
    for a in (0,1.013120,1.623480,value(d,'P_FEE')*.2):
        for delay in (0,3,12): childress_forward(d,Childress(received_advance=a,delay_unstarted_months=delay))
    base=childress_forward(d,Childress())['project_forward_value']; claim=iren_claim(d)['debt_face_operating_requirement']
    close(base-childress_forward(d,Childress(remaining_capital=5))['project_forward_value'],1)
    after=childress_forward(d,Childress(remaining_capital=3))['project_forward_value']
    close(claim+1-after,claim-base,'cash/cost-to-complete symmetry'); close(claim+2-2,claim)
    if childress_forward(d,Childress(received_advance=0))['project_forward_value']<=childress_forward(d,Childress(received_advance=1))['project_forward_value']:
        raise ValueError('Received advance reappeared as future cash')
    renew=childress_renewal(d,Childress(),8,.65)
    if not renew['incremental_value_today']<0 or renew['voluntary_exercise_value']!=0: raise ValueError('Optional refresh failed')
    bridge=microsoft_bridge(d); close(bridge['residual_economic_cash_proxy'],29.7715); close(bridge['net_financial_claims'],26.251)
    req=microsoft_required_growth(d)
    close(microsoft_value(d,req['required_revenue_growth'])['operating_value'],req['target_operating_value'])
    if microsoft_required_growth(d,cap=.3)['required_revenue_growth']<=microsoft_required_growth(d,cap=.2)['required_revenue_growth']:
        raise ValueError('Reinvestment monotonicity failed')
    f=frontier_requirement(852,100)
    if not frontier_requirement(852,0)['first_distribution_cash']<f['first_distribution_cash']<frontier_requirement(852,100,no_distribution_years=7)['first_distribution_cash']:
        raise ValueError('Funding/timing monotonicity failed')
    if frontier_requirement(852,100,finite_distribution_years=15)['first_distribution_cash']<=f['first_distribution_cash']:
        raise ValueError('Finite tail check failed')
    close(frontier_requirement(852,100,participation=False)['future_claim_fraction'],852/952)
    close(value(d,'CW_NET')-value(d,'CW_CAPCOST'),3.5708)
    fund=dilution(value(d,'I_SHARES'),2,value(d,'I_PRICE'))
    close(fund['new_shares_million']*value(d,'I_PRICE')/1000,fund['new_cash'])
    failures=[lambda:childress_forward(d,Childress(received_advance=3)),
              lambda:childress_renewal(d,Childress(),16,1.01),lambda:microsoft_value(d,.1,rate=.03),
              lambda:frontier_requirement(852,-1),lambda:value(d,'I_PRICE','USD_billion'),
              lambda:childress_forward(d,Childress(delay_unstarted_months=1.5)),
              lambda:frontier_requirement(852,float('nan')),lambda:discount(float('inf'),1)]
    for f in failures:
        try: f()
        except ValueError: pass
        else: raise ValueError('Invalid input was accepted')

def render_figure(d: dict[str,Input], destination: Path) -> None:
    """Redraw the supplied Microsoft sensitivity, not a live forecast."""
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9.2,5.8))
    caps=[.18+i*.01 for i in range(15)]
    for rate in (.08,.1,.12):
        ys=[100*microsoft_required_growth(d,rate,cap=k)['required_revenue_growth'] for k in caps]
        ax.plot([100*x for x in caps],ys,label=f'{rate:.0%} required return',linewidth=2)
    ax.set_xlabel('Long-run all-in reinvestment / revenue (%)')
    ax.set_ylabel('Required revenue growth over ten years (%) per year')
    ax.set_title('Microsoft: what the reference price requires\nCash retained after reinvestment changes the growth hurdle',loc='left',pad=16)
    ax.legend(frameon=False); ax.grid(alpha=.22)
    fig.text(.10,.03,'Conditional reverse test: Sept 24, 2026 price; FY2026 reference revenue; 49% pre-investment cash share.\n'
        'Reinvestment holds for two years, fades by year 7; 3% terminal growth; no separate OpenAI holding credit.\n'
        'Not a forecast or estimated cost of capital. See the ownership-price chapter and valuations-data.csv.',fontsize=9)
    fig.subplots_adjust(bottom=.24,left=.10,right=.97,top=.85)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Ownership-price calculations'})
    plt.close(fig)

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path);parser.add_argument('--json',action='store_true')
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args(); own=Path(__file__).resolve()
    path=args.data or own.with_name(own.name.replace('calculations.py','data.csv'))
    d=load_inputs(path);run_tests(d)
    if args.figure: render_figure(d,args.figure)
    print(json.dumps(outputs(d),indent=2,sort_keys=True))
    if not args.json: print('\nAll conservation, status, units, claim bridges, roots and invalid-input checks passed.')

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError,OverflowError) as error:
        raise SystemExit(f'Calculation failed: {error}') from error
