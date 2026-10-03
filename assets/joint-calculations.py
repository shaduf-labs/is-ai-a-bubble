#!/usr/bin/env python3
"""Connected cash consistency, not a forecast or compliance certificate.

Python 3.10+, standard library for calculations/tests. Optional SVG needs matplotlib.
Run beside joint-data.csv, or a matching delivery-prefixed data file:
  python joint-calculations.py [--data joint-data.csv] [--figure joint-cash.svg]

The 2027–2030 operating path is the issuer's April 2026 ILLUSTRATION. Only its
financing schedule is replaced by the executed coupon and June assumed first
installment date. Full 2031 annual cash is never silently put before May maturity.
No live data, downloads, file modifications other than an explicitly requested figure.
"""
from __future__ import annotations
import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

DATA_NAME = 'joint-data.csv'
STATUSES = {'reported_actual','reported_inherited','reported_subsequent_event',
            'disclosed_future_schedule','issuer_illustration','issuer_estimate',
            'contractual','research_assumption'}

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    entity: str
    period: str
    source: str


def require(test: bool, message: str) -> None:
    if not test:
        raise ValueError(message)


def finite(x: float, name: str, *, nonnegative: bool = False) -> None:
    require(not isinstance(x,bool) and math.isfinite(x), f'{name}: finite number required')
    require(not nonnegative or x >= 0, f'{name}: negative value')


def close(a: float, b: float, *, atol: float = 1e-8) -> None:
    require(math.isclose(a,b,rel_tol=1e-10,abs_tol=atol), f'Identity failed: {a} != {b}')


def load_inputs(path: Path) -> dict[str, Input]:
    required = {'id','entity','metric','value','unit','status','period','source_id',
                'source_url','locator','notes'}
    out: dict[str, Input] = {}
    with path.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f)
        require(required.issubset(reader.fieldnames or []),'Missing input columns')
        for row in reader:
            require(None not in row,'Too many fields in ledger row')
            require(all(row[k] is not None and row[k].strip() for k in required),
                    'Missing ledger field')
            key=row['id']; require(key not in out,f'Duplicate ID: {key}')
            value=float(row['value']); finite(value,key)
            require(row['status'] in STATUSES,f'Unknown status: {key}')
            require(row['source_url'].startswith(('https://','report.md#')),f'Bad source: {key}')
            out[key]=Input(value,row['unit'],row['status'],row['entity'],row['period'],row['source_id'])
    require(bool(out),'Empty input ledger')
    return out


def val(d: Mapping[str,Input], key: str, unit: str='USD_million',
        status: str|None=None) -> float:
    rec=d[key]
    require(rec.unit==unit,f'Unit mismatch for {key}: {rec.unit} != {unit}')
    require(status is None or rec.status==status,f'Status mismatch for {key}')
    return rec.value


def actual_accounts(d: Mapping[str,Input]) -> dict[str,float]:
    """Sum disclosed cash accounts, NOT legal consolidation or AI-only operations."""
    out={}
    for issuer in ('CW','CS'):
        start=val(d,issuer+'_START'); end=val(d,issuer+'_END')
        ocf=val(d,issuer+'_OCF'); icf=val(d,issuer+'_ICF'); fcf=val(d,issuer+'_FCF')
        close(start+ocf+icf+fcf,end)
        close(val(d,issuer+'_UNRESTRICTED')+val(d,issuer+'_RESTRICTED_CURRENT')
              +val(d,issuer+'_RESTRICTED_NONCURRENT'),end)
        out[issuer+'_nonfinancing']=ocf+icf
    for item in ('START','OCF','ICF','FCF','END','UNRESTRICTED'):
        out[item]=sum(val(d,x+'_'+item) for x in ('CW','CS'))
    out['restricted']=out['END']-out['UNRESTRICTED']
    out['nonfinancing']=out['OCF']+out['ICF']
    out['cash_change']=out['END']-out['START']
    out['no_financing_fixed_uses']=out['START']+out['nonfinancing']
    close(out['START']+out['nonfinancing']+out['FCF'],out['END'])
    close(val(d,'CW_DEBT_NET')+val(d,'CW_EQUITY_NET')-val(d,'CW_REPAY')
          -val(d,'CW_CAPCALL')-val(d,'CW_FIN_OTHER'),val(d,'CW_FCF'))
    close(val(d,'CS_DEBT_GROSS')-val(d,'CS_BRIDGE_REPAY')-val(d,'CS_ISSUANCE_COSTS')
          -val(d,'CS_RSU_TAX')+val(d,'CS_FIN_OTHER'),val(d,'CS_FCF'))
    close(-val(d,'CS_PPE')-val(d,'CS_LAND')+val(d,'CS_ASSETSALE')
          -val(d,'CS_ICF_OTHER'),val(d,'CS_ICF'))
    out['specified_cash_capital']=val(d,'CW_PPE')+val(d,'CS_PPE')+val(d,'CS_LAND')
    out['advance_end']=val(d,'CS_ADV_START')+val(d,'CS_ADV_RECEIPT') \
        -val(d,'CS_ADV_EARNED')-val(d,'CS_ADV_NONCASH')
    close(out['advance_end'],val(d,'CS_ADV_END'))
    out['CS_nonpower_nondepreciation_expense']=val(d,'CS_H1_COLOC_COST') \
        -val(d,'CS_H1_POWER')-val(d,'CS_H1_DEPR')
    out['CW_sept_after_calls']=val(d,'CW_SEPT_NET')-val(d,'CW_SEPT_CALL')
    out['CW_sept_coupon']=val(d,'CW_SEPT_FACE')*val(d,'CW_SEPT_COUPON','fraction')
    return out


def site_scales(d: Mapping[str,Input]) -> dict[str,float]:
    sites=['AUSTIN','DENTON','DALTON1','DALTON4','MARBLE','MUSKOGEE']
    mw=sum(val(d,f'SITE_{s}_MW','MW_IT') for s in sites)
    annual=sum(val(d,f'SITE_{s}_MW','MW_IT')*1000*val(d,f'SITE_{s}_FEE','USD_per_kW_month')*12/1e6 for s in sites)
    eligible=mw-val(d,'SITE_AUSTIN_MW','MW_IT')
    return {'detailed_MW':mw,'base_annual_fee':annual,
            'non_Austin_credit_cap':eligible*val(d,'CREDIT_PER_MW','USD_million_per_MW'),
            'uncontributed_estimate':val(d,'PROJECT_CAPEX')-val(d,'PROJECT_CONTRIBUTED')}


def project_row(d: Mapping[str,Input], year: int) -> dict[str,float]:
    require(2026<=year<=2031,'Outside disclosed illustration')
    row={x:val(d,f'P_{x}_{year}',status='issuer_illustration')
         for x in ('REV','OPEX','NOI','OTHER','INTEREST','AMORT','LFCF','END_DEBT')}
    # Reported NOI, rather than an invented unrounded REV-OPEX, controls the model.
    row['rounding_residual']=row['REV']-row['OPEX']-row['NOI']
    row['pre_debt']=row['NOI']-row['OTHER']
    row['tenant_lower']=row['REV']-row['OTHER']
    row['tenant_upper']=row['REV']
    return row


@dataclass(frozen=True)
class DebtPayment:
    day: date
    opening_principal: float
    interest: float
    principal: float
    closing_principal: float
    @property
    def total(self) -> float:
        return self.interest+self.principal


def debt_calendar(d: Mapping[str,Input], first_installment: date=date(2029,11,15)) -> list[DebtPayment]:
    """Contract schedule on the June assumption. No optional redemption/new notes.

    November 2026 stub uses six 30-day months plus nine actual days (189/360).
    All later coupons are half-year. Stated dates are shown; nonbusiness-day
    settlement shifts do not earn additional interest under the indenture.
    """
    require(isinstance(first_installment,date),'Date required')
    require(first_installment in [date(y,m,15) for y in range(2027,2032) for m in (5,11) if date(y,m,15)<=date(2031,5,15)],
            'First installment must be an allowed semiannual payment date')
    face=val(d,'N_FACE'); rate=val(d,'N_COUPON','fraction'); ar=val(d,'N_AMORT_RATE','fraction')
    require(face>0 and 0<=rate<1 and 0<ar<=1,'Invalid note terms')
    days=[date(2026,11,15)]+[date(y,m,15) for y in range(2027,2031) for m in (5,11)]+[date(2031,5,15)]
    outstanding=face; result=[]
    for i,day in enumerate(days):
        interest=outstanding*rate*(189/360 if i==0 else .5)
        principal=outstanding if day==days[-1] else min(outstanding,face*ar/2 if day>=first_installment else 0)
        result.append(DebtPayment(day,outstanding,interest,principal,outstanding-principal))
        outstanding-=principal
    close(sum(p.principal for p in result),face)
    return result


def annual_test(d: Mapping[str,Input], first_installment: date=date(2029,11,15),
                shock_year: int|None=None, shock: float=0) -> list[dict[str,float]]:
    finite(shock,'net cash shock',nonnegative=True)
    payments=debt_calendar(d,first_installment)
    out=[]
    for y in range(2027,2031):
        p=project_row(d,y)
        interest=sum(x.interest for x in payments if x.day.year==y)
        principal=sum(x.principal for x in payments if x.day.year==y)
        net=p['pre_debt']-(shock if y==shock_year else 0)
        out.append(dict(year=y,pre_debt=net,interest=interest,principal=principal,
                        debt_service=interest+principal,residual=net-interest-principal))
    return out


def maturity_test(d: Mapping[str,Input], opening_cash: float,
                  early_cash: float, distributions: float=0,
                  first_installment: date=date(2029,11,15), extra_cost: float=0) -> dict[str,float]:
    """B + operating residual + pre-May cash + new net funding = final debt + payouts.

    B is an explicit FUTURE opening resource assumption. It is not June group cash.
    In this aggregate identity reserves move within B/cash, not new sources or costs.
    Distribution permission and intraperiod reserve tests remain outside this bound.
    """
    for k,x in [('opening',opening_cash),('distributions',distributions),('extra_cost',extra_cost)]:
        finite(x,k,nonnegative=True)
    finite(early_cash,'cash earned by maturity')
    annual=annual_test(d,first_installment)
    retained=sum(x['residual'] for x in annual)
    maturity=debt_calendar(d,first_installment)[-1]
    resources=opening_cash+retained+early_cash-distributions-extra_cost
    need=maturity.total-resources
    return dict(retained_before_payout=retained,principal=maturity.principal,
                final_interest=maturity.interest,final_payment=maturity.total,
                resources=resources,net_takeout_needed=max(0,need),signed_takeout=need,
                surplus=max(0,-need))


def annuity_factor(years: int, rate: float) -> float:
    require(not isinstance(years,bool) and isinstance(years,int) and years>0,'Positive integer term required')
    finite(rate,'rate',nonnegative=True)
    return sum((1+rate)**(-t) for t in range(1,years+1))


def refinance(net_needed: float, annual_cash: float, rate: float,
              years: int, fee: float) -> dict[str,float]:
    """Finite fully amortizing new debt. Closing fee charged ONCE.

    annual_cash is AFTER all future non-debt cash needs, not gross project NOI.
    This is a capacity test, not a loan commitment or forecast refinancing price.
    """
    finite(net_needed,'net need',nonnegative=True); finite(annual_cash,'cash',nonnegative=True)
    finite(fee,'fee',nonnegative=True); require(fee<1,'Fee must be below 100%')
    af=annuity_factor(years,rate)
    face=net_needed/(1-fee)
    service=face/af
    maximum=annual_cash*af*(1-fee)
    return dict(face=face,fee_cash=face*fee,annual_debt_service=service,
                annual_residual=annual_cash-service,maximum_net_advance=maximum,
                funding_margin=maximum-net_needed)


def split_payment(d: Mapping[str,Input],year: int,tenant_credit: float) -> dict[str,float]:
    """Identify a consistent split of OTHER into tenant repayments and other uses.

    This is an identification range, not permission for management to choose costs.
    Any other transfer hidden in OTHER requires reclassifying this particular bound.
    """
    p=project_row(d,year)
    finite(tenant_credit,'credit',nonnegative=True)
    require(tenant_credit<=p['OTHER'],'Credit exceeds disclosed combined line')
    tenant=p['REV']-tenant_credit
    other_uses=p['OTHER']-tenant_credit
    provider=tenant-p['OPEX']-other_uses-p['rounding_residual']
    close(provider,p['pre_debt'])
    return dict(tenant_net=tenant,provider_outside_uses=p['OPEX']+other_uses,
                provider_predebt=provider,rounding=p['rounding_residual'])


def run_tests(d: Mapping[str,Input]) -> None:
    a=actual_accounts(d); close(a['nonfinancing'],-12162.942)
    close(a['END'],9455.391);close(a['UNRESTRICTED'],7293.735)
    close(a['CW_sept_after_calls'],3570.8)
    close(sum(val(d,f'CS_LEASE_{x}') for x in ('2026','2027','2028','2029','2030','LATER')),val(d,'CS_LEASE_TOTAL'))
    # Annual original cells can be rounded independently. Never silently overwrite them.
    for y in range(2026,2032):
        p=project_row(d,y)
        require(abs(p['rounding_residual'])<=1.01,'Unexpected source rounding gap')
        require(abs(p['pre_debt']-p['INTEREST']-p['AMORT']-p['LFCF'])<=1.01,'Illustration does not reconcile within disclosed rounding')
        split_payment(d,y,0);split_payment(d,y,p['OTHER']);split_payment(d,y,p['OTHER']/2)
    c=debt_calendar(d)
    close(c[0].interest,134.26875)
    close(c[-1].principal,val(d,'CS_PRINCIPAL_LATER'))
    close(sum(p.principal for p in c if p.day.year==2029),val(d,'CS_PRINCIPAL_2029'))
    close(sum(p.principal for p in c if p.day.year==2030),val(d,'CS_PRINCIPAL_2030'))
    close(c[-1].total,2836.5665625)
    b=val(d,'A_OPENING');z=project_row(d,2031)['pre_debt']*val(d,'A_EARLY_SHARE','fraction')
    m=maturity_test(d,b,z);close(m['retained_before_payout'],350.8084375)
    close(m['net_takeout_needed'],1809.958125)
    close(maturity_test(d,b,z,distributions=50)['signed_takeout']-m['signed_takeout'],50)
    close(maturity_test(d,b+50,z)['signed_takeout']-m['signed_takeout'],-50)
    close(maturity_test(d,b,z+50)['signed_takeout']-m['signed_takeout'],-50)
    late=maturity_test(d,b,z,first_installment=date(2030,11,15))
    close(late['principal']-m['principal'],379.5)
    close(late['signed_takeout']-m['signed_takeout'],36.7640625)
    ref=refinance(m['net_takeout_needed'],600,.10,4,.02)
    close(ref['face']-ref['fee_cash'],m['net_takeout_needed'])
    close(ref['annual_debt_service']*annuity_factor(4,.10),ref['face'])
    require(ref['annual_residual']>0,'Favorable test should have a finite feasible cash path')
    require(refinance(m['net_takeout_needed'],450,.12,4,.02)['funding_margin']<0,'Adverse path must expose cash shortfall')
    for bad in [lambda: annuity_factor(0,.1),lambda: annuity_factor(True,.1),
                lambda: refinance(1,1,.1,4,1), lambda: refinance(-1,1,.1,4,0),
                lambda: split_payment(d,2027,302),lambda: maturity_test(d,-1,0),
                lambda: debt_calendar(d,date(2029,10,15)),lambda: finite(float('nan'),'bad')]:
        try:bad()
        except (ValueError,KeyError):pass
        else:raise ValueError('Expected domain rejection')


def render_figure(d: Mapping[str,Input], destination: Path) -> None:
    import matplotlib.pyplot as plt
    b=val(d,'A_OPENING');z=project_row(d,2031)['pre_debt']*val(d,'A_EARLY_SHARE','fraction')
    m=maturity_test(d,b,z);ret=m['retained_before_payout']
    payouts=[0,ret]
    comps=[[b,z,ret-p,maturity_test(d,b,z,p)['net_takeout_needed']] for p in payouts]
    labels=['Opening resources (assumed)','Cash by maturity (assumed)',
            '2027–2030 residual retained','New net funding / returned capital']
    fig,ax=plt.subplots(figsize=(12.4,6.6))
    left=[0.,0.]
    for i,label in enumerate(labels):
        widths=[comps[y][i] for y in range(2)]
        bars=ax.barh([1,0],widths,left=left,label=label,height=.42)
        for j,(bar,w) in enumerate(zip(bars,widths)):
            if w>0:
                ax.text(left[j]+w/2,bar.get_y()+bar.get_height()/2,f'{w:,.1f}',ha='center',va='center',fontsize=10)
        left=[left[j]+widths[j] for j in range(2)]
    ax.set_yticks([1,0],['Residual retained','Residual paid out'])
    ax.set_xlabel('USD millions needed for the May 15, 2031 payment')
    ax.set_xlim(0,m['final_payment']*1.05)
    ax.set_title('The same rent cash cannot fund both owner payouts and debt retirement',loc='left',pad=20,fontsize=14)
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.20),ncol=2,frameon=False,fontsize=9)
    ax.text(0,1.45,f'Final payment: {m["final_payment"]:,.1f} = principal {m["principal"]:,.1f} + final coupon {m["final_interest"]:,.1f}',fontsize=10)
    ax.set_ylim(-.5,1.8)
    fig.text(.08,.025,'Conditional hybrid: April issuer operating illustration; executed debt terms; June assumed amortization start.\n'
             'Opening resources of 344.8 and pre-maturity cash of 331.0 are assumptions, not current balances.\n'
             'Additional funding is a requirement, not a commitment or loss forecast. Reserve and distribution permissions remain separate.\n'
             'Sources and exact equations: chapter §§4–7, joint-data.csv, joint-calculations.py. No terminal sale value.',fontsize=9)
    fig.subplots_adjust(left=.17,right=.96,top=.86,bottom=.35)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Is AI a Bubble? Connected cash calculations'})
    plt.close(fig)


def main() -> None:
    here=Path(__file__).resolve().parent
    default=here/DATA_NAME
    if not default.exists():
        prefix=Path(__file__).name.removesuffix('joint-calculations.py')
        default=here/(prefix+DATA_NAME)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=default)
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args(); d=load_inputs(args.data); run_tests(d)
    print('Units: USD millions unless stated. Observations, issuer illustrations and assumptions remain separate.')
    print('\nACTUAL TWO-COMPANY ACCOUNTS')
    for k,v in actual_accounts(d).items():print(f'{k}: {v:,.6f}')
    print('\nCONTRACT SCALES (not current occupancy or achieved receipts)')
    for k,v in site_scales(d).items():print(f'{k}: {v:,.6f}')
    print('\nCONTRACTUAL NOTE PAYMENT CALENDAR ON JUNE FIRST-INSTALLMENT ASSUMPTION')
    for x in debt_calendar(d):print(f'{x.day}: opening {x.opening_principal:,.6f}; interest {x.interest:,.6f}; principal {x.principal:,.6f}; end {x.closing_principal:,.6f}')
    print('\nOPERATING ILLUSTRATION + EXECUTED DEBT: NOT A FORECAST')
    for x in annual_test(d):print(' '.join(f'{k}={v:,.6f}' for k,v in x.items()))
    print('\nTENANT CASH RANGE: excludes additional construction/GPU costs')
    for y in range(2027,2031):
        p=project_row(d,y);print(f'{y}: {p["tenant_lower"]:,.3f} to {p["tenant_upper"]:,.3f}; provider predebt {p["pre_debt"]:,.3f}')
    b=val(d,'A_OPENING');z=project_row(d,2031)['pre_debt']*val(d,'A_EARLY_SHARE','fraction')
    m=maturity_test(d,b,z)
    print('\nMATURITY TEST (explicit future opening/timing assumptions)')
    for k,v in m.items():print(f'{k}: {v:,.9f}')
    print('All residual paid out:',maturity_test(d,b,z,m['retained_before_payout']))
    print('First installment delayed a year:',maturity_test(d,b,z,first_installment=date(2030,11,15)))
    for name,rate,cash in [('Favorable',val(d,'A_REF_RATE','fraction'),val(d,'A_REF_CASH','USD_million_per_year')),
                           ('Adverse',val(d,'A_ADVERSE_RATE','fraction'),val(d,'A_ADVERSE_CASH','USD_million_per_year'))]:
        print(name,refinance(m['net_takeout_needed'],cash,rate,int(val(d,'A_REF_YEARS','years')),val(d,'A_REF_COST','fraction')))
    print(f'All internal checks passed; {len(d)} input records read.')
    if args.figure:render_figure(d,args.figure)

if __name__=='__main__':
    try:main()
    except (OSError,KeyError,ValueError) as e:
        raise SystemExit(f'Calculation failed: {e}') from e
