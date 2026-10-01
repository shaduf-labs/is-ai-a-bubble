#!/usr/bin/env python3
"""Older capacity: historical continuation budgets and service-substitution tests.

Python >=3.10; standard-library calculations. Optional --figure needs matplotlib.
  python continuation-calculations.py [--data continuation-data.csv]
  python continuation-calculations.py --figure continuation-budget.svg
Delivery-prefixed sibling names also work. No network calls or live data updates.

The Austin diagnostic is anchored at March 31, 2025 and was assembled using
amended historical accounts inspected September 29, 2026. It is NOT a backtest,
current appraisal, actual cash-flow record or full contract valuation. Disclosed
annual fee buckets are paired with a Q1 expense calibration, NOT verified cash
cost. The net cash-cost correction is signed. The undated later receipt bucket
and its associated costs remain outside the finite test, not assumed worthless.
No terminal sale, new financing receipt or repeated historical build cost enters.
Read the accompanying chapter for the contract, rights and inference boundaries.
"""
from __future__ import annotations
import argparse
import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path

COLUMNS = {'id','entity','metric','value','unit','period','status','source_id',
           'source_url','locator','notes'}
UNITS = {'calendar_year','USD_per_node_hour','GPU_per_node','GB_per_GPU',
         'TB_per_node','MW_customer','MW_facility','years','USD_million',
         'MW_contract','fraction','GPU','USD_million_per_year','quarters_per_year'}
STATUSES = {'company_reported','company_reported_contract','posted_tariff',
            'posted_specification','reported','reported_contract',
            'reported_contract_rounded','reported_contract_schedule',
            'reported_expense','company_estimate','reported_rounded',
            'company_reported_operating','reported_restricted_cash',
            'reported_funded','company_operating_run_rate','inherited_assumption',
            'inherited_calculation','research_assumption'}

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    source: str
    period: str


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_inputs(path: Path) -> dict[str, Input]:
    data: dict[str, Input] = {}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        require(len(fields)==len(set(fields)) and COLUMNS.issubset(fields),
                'Missing or duplicate ledger columns')
        for row in reader:
            require(None not in row and all(v is not None for v in row.values()),
                    'Malformed CSV row')
            key = row['id'].strip()
            require(bool(key) and key not in data, f'Missing/duplicate ID: {key!r}')
            for field in ('entity','metric','unit','period','status','source_id','source_url','locator'):
                require(bool(row[field].strip()), f'Missing {field}: {key}')
            number = float(row['value'])
            require(math.isfinite(number), f'Nonfinite number: {key}')
            require(row['unit'] in UNITS, f'Unknown unit: {key}')
            require(row['status'] in STATUSES, f'Unknown evidence status: {key}')
            require(row['source_url'].startswith('https://'), f'Expected public source URL: {key}')
            data[key] = Input(number,row['unit'],row['status'],row['source_id'],row['period'])
    require(bool(data), 'Empty ledger')
    return data


def val(data: dict[str, Input], key: str, unit: str) -> float:
    record = data[key]
    require(record.unit == unit, f'Unit mismatch for {key}: {record.unit} != {unit}')
    return record.value


def m(data: dict[str, Input], key: str) -> float:
    return val(data,key,'USD_million')


def near(a: float, b: float, label: str = 'identity') -> None:
    require(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8), f'{label}: {a} != {b}')


@dataclass(frozen=True)
class AustinCase:
    # USD million. Underlying rent is already inside the expense calibration.
    annual_direct_expense: float
    annual_escalation: float = 0.0
    annual_net_cash_correction: float = 0.0
    rate: float = 0.10
    incremental_upfront: float = 0.0

    def __post_init__(self) -> None:
        numbers = (self.annual_direct_expense,self.annual_escalation,
                   self.annual_net_cash_correction,self.rate,self.incremental_upfront)
        require(all(math.isfinite(x) for x in numbers), 'Nonfinite scenario parameter')
        require(self.annual_direct_expense >= 0 and self.incremental_upfront >= 0,
                'Direct expense and upfront spending must be nonnegative')
        require(self.annual_escalation > -1 and self.rate >= 0,
                'Invalid escalation or discount rate')
        # The net correction can be negative: actual cash rent, compensation,
        # working capital, overhead, tax and maintenance may adjust either way.


@dataclass(frozen=True)
class Period:
    year: int
    years_from_anchor: float
    fraction: float
    receipts: float
    direct_expense: float
    correction: float
    net: float
    pv: float


def annual_direct_expense(data: dict[str, Input]) -> float:
    return (m(data,'AQ_COST')-m(data,'AQ_POWER')-m(data,'AQ_DEP')) * val(data,'M_QUARTERS','quarters_per_year')


def finite_austin(data: dict[str, Input], case: AustinCase) -> list[Period]:
    first = val(data,'M_FIRST_FRACTION','years')
    require(0 < first <= 1, 'Invalid first-year fraction')
    periods: list[Period] = []
    for i,year in enumerate(range(2025,2030)):
        key = f'AQ_R_{year}'
        rec = data[key]
        require(rec.status=='reported_contract_schedule' and rec.source=='CS25Q1',
                'Receipts must remain the disclosed historical single-site schedule')
        receipts = m(data,key)
        require(receipts >= 0, 'Negative scheduled receipt')
        fraction = first if i==0 else 1.0
        t = first+i
        expense = case.annual_direct_expense*fraction*(1+case.annual_escalation)**i
        correction = case.annual_net_cash_correction*fraction
        net = receipts-expense-correction
        periods.append(Period(year,t,fraction,receipts,expense,correction,net,net/(1+case.rate)**t))
    return periods


def budget(data: dict[str, Input], case: AustinCase) -> float:
    """Signed finite cost budget, not a transferable market value or owner cash."""
    return sum(p.pv for p in finite_austin(data,case))-case.incremental_upfront


def correction_limit(data: dict[str, Input], case: AustinCase) -> float:
    """Total annual net correction that exhausts the budget, keeping upfront cost.

    A positive limit is not evidence that actual net costs lie below it, or that
    stopping service avoids contractual rent. No claim allocation is performed.
    """
    zero = replace(case,annual_net_cash_correction=0)
    weight = sum(p.fraction/(1+case.rate)**p.years_from_anchor for p in finite_austin(data,zero))
    return budget(data,zero)/weight


def escalation_limit(data: dict[str, Input], case: AustinCase) -> float:
    lo,hi = 0.0,1.0
    require(budget(data,replace(case,annual_escalation=lo)) >= 0 and
            budget(data,replace(case,annual_escalation=hi)) <= 0,'Escalation root not bracketed')
    for _ in range(100):
        mid=(lo+hi)/2
        if budget(data,replace(case,annual_escalation=mid)) > 0:
            lo=mid
        else:
            hi=mid
    return (lo+hi)/2


def speedup_threshold(old_rate: float,new_rate: float,migration_per_old_hour: float=0.0) -> float:
    """Buyer rental test ONLY when service/quality are equivalent. Not measured speed.

    old_rate*H versus new_rate*H/s + migration. Tariffs are not achieved prices.
    The speedup s must exceed the result; equality gives equal rental cost.
    """
    require(all(math.isfinite(x) for x in (old_rate,new_rate,migration_per_old_hour)),
            'Nonfinite service-price input')
    require(old_rate>0 and new_rate>0 and migration_per_old_hour>=0,'Invalid service-price input')
    denom=old_rate-migration_per_old_hour
    return math.inf if denom<=0 else new_rate/denom


def billed_and_power_bridge(data: dict[str, Input], prefix: str) -> dict[str,float]:
    revenue=m(data,prefix+'_REVENUE')
    power=m(data,prefix+'_POWER')
    return {'revenue':revenue,'nonpower_revenue':revenue-power,
            'direct_expense_ex_power_depreciation':m(data,prefix+'_COST')-power-m(data,prefix+'_DEP'),
            'gross_profit':m(data,prefix+'_GP')}


def run_tests(data: dict[str, Input]) -> None:
    for p in ('A24','AQ'):
        near(sum(m(data,p+'_'+k) for k in ('LICENSE','OTHERREV','POWER')),m(data,p+'_REVENUE'),p+' revenue')
        near(sum(m(data,p+'_'+k) for k in ('EMPLOYEE','FACILITY','OTHERCOST','DEP','POWER')),m(data,p+'_COST'),p+' costs')
        near(m(data,p+'_REVENUE')-m(data,p+'_COST'),m(data,p+'_GP'),p+' profit')
        near(sum(m(data,p+'_R_'+str(y)) for y in range(2025,2030))+m(data,p+'_R_later'),m(data,p+'_R_TOTAL'),p+' schedule')
    near(m(data,'A24_R_TOTAL')-m(data,'AQ_R_TOTAL'),5.685,'schedule rolloff is NOT collection')
    near(m(data,'AQ_LICENSE')-5.685,.310,'accrual versus scheduled rolloff')
    near(m(data,'A24_R_TOTAL')-m(data,'A_HEAD_RENT24'),66.006,'rounded whole-term spread')
    near(annual_direct_expense(data),21.812,'annual expense calibration')
    near(m(data,'DEF_BEGIN')+m(data,'DEF_NEW')-m(data,'DEF_USED')-m(data,'DEF_NONCASH'),m(data,'DEF_END'),'deferred revenue')
    c=AustinCase(annual_direct_expense(data))
    near(budget(data,c),10.426678685875055,'flat cost')
    near(correction_limit(data,c),2.8570598920557746,'net correction limit')
    near(budget(data,replace(c,annual_escalation=.03)),5.6951990121045615,'3% cost growth')
    near(budget(data,replace(c,annual_escalation=.06)),.6897076177479406,'6% cost growth')
    near(budget(data,replace(c,incremental_upfront=2)),budget(data,c)-2,'upfront paid once')
    near(budget(data,replace(c,annual_net_cash_correction=correction_limit(data,c))),0,'correction root')
    near(budget(data,replace(c,annual_escalation=escalation_limit(data,c))),0,'escalation root')
    changed=dict(data)
    changed['AQ_R_later']=replace(data['AQ_R_later'],value=99999)
    near(budget(changed,c),budget(data,c),'undated tail stays outside finite test')
    for g in (0,.03,.06):
        cg=replace(c,annual_escalation=g)
        require(budget(data,replace(cg,annual_net_cash_correction=1))<budget(data,cg),'More costs reduce budget')
    near(speedup_threshold(val(data,'P_A100','USD_per_node_hour'),val(data,'P_H100','USD_per_node_hour')),2.2796296296296297,'rental threshold')
    require(speedup_threshold(21.6,49.24,1)>speedup_threshold(21.6,49.24),'Migration is not free')
    require(math.isinf(speedup_threshold(21.6,49.24,21.6)),'No finite threshold domain')
    for k in ('P_A100','P_H100'):
        require(data[k].status=='posted_tariff','A tariff is not an achieved renewal price')
    # Different inherited scenarios; neither uses the Austin budget as asset value.
    recovery = val(data,'RECOVERY_FULL_SALES','USD_million_per_year')*val(data,'RECOVERY_UTIL','fraction') \
        -val(data,'RECOVERY_VARIABLE','USD_million_per_year')*val(data,'RECOVERY_UTIL','fraction') \
        -val(data,'RECOVERY_FIXED','USD_million_per_year')
    ownership = val(data,'OWNERSHIP_FULL_SALES','USD_million_per_year')*val(data,'OWNERSHIP_UTIL','fraction') \
        *(1-val(data,'OWNERSHIP_VARIABLE_SHARE','fraction'))-val(data,'OWNERSHIP_FIXED','USD_million_per_year')
    near(recovery,2500,'original-recovery second-cycle assumption')
    near(ownership,1910,'forward-ownership second-cycle assumption')
    for kwargs in ({'annual_direct_expense':-1},{'annual_direct_expense':1,'rate':-1},
                   {'annual_direct_expense':1,'annual_escalation':-1},
                   {'annual_direct_expense':1,'incremental_upfront':-1},
                   {'annual_direct_expense':1,'annual_net_cash_correction':float('nan')}):
        try: AustinCase(**kwargs)
        except ValueError: pass
        else: raise ValueError('Invalid case accepted')
    try: speedup_threshold(0,5)
    except ValueError: pass
    else: raise ValueError('Invalid service input accepted')


def render_figure(data: dict[str, Input], destination: Path) -> None:
    """Reproduce the supplied finite-budget drawing; optional local dependency."""
    import matplotlib.pyplot as plt
    c=AustinCase(annual_direct_expense(data),rate=val(data,'M_RATE','fraction'))
    cases=[replace(c,annual_escalation=0),replace(c,annual_escalation=.03),
           replace(c,annual_escalation=.06),
           replace(c,annual_escalation=.06,annual_net_cash_correction=1)]
    labels=['Flat direct-expense proxy','Direct expense grows 3% a year',
            'Direct expense grows 6% a year','6% growth + $1m/year net cash correction']
    values=[budget(data,x) for x in cases]
    fig,ax=plt.subplots(figsize=(11.7,6.8))
    ax.barh(range(len(labels)),values,height=.6)
    ax.set_yticks(range(len(labels)),labels,fontsize=10)
    ax.invert_yaxis()
    ax.axvline(0,linewidth=.8)
    for i,v in enumerate(values):
        ax.text(v+(.17 if v>=0 else -.17),i,f'{v:+.2f}',
                ha='left' if v>=0 else 'right',va='center',fontsize=11)
    ax.set_xlim(min(values)-2,max(values)+2)
    ax.set_xlabel('Finite remaining budget (USD millions, present value at March 31, 2025)',fontsize=10)
    ax.set_title('Useful service does not provide an unlimited refit budget',fontsize=15,pad=18)
    fig.text(.035,.16,'Austin hosting: disclosed April 2025–2029 minimum fees; Q1 2025 expense calibration; 10% assumed return.',fontsize=10)
    fig.text(.035,.105,'The expense proxy is not verified cash cost. Net corrections, new refit spending and prior claims must still be met.\n'
             'Negative means the specified finite budget does not cover those assumptions—not default or a shutdown instruction.',fontsize=9)
    fig.text(.035,.045,'No terminal sale or undated later receipts. Not a September 2026 appraisal. Source: report §§4–5; data.csv; calculations.py.',fontsize=9)
    fig.subplots_adjust(left=.40,right=.95,top=.83,bottom=.28)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Is AI a Bubble? continuation calculations'})
    plt.close(fig)


def print_results(data: dict[str, Input]) -> None:
    c=AustinCase(annual_direct_expense(data),rate=val(data,'M_RATE','fraction'))
    print('HISTORICAL SINGLE-SITE RECONCILIATION; USD millions unless stated')
    print(f'December 2024 whole-term fees less rounded headlease: {m(data,"A24_R_TOTAL")-m(data,"A_HEAD_RENT24"):.6f}')
    print(f'Q1 scheduled rolloff, NOT verified cash: {m(data,"A24_R_TOTAL")-m(data,"AQ_R_TOTAL"):.6f}')
    print(f'Recognized fixed fees minus rolloff: {m(data,"AQ_LICENSE")-(m(data,"A24_R_TOTAL")-m(data,"AQ_R_TOTAL")):.6f}')
    print(f'Q1 expense excluding power/depreciation: {c.annual_direct_expense/4:.6f}; annual calibration: {c.annual_direct_expense:.6f}')
    print('FINITE AUSTIN DIAGNOSTIC: March 31, 2025 anchor; year-end timing; through 2029 only')
    for g,u in ((0,0),(.03,0),(.06,0),(.06,1)):
        case=replace(c,annual_escalation=g,annual_net_cash_correction=u)
        print(f'cost growth={g:.2%}; annual correction={u:.3f}; budget={budget(data,case):.9f}; total annual correction limit={correction_limit(data,case):.9f}')
    print(f'Zero-budget escalation: {escalation_limit(data,c):.9%}')
    for rate in (.08,.10,.12):
        print(f'Flat-cost rate {rate:.0%}: {budget(data,replace(c,rate=rate)):.9f}')
    print('Year | fees | direct-expense calibration | residual | present value')
    for p in finite_austin(data,c):
        print(f'{p.year} | {p.receipts:.6f} | {p.direct_expense:.6f} | {p.net:.6f} | {p.pv:.6f}')
    print(f'Undated later fees outside finite model: {m(data,"AQ_R_later"):.6f}')
    print(f'Equal-output tariff speedup threshold: {speedup_threshold(val(data,"P_A100","USD_per_node_hour"),val(data,"P_H100","USD_per_node_hour")):.9f}x')
    print(f'Portfolio deferred-revenue reconciliation: {m(data,"DEF_BEGIN")+m(data,"DEF_NEW")-m(data,"DEF_USED")-m(data,"DEF_NONCASH"):.6f}')
    print(f'Accounting, unit, status, boundary, numerical and invalid-input checks passed; {len(data)} records.')


def main() -> None:
    here=Path(__file__).resolve()
    default=here.with_name(here.name.replace('continuation-calculations.py','continuation-data.csv'))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=default)
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args()
    data=load_inputs(args.data)
    run_tests(data)
    print_results(data)
    if args.figure:
        render_figure(data,args.figure)


if __name__=='__main__':
    try:
        main()
    except (OSError,KeyError,TypeError,ValueError) as error:
        raise SystemExit(f'Calculation failed: {error}') from error
