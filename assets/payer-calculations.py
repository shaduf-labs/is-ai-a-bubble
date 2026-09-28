#!/usr/bin/env python3
"""Actual cash accounts and conditional payer-funding tests.

Python 3.10+, standard library. No network calls or file modifications by default.
Run alongside payer-data.csv: python payer-calculations.py
Or: python payer-calculations.py --data /path/to/payer-data.csv
The delivery-prefixed sibling filenames also work without renaming.
Optional --figure PATH requires matplotlib and writes the explanatory SVG.

All monetary inputs and arithmetic are USD MILLIONS; printed money is USD billions.
Operating cash, contractual schedules, and policy/operating assumptions remain
separate. A resource ceiling is not legally cancellable expenditure. The $50bn
buffer is illustrative, not a covenant, safety finding or insolvency threshold.
The original research equations are retained; this reader adaptation adds input
validation and public filenames. It is not an actual current cash forecast.
"""
from __future__ import annotations
import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    entity: str
    start: str
    end: str
    source: str

Data = dict[str, Input]

def load_inputs(path: Path) -> Data:
    data: Data = {}
    required = {'id','entity','metric','value','unit','status','period_start',
                'period_end','source_id','source_url','locator'}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Missing required CSV columns')
        for line, row in enumerate(reader, 2):
            if None in row or any(row.get(k) is None for k in required):
                raise ValueError(f'Malformed CSV row at line {line}')
            key = row['id'].strip()
            if not key or key in data:
                raise ValueError(f'Blank or duplicate input ID at line {line}')
            number = float(row['value'])
            if not math.isfinite(number):
                raise ValueError(f'Nonfinite input: {key}')
            if not all(row[k] for k in ('entity','metric','unit','status','period_end','source_id','locator')):
                raise ValueError(f'Missing boundary or provenance: {key}')
            if row['status'] != 'research_assumption' and not row['source_url'].startswith('https://'):
                raise ValueError(f'Observed input lacks a source URL: {key}')
            data[key] = Input(number,row['unit'],row['status'],row['entity'],
                              row['period_start'],row['period_end'],row['source_id'])
    if not data:
        raise ValueError('Empty CSV')
    return data

def v(d: Mapping[str,Input], key: str, unit: str='USD_million') -> float:
    z = d[key]
    if z.unit != unit:
        raise ValueError(f'Unit mismatch for {key}: expected {unit}, found {z.unit}')
    return z.value

def nonnegative(**xs: float) -> None:
    if any(not math.isfinite(x) or x < 0 for x in xs.values()):
        raise ValueError('Inputs must be finite and nonnegative: '+', '.join(xs))

def growth_domain(growth: float, investment_growth: float = 0) -> None:
    if not math.isfinite(growth) or not math.isfinite(investment_growth) or growth <= -1 or investment_growth < -1:
        raise ValueError('Invalid operating or investment growth')

def total(d: Data, prefix: str, keys: str) -> float:
    return sum(v(d, prefix+'_'+k) for k in keys.split())

MS_INV='ppe acquisitions investment_purchases investment_maturities investment_sales other_investing'
MS_FIN='short_debt_net debt_proceeds debt_repayments stock_issued stock_repurchase_cash dividends other_financing'
META_INV='ppe marketable_purchases marketable_sales held_for_sale venture_distribution nonmarketable acquisitions other_investing'
META_FIN='rsu_cash buybacks dividends debt_proceeds fl_principal other_financing'
OR_INV='ppe investment_purchases investment_sales'
OR_FIN='atm_net employee_stock_net dividends cp_net short_cap_finance_net debt_repayments other_financing'
MS_OP='ni da_other sbc investment_gains deferred_tax wc_ar wc_inventory wc_other_current wc_other_long wc_ap wc_unearned wc_tax wc_current_liab wc_long_liab'
META_OP='ni da sbc deferred_tax unrealized_losses other_noncash wc_ar wc_prepaid wc_other_assets wc_ap wc_accrued wc_other_liab'
OR_OP='ni da intangible_amort deferred_tax sbc other_noncash wc_ar wc_prepaid wc_ap wc_tax financing_prepay other_deferred'

@dataclass(frozen=True)
class Account:
    begin: float
    ocf: float
    cfi: float
    cff: float
    fx: float
    end: float

def account(d: Data, prefix: str) -> Account:
    return Account(*(v(d,prefix+'_'+k) for k in ('begin','ocf','cfi','cff','fx','end')))

def microsoft_h1(d: Data, year: int) -> Account:
    """January-June = full fiscal year less preceding July-December flows.

    Beginning and ending stocks are selected, not subtracted from one another.
    """
    if year not in (2025,2026):
        raise ValueError('Only observed windows 2025/2026 are supported')
    full = account(d,'M'+str(year)[2:]); first = account(d,'MH'+str(year-1)[2:])
    return Account(first.end, full.ocf-first.ocf, full.cfi-first.cfi,
                   full.cff-first.cff, full.fx-first.fx, full.end)

def ms_base(d: Data) -> dict[str,float]:
    liquidity = v(d,'M_CASH')+v(d,'M_SEC')-v(d,'M_SEC_RESTRICTED')
    prelease = v(d,'M26_ocf')+v(d,'M26_op_lease_cash')+v(d,'M26_fl_interest_cash')
    envelope = -v(d,'M26_ppe')-v(d,'M26_other_investing')
    # Later undeclared dividends and an unchanged share count are assumptions.
    dividend = v(d,'M_SEP_DIV')+3*v(d,'M_NEW_DIV','USD_per_share')*v(d,'M_SHARES','million_shares')
    nonprogram = -v(d,'M26_stock_repurchase_cash')-v(d,'M_PROGRAM')
    other = dividend+nonprogram-v(d,'M26_acquisitions')
    return dict(liquidity=liquidity,prelease=prelease,envelope=envelope,
                dividend=dividend,nonprogram=nonprogram,other=other)

@dataclass(frozen=True)
class Funding:
    end: float
    cash_required: float
    investment_capacity: float
    target_gap: float

def funding(*, start: float, cash: float, investment: float, fixed: float,
            other: float, target: float, finance: float=0, incremental: float=0) -> Funding:
    """Assign each use to exactly ONE bucket; no intraperiod payment calendar.

    'fixed' denotes this equation's explicit payment deductions, not a finding
    that all other expenditure is legally discretionary. A negative end balance
    means these assumptions cannot coexist without adjustment or funding.
    """
    nonnegative(start=start,cash=cash,investment=investment,fixed=fixed,other=other,
                target=target,finance=finance,incremental=incremental)
    end = start+cash+finance-investment-fixed-other-incremental
    required = target-start-finance+investment+fixed+other+incremental
    capacity = start+cash+finance-fixed-other-incremental-target
    return Funding(end,required,capacity,max(0,target-end))

def ms_year1(d: Data, *, growth: float=0, investment_growth: float=0,
             retain_program: bool=False, tax_reset: bool=False, target: float|None=None,
             extra: float=0, finance: float=0) -> Funding:
    growth_domain(growth,investment_growth)
    b=ms_base(d)
    cash=b['prelease']*(1+growth)
    if tax_reset:
        cash-=v(d,'M_TAX25')-v(d,'M_TAX26')
    other=b['other']+(v(d,'M_PROGRAM') if retain_program else 0)
    return funding(start=b['liquidity'],cash=cash,investment=b['envelope']*(1+investment_growth),
                   fixed=v(d,'M_LEASE27')+v(d,'M_DEBT27'),other=other,
                   target=v(d,'A_BUFFER') if target is None else target,
                   incremental=extra,finance=finance)

def ms_year2_uncommenced_capacity(d: Data, start: float, *, growth: float=0,
                                 investment_growth: float=0, target:float|None=None) -> float:
    """Maximum extra FY2028 lease cash X beyond the commenced schedule.

    Holds the selected operating/investment STATE, not a second compound-growth
    step. The unknown lease-start schedule is not spread from a lifetime total.
    Four dividends at the September-declared rate are policy assumptions.
    """
    growth_domain(growth,investment_growth)
    b=ms_base(d); nonnegative(start=start)
    if target is not None:
        nonnegative(target=target)
    return (start+b['prelease']*(1+growth)-b['envelope']*(1+investment_growth)
            -v(d,'M_LEASE_OP28')-v(d,'M_LEASE_FL28')-v(d,'M_DEBT28')
            -(b['other']-b['dividend']+4*v(d,'M_NEW_DIV','USD_per_share')*v(d,'M_SHARES','million_shares'))
            -(v(d,'A_BUFFER') if target is None else target))

def meta_base(d: Data) -> dict[str,float]:
    start=v(d,'T_CASH')+v(d,'T_SEC')
    h225=v(d,'T25_ocf')-v(d,'TH25_ocf')
    growth=v(d,'TH26_ocf')/v(d,'TH25_ocf')-1
    spent=-v(d,'TH26_ppe')-v(d,'TH26_fl_principal')
    rsu=-(v(d,'T25_rsu_cash')-v(d,'TH25_rsu_cash'))
    div=-(v(d,'T25_dividends')-v(d,'TH25_dividends'))
    other=-total(d,'TH26','nonmarketable held_for_sale acquisitions other_investing other_financing')
    ttm=v(d,'T25_ocf')+v(d,'TH26_ocf')-v(d,'TH25_ocf')
    return dict(liquidity=start,h225=h225,recent_growth=growth,spent=spent,
                rsu=rsu,div=div,other=other,ttm=ttm)

def meta_h2(d: Data, *, growth:float=0, high:bool=True, tax_reset:bool=False,
            target:float|None=None, extra:float=0, finance:float=0) -> Funding:
    growth_domain(growth)
    b=meta_base(d); cash=b['h225']*(1+growth)
    if tax_reset:
        cash-=v(d,'TH25_cash_tax')-v(d,'TH26_cash_tax')
    investment=v(d,'T_CAP_HIGH' if high else 'T_CAP_LOW')-b['spent']
    return funding(start=b['liquidity'],cash=cash,investment=investment,
                   fixed=v(d,'T_DEBT26'),other=b['rsu']+b['div']+b['other'],
                   target=v(d,'A_BUFFER') if target is None else target,
                   incremental=extra,finance=finance)

def meta_2027(d: Data,start:float,cash:float,investment:float,
              target:float|None=None,extra:float=0)->Funding:
    """Conditional 2027 continuation, NOT issuer guidance.

    OCF contains operating rents and interest; capital contains finance-lease
    principal. Additional unmodeled rent/interest/restrictions enter extra once.
    """
    b=meta_base(d)
    rsu=-v(d,'T25_rsu_cash')-v(d,'TH26_rsu_cash')+v(d,'TH25_rsu_cash')
    div=-v(d,'T25_dividends')-v(d,'TH26_dividends')+v(d,'TH25_dividends')
    return funding(start=start,cash=cash,investment=investment,fixed=v(d,'T_DEBT27'),
                   other=rsu+div+2*b['other'],target=v(d,'A_BUFFER') if target is None else target,
                   incremental=extra)

def finance_needed(gap:float,cash_rate:float)->float:
    """New net funds if the assumed cash financing cost is paid in the window.

    Principal is a new claim; this is not a quote or an available commitment.
    """
    nonnegative(gap=gap)
    if not math.isfinite(cash_rate) or not 0<=cash_rate<1:
        raise ValueError('Invalid new-finance cash rate')
    return gap/(1-cash_rate)

def oracle_counterfactual(d:Data,remove_equity:bool=False,remove_advance:bool=False)->float:
    """Retrospective source dependence at FIXED actual uses and restrictions.

    Not normalized OCF, a pro-forma balance sheet, or a no-financing forecast.
    """
    return (v(d,'O_CASH')+v(d,'O_SEC')
            -(v(d,'O26_atm_net') if remove_equity else 0)
            -(v(d,'O26_financing_prepay') if remove_advance else 0))

def close(x:float,y:float)->None:
    if not math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7):
        raise AssertionError(f'{x} != {y}')

def run_tests(d:Data)->None:
    for prefixes,inv,fin in [(['M26','M25','M24','MH25','MH24'],MS_INV,MS_FIN),
                            (['T25','T24','T23','TH26','TH25'],META_INV,META_FIN),
                            (['O26','O25'],OR_INV,OR_FIN)]:
        for p in prefixes:
            a=account(d,p)
            close(a.begin+a.ocf+a.cfi+a.cff+a.fx,a.end)
            close(total(d,p,inv),a.cfi); close(total(d,p,fin),a.cff)
    for p,keys in [('M26',MS_OP),('TH26',META_OP),('O26',OR_OP),('O25',OR_OP)]:
        close(total(d,p,keys),v(d,p+'_ocf'))
    for y in (2025,2026):
        a=microsoft_h1(d,y); close(a.begin+a.ocf+a.cfi+a.cff+a.fx,a.end)
    close(v(d,'T_CASH')+v(d,'T_RESTRICT_C')+v(d,'T_RESTRICT_L'),v(d,'TH26_end'))
    close(v(d,'T_CASH25')+v(d,'T_RESTRICT_C25')+v(d,'T_RESTRICT_L25'),v(d,'TH26_begin'))
    close(v(d,'T_DEBT26')+v(d,'T_DEBT27')+v(d,'T_DEBT28')+v(d,'T_DEBT_LATER'),v(d,'T_DEBT_FACE'))
    close(v(d,'M_LEASE27')-v(d,'M_LEASE_OP27')-v(d,'M_LEASE_FL27'),19208)
    inferred=v(d,'M_LEASE27')+v(d,'M_LEASE_LATER')-v(d,'M_LEASE_OP_TOTAL')-v(d,'M_LEASE_FL_TOTAL')
    if abs(inferred-v(d,'M_LEASE_UNSTART'))>50:
        raise AssertionError('Lease perimeter reconciliation failed')
    b=ms_base(d); close(b['liquidity'],73043); close(b['prelease'],191925); close(b['envelope'],135809)
    base=ms_year1(d); preserved=ms_year1(d,retain_program=True)
    close(base.end-preserved.end,v(d,'M_PROGRAM'))
    close(ms_year1(d,finance=1000).end-base.end,1000)
    close(ms_year1(d,extra=1000).end-base.end,-1000)
    close(ms_year1(d,tax_reset=True).end-base.end,-(v(d,'M_TAX25')-v(d,'M_TAX26')))
    close(ms_year1(d,target=b['liquidity']).cash_required/b['prelease']-1,0.11165874469438619)
    close(ms_year1(d,target=0).end,base.end)
    close(ms_year1(d,target=0).investment_capacity-base.investment_capacity,v(d,'A_BUFFER'))
    t=meta_base(d); low=meta_h2(d,high=False); high=meta_h2(d)
    close(low.end-high.end,v(d,'T_CAP_HIGH')-v(d,'T_CAP_LOW'))
    close(t['spent'],50918); close(t['h225'],66213); close(t['other'],4950)
    close(meta_h2(d,growth=t['recent_growth']).end-high.end,t['h225']*t['recent_growth'])
    close(oracle_counterfactual(d,True,True),5805)
    close(v(d,'CW_NET')-v(d,'CW_CAPCALL'),3570.8)
    if d['CW_FACE'].status!='reported_closed':
        raise AssertionError('Closing status lost')
    if 'NVIDIA_RECEIPT' in d:
        raise AssertionError('Unverified receipt entered model')
    close(finance_needed(1000,.06)*(1-.06),1000)
    for fn in [lambda:finance_needed(1,1), lambda:v(d,'M_NEW_DIV'),
               lambda:funding(start=1,cash=-1,investment=0,fixed=0,other=0,target=0),
               lambda:ms_year1(d,growth=-2), lambda:ms_year1(d,growth=math.nan),
               lambda:finance_needed(1,math.nan)]:
        try:
            fn()
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid input accepted')

def print_results(d:Data)->None:
    f=lambda x:f'{x/1000:.3f}'
    print(f'{len(d)} source records. Currency: USD billions below; USD millions in the input and functions.')
    print('Conditional tests, not current cash forecasts, solvency tests or legal cancellation budgets.\n')
    print('ACTUAL CASH ACCOUNTS: periods differ across companies')
    print('Period | beginning | operating | investing | financing | FX | ending')
    names={'M24':'Microsoft FY2024','M25':'Microsoft FY2025','M26':'Microsoft FY2026',
           'T23':'Meta 2023','T24':'Meta 2024','T25':'Meta 2025',
           'TH25':'Meta Jan-Jun 2025','TH26':'Meta Jan-Jun 2026',
           'O25':'Oracle Jun-Aug 2025','O26':'Oracle Jun-Aug 2026'}
    for p in names:
        a=account(d,p)
        print(names[p],'|',' | '.join(f(x) for x in (a.begin,a.ocf,a.cfi,a.cff,a.fx,a.end)))
    print('\nMATCHED JANUARY-JUNE MICROSOFT')
    for year in (2025,2026):
        a=microsoft_h1(d,year)
        print(year,'|',' | '.join(f(x) for x in (a.begin,a.ocf,a.cfi,a.cff,a.fx,a.end)))
    print('\nMICROSOFT FY2027: June-anchored, after identified restriction')
    b=ms_base(d); print('Base values:',{k:f(x) for k,x in b.items()})
    cases=[('Flat; repeat program buybacks',dict(retain_program=True)),
           ('Flat; no new program buybacks',{}),
           ('Tax reset; no program buybacks',dict(tax_reset=True)),
           ('Favorable net prelease cash +20%, investment +10%; no program',dict(growth=.2,investment_growth=.1)),
           ('Same favorable state; repeat program',dict(growth=.2,investment_growth=.1,retain_program=True))]
    for name,kw in cases:
        r=ms_year1(d,**kw)
        print(name,': end',f(r.end),'investment capacity at $50bn buffer',f(r.investment_capacity),
              'buffer gap',f(r.target_gap),'new funds at assumed 6% cash cost',f(finance_needed(r.target_gap,v(d,'A_FIN_RATE','fraction'))))
    hold=ms_year1(d,target=b['liquidity'])
    print('No-drawdown required net prelease cash',f(hold.cash_required),'growth',f'{hold.cash_required/b["prelease"]-1:.6%}')
    schedule=v(d,'M_CONSTRUCT27')+v(d,'M_PURCHASE27')
    print('Purchase/construction schedule',f(schedule),'required overlap or valid adjustment',f(schedule-ms_year1(d).investment_capacity))
    for name,kw in [('flat',{}),('favorable',dict(growth=.2,investment_growth=.1))]:
        print('FY2028 extra-lease X ceiling, '+name,f(ms_year2_uncommenced_capacity(d,ms_year1(d,**kw).end,**kw)))
    print('\nMETA: SEASONALLY MATCHED SECOND HALF 2026')
    t=meta_base(d)
    print('Base values:',{k:(f'{x:.6%}' if k=='recent_growth' else f(x)) for k,x in t.items()})
    for name,kw in [('Seasonally flat; low capital',dict(high=False)),('Seasonally flat; high capital',{}),
                    ('High capital; tax reset',dict(tax_reset=True)),
                    ('Repeat first-half year-on-year cash growth; high capital',dict(growth=t['recent_growth']))]:
        r=meta_h2(d,**kw)
        print(name,': end',f(r.end),'OCF required for $50bn',f(r.cash_required),'gap',f(r.target_gap),
              'new funds at assumed 6%',f(finance_needed(r.target_gap,v(d,'A_FIN_RATE','fraction'))))
    r=meta_h2(d)
    print('H2 growth required for $50bn',f'{r.cash_required/t["h225"]-1:.6%}',
          'OCF for no drawdown',f(meta_h2(d,target=t['liquidity']).cash_required))
    for name,g in [('flat',0),('favorable',t['recent_growth'])]:
        start=meta_h2(d,growth=g).end
        for cash in [t['ttm'],t['ttm']*(1+t['recent_growth'])]:
            r=meta_2027(d,start,cash,v(d,'T_CAP_HIGH'))
            print('2027 from',name,'OCF',f(cash),'capital capacity at $50bn',f(r.investment_capacity),
                  'end at $145bn capital',f(r.end),'OCF required',f(r.cash_required))
    print('\nORACLE: RETROSPECTIVE FIXED-USES SOURCE DEPENDENCE')
    for e,a in [(False,False),(True,False),(True,True)]:
        print('Remove equity:',e,'remove financing advance:',a,'resources',f(oracle_counterfactual(d,e,a)))
    print('OCF excluding only financing advance, NOT normalized OCF',f(v(d,'O26_ocf')-v(d,'O26_financing_prepay')))
    print('CoreWeave closing after discounts/capped calls, before other expenses',f(v(d,'CW_NET')-v(d,'CW_CAPCALL')))
    print('\nAll cash, unit, scope, status, breakpoint and invalid-input checks passed.')

def render_figure(d:Data,destination:Path)->None:
    """Explanatory funding boundary from the same functions; matplotlib optional."""
    import matplotlib.pyplot as plt
    from matplotlib.text import Text
    b=ms_base(d); xs=list(range(-10,41))
    no=[ms_year1(d,growth=x/100).investment_capacity/1000 for x in xs]
    yes=[ms_year1(d,growth=x/100,retain_program=True).investment_capacity/1000 for x in xs]
    fig,ax=plt.subplots(figsize=(10,6))
    ax.plot(xs,no,label='No new program buybacks',linewidth=2)
    ax.plot(xs,yes,label='Repeat FY2026 program buybacks',linewidth=2,linestyle='--')
    ax.axhline(b['envelope']/1000,linestyle=':',label='FY2026 cash-investment reference: $135.809bn')
    ax.set_xlabel('Net operating cash before leases: change from FY2026 (%)')
    ax.set_ylabel('Cash-investment capacity (USD bn)\nwith a $50bn closing buffer')
    ax.set_title('Microsoft: a payment-aware funding boundary, not a valuation')
    ax.legend(loc='upper left',fontsize=9)
    ax.grid(axis='y',alpha=.25)
    fig.text(.11,.025,'Conditional FY2027 test. Start: June2026 cash/short-term investments less $3.8bn restricted funds.\n'
             'Deduct full $32.411bn lease schedule, $9.25bn principal and modeled dividends/other uses.\n'
             'Capacity is not legally cancellable spending. No new finance; no future receipt of supplier receivables assumed.\n'
             'Source inputs and formulas: report §§2–6 and data.csv. $50bn is a research buffer, not a covenant.',fontsize=9)
    fig.subplots_adjust(left=.11,right=.97,top=.88,bottom=.25)
    for text in fig.findobj(match=Text):
        text.set_parse_math(False)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Payer funding calculations'})
    plt.close(fig)

def main()->None:
    own=Path(__file__).resolve()
    sibling=own.with_name(own.name.replace('calculations.py','data.csv'))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=sibling)
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args()
    d=load_inputs(args.data); run_tests(d); print_results(d)
    if args.figure:
        render_figure(d,args.figure)

if __name__=='__main__':
    try:
        main()
    except (OSError,KeyError,ValueError,AssertionError) as exc:
        raise SystemExit(f'Calculation failed: {exc}') from exc
