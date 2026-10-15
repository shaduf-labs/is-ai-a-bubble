#!/usr/bin/env python3
"""Ownership economics: dated claim bridges and funded continuing-business requirements.

Standard-library only. Run beside data.csv or the matching CSV,
or pass --data PATH. Optional --json emits the numerical results to stdout.
Money is USD millions; share counts are millions. Scenarios are NOT probabilities,
price targets, compliance tests, or forecasts. See the accompanying reader investigation for source boundaries.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

SCHEMA = ['id','entity','metric','value','unit','period','status','source_id','source_url','locator','note']
STATUSES = {'reported','market_reference','issuer_forecast','announced_authorization','research_assumption'}
SCENARIOS = ('N_RENEW','N_STRONG','N_EROSION','F_RENEW','F_STRONG','F_EROSION')

class Ledger:
    def __init__(self, path: Path):
        self.rows: dict[str,dict[str,str]] = {}
        with path.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != SCHEMA:
                raise ValueError('CSV header does not match the documented schema')
            for line,row in enumerate(reader,2):
                if None in row or any(row.get(k) is None for k in SCHEMA):
                    raise ValueError(f'CSV line {line}: wrong number of columns')
                if any(not row[k].strip() for k in SCHEMA if k != 'note'):
                    raise ValueError(f'CSV line {line}: required field is empty')
                key=row['id']
                if key in self.rows:
                    raise ValueError(f'duplicate input {key}')
                if row['status'] not in STATUSES:
                    raise ValueError(f'{key}: unsupported evidence status')
                try: value=Decimal(row['value'])
                except InvalidOperation as exc: raise ValueError(f'{key}: not a decimal') from exc
                if not value.is_finite(): raise ValueError(f'{key}: non-finite input')
                self.rows[key]=row
        if not self.rows: raise ValueError('empty input ledger')
        for key,row in self.rows.items():
            if row['unit'] not in {'USD_million','USD_per_share','million_shares','fraction','years','count','GW'}:
                raise ValueError(f'{key}: unsupported unit')
            if row['unit']=='years' and self.d(key)!=self.d(key).to_integral_value():
                raise ValueError(f'{key}: year parameter must be an integer')
        # Core claim units are a contract: an accepted unit name is not enough.
        expected = {
            'N_PRICE':'USD_per_share','F_PRICE':'USD_per_share','F_STRIKE':'USD_per_share',
            'N_SHARES':'million_shares','N_AWARDS':'million_shares',
            'F_A_SHARES':'million_shares','F_B_SHARES':'million_shares',
            'F_AWARDS':'million_shares','F_OPTIONS':'million_shares',
            'N_Q_REV':'USD_million','F_Q_REV':'USD_million',
            'N_REQUIRED_CASH':'USD_million','F_REQUIRED_CASH':'USD_million',
            'N_INVESTMENT_CREDIT':'fraction','RATE':'fraction','TAX':'fraction'}
        for key,unit in expected.items():
            self.d(key)  # Missing required keys receive the same clear error.
            if self.rows[key]['unit'] != unit:
                raise ValueError(f'{key}: expected unit {unit}')
            if self.d(key) < 0:
                raise ValueError(f'{key}: negative claim/reference parameter')
        for key in ('N_PRICE','F_PRICE','N_SHARES','N_Q_REV','F_Q_REV'):
            if self.d(key) <= 0: raise ValueError(f'{key}: must be positive')
        for key in ('N_REQUIRED_CASH','F_REQUIRED_CASH','N_INVESTMENT_CREDIT','RATE','TAX'):
            self.assumption(key)
        if self.d('N_INVESTMENT_CREDIT') > 1:
            raise ValueError('investment-credit fraction must be between zero and one')
    def d(self,key: str) -> Decimal:
        try: return Decimal(self.rows[key]['value'])
        except KeyError as exc: raise ValueError(f'missing input {key}') from exc
    def v(self,key: str) -> float: return float(self.d(key))
    def assumption(self,key: str) -> float:
        if self.rows.get(key,{}).get('status') != 'research_assumption':
            raise ValueError(f'{key}: scenario input must be marked research_assumption')
        return self.v(key)

@dataclass(frozen=True)
class Case:
    name: str
    revenue0: float
    growth: float
    terminal_growth: float
    rate: float
    tax: float
    start_costs: tuple[float,...]
    end_costs: tuple[float,...]
    cost_fade: int
    fixed_growth_capital: float
    working_growth_capital: float
    extra_renewal: float
    da_ratio: float
    first_growth: float | None = None
    opening_extra: float = 0.0
    def validate(self) -> None:
        scalar=(self.revenue0,self.growth,self.terminal_growth,self.rate,self.tax,
                self.fixed_growth_capital,self.working_growth_capital,self.extra_renewal,
                self.da_ratio,self.opening_extra,*self.start_costs,*self.end_costs)
        if not all(math.isfinite(v) for v in scalar): raise ValueError('non-finite scenario')
        if self.revenue0<=0 or self.rate<=self.terminal_growth or self.rate<=0:
            raise ValueError('positive revenue and r > g_terminal are required')
        if self.growth<=-1 or self.terminal_growth<0 or not 0<=self.tax<=1:
            raise ValueError('invalid growth or tax')
        if self.first_growth is not None and (not math.isfinite(self.first_growth) or self.first_growth<=-1):
            raise ValueError('invalid first-year growth')
        if self.cost_fade<2 or len(self.start_costs)!=len(self.end_costs):
            raise ValueError('invalid cost interpolation')
        if not all(0<=v<=1 for v in (*self.start_costs,*self.end_costs)):
            raise ValueError('cost shares must be between zero and one')
        if min(self.fixed_growth_capital,self.working_growth_capital,self.extra_renewal,self.da_ratio,self.opening_extra)<0:
            raise ValueError('investment parameters cannot be negative')

def load_case(L: Ledger,prefix: str) -> Case:
    n=prefix[0]; names=('COGS','RD','SGA','GRANT') if n=='N' else ('COGS','RD','SM','GA','GRANT')
    a=lambda key:L.assumption(prefix+'_'+key)
    return Case(prefix,4*L.v(n+'_Q_REV'),a('G'),a('TG'),L.assumption('RATE'),L.assumption('TAX'),
                tuple(a(k+'_START') for k in names),tuple(a(k+'_END') for k in names),int(a('COST_FADE')),
                a('KF'),a('KW'),a('EXTRA'),L.assumption(n+'_DA_RATIO'),
                a('SHOCK') if prefix+'_SHOCK' in L.rows else None)

def trajectory(c: Case,years: int=30) -> list[dict[str,float]]:
    c.validate()
    if years<11: raise ValueError('at least eleven years needed for terminal comparison')
    previous=c.revenue0; rows=[]
    for t in range(1,years+1):
        g=c.growth if t<=5 else (c.growth+(c.terminal_growth-c.growth)*(t-5)/5 if t<=10 else c.terminal_growth)
        if t==1 and c.first_growth is not None: g=c.first_growth
        revenue=previous*(1+g)
        fraction=min(1.0,(t-1)/(c.cost_fade-1))
        costs=tuple(a+(b-a)*fraction for a,b in zip(c.start_costs,c.end_costs))
        ebit=revenue*(1-sum(costs))
        tax=max(ebit,0)*c.tax  # No automatic refund/negative cash tax on modeled losses.
        da=revenue*c.da_ratio
        maintenance=da+revenue*c.extra_renewal
        increment=max(revenue-previous,0)  # Decline does not promise liquidatable working capital.
        fixed=increment*c.fixed_growth_capital
        working=increment*c.working_growth_capital
        extra=c.opening_extra if t==1 else 0.0
        free=ebit-tax+da-maintenance-fixed-working-extra
        rows.append(dict(year=t,revenue=revenue,growth=g,economic_ebit=ebit,tax=tax,da=da,
                         maintenance=maintenance,fixed_growth=fixed,working_growth=working,
                         new_grant_cost=revenue*costs[-1],free_cash=free,
                         retained_margin=free/revenue,pv=free/(1+c.rate)**t,
                         gross_fixed_investment=maintenance+fixed,opening_extra=extra))
        previous=revenue
    return rows

def value(c: Case) -> dict:
    rows=trajectory(c)
    pv10=sum(x['pv'] for x in rows[:10]); pv30=sum(x['pv'] for x in rows)
    terminal=rows[10]['free_cash']/(c.rate-c.terminal_growth)/(1+c.rate)**10
    total=pv10+terminal
    cumulative=0.0; low=0.0
    for x in rows:
        cumulative+=x['free_cash'];low=min(low,cumulative)
    return dict(operating_value=total,pv_first10=pv10,pv_first30=pv30,
                pv_after10=terminal,pv_after30=total-pv30,
                after10_fraction=terminal/total if total else None,
                after30_fraction=(total-pv30)/total if total else None,
                cumulative_funding_need=-low,rows=rows)

def root(fn: Callable[[float],float],lo: float,hi: float,iterations: int=100) -> float:
    flo=fn(lo);fhi=fn(hi)
    if not all(map(math.isfinite,(flo,fhi))) or flo*fhi>0:
        raise ValueError('root not bracketed; no price-compatible path in this interval')
    if flo==0:return lo
    if fhi==0:return hi
    for _ in range(iterations):
        mid=(lo+hi)/2;fm=fn(mid)
        if fm==0:return mid
        if flo*fm<=0:hi=mid
        else:lo=mid;flo=fm
    return (lo+hi)/2

def required_growth(c: Case,target: float,finite: int|None=None) -> float:
    if not math.isfinite(target) or target <= 0 or finite not in (None,10,30):
        raise ValueError('positive finite claim and finite window 10 or 30 required')
    def difference(g: float) -> float:
        result=value(replace(c,growth=g))
        return result['operating_value' if finite is None else f'pv_first{finite}']-target
    return root(difference,0.0,1.0)

def bridges(L: Ledger) -> dict:
    nv_credit=L.d('N_CASH')+L.d('N_LIQUID_DEBT')-L.d('N_REQUIRED_CASH')+L.d('N_INVESTMENT_CREDIT')*(L.d('N_PUBLIC_EQUITY')+L.d('N_PRIVATE_TOTAL'))-L.d('N_DEBT_FACE')-L.d('N_GROQ_PAYABLE')-L.d('N_LEGACY_TAX')
    ns=L.d('N_SHARES')+L.d('N_AWARDS')
    fs=L.d('F_A_SHARES')+L.d('F_B_SHARES')+L.d('F_AWARDS')
    fr_credit=L.d('F_CASH')+L.d('F_MARKETABLE')-L.d('F_REQUIRED_CASH')-L.d('F_ACQ_HOLDBACK')
    optlo=L.d('F_OPTIONS')*max(L.d('F_PRICE')-L.d('F_STRIKE'),Decimal(0))
    opthi=L.d('F_OPTIONS')*L.d('F_PRICE')
    result={
      'N':dict(net_nonoperating_credit=nv_credit,claim_shares=ns,
               basic_equity_reference=L.d('N_PRICE')*L.d('N_SHARES'),
               required_operating_value=ns*L.d('N_PRICE')-nv_credit),
      'F':dict(net_nonoperating_credit=fr_credit,claim_shares=fs+L.d('F_OPTIONS'),
               shares_without_options=fs,option_value_lower_bound=optlo,option_value_upper_bound=opthi,
               basic_equity_reference=L.d('F_PRICE')*(L.d('F_A_SHARES')+L.d('F_B_SHARES')),
               required_operating_value=fs*L.d('F_PRICE')+opthi-fr_credit,
               required_operating_value_lower=fs*L.d('F_PRICE')+optlo-fr_credit)}
    return {k:{j:float(v) for j,v in r.items()} for k,r in result.items()}

def repurchase_effect(mark: float,transaction_price: float,shares: float) -> float:
    if min(mark,transaction_price,shares)<0:raise ValueError('negative transaction argument')
    return (transaction_price-mark)*shares

def results(L: Ledger) -> dict:
    B=bridges(L);cases={};rate_grid={};sensitivity={}
    for name in SCENARIOS:
        c=load_case(L,name);n=name[0];v=value(c);credit=B[n]['net_nonoperating_credit'];den=B[n]['claim_shares']
        v['conditional_common_equivalent']=(v['operating_value']+credit)/den
        v['finite10_common_equivalent']=(v['pv_first10']+credit)/den
        v['finite30_common_equivalent']=(v['pv_first30']+credit)/den
        cases[name]=v
        if not name.endswith('EROSION'):
            req=required_growth(c,B[n]['required_operating_value']);rr=value(replace(c,growth=req))
            v['required_growth']=req
            v['required_revenue5']=rr['rows'][4]['revenue'];v['required_revenue10']=rr['rows'][9]['revenue']
            v['required_cash10']=rr['rows'][9]['free_cash']
            v['required_after10_fraction']=rr['after10_fraction']
            v['required_growth_finite10']=required_growth(c,B[n]['required_operating_value'],10)
            v['required_growth_finite30']=required_growth(c,B[n]['required_operating_value'],30)
    for name in ('N_RENEW','F_RENEW'):
        c=load_case(L,name);target=B[name[0]]['required_operating_value']
        rate_grid[name]={f'{r:.2f}':{f'{g:.2f}':required_growth(replace(c,rate=r,terminal_growth=g),target) for g in (0,.02,.03,.04)} for r in (.09,.11,.13)}
        sensitivity[name]={}
        for label,alt in [('tax15',replace(c,tax=.15)),('tax25',replace(c,tax=.25)),
                          ('double_growth_capital',replace(c,fixed_growth_capital=c.fixed_growth_capital*2,working_growth_capital=c.working_growth_capital*2)),
                          ('extra_renewal_plus2pp',replace(c,extra_renewal=c.extra_renewal+.02)),
                          ('H1_annualized_scale',replace(c,revenue0=2*L.v(name[0]+'_H1_REV')))]:
            sensitivity[name][label]=dict(required_growth=required_growth(alt,target),operating_value=value(alt)['operating_value'])
    f=load_case(L,'F_RENEW');target=B['F']['required_operating_value']
    def grant_case(x: float) -> Case:return replace(f,end_costs=f.end_costs[:-1]+(x,))
    grant_needed=root(lambda x:value(grant_case(x))['operating_value']-target,0,.30)
    annual_grant_observed=L.v('F_NEW_GRANTS')*L.v('F_GRANT_FAIR')/f.revenue0
    high_grant=replace(f,start_costs=f.start_costs[:-1]+(annual_grant_observed,),end_costs=f.end_costs[:-1]+(annual_grant_observed,))
    r=result_exact(L)
    extra_claims={}
    for name,us in [('N_RENEW',(0,1000,5000)),('F_RENEW',(0,25,100,350))]:
        c=load_case(L,name);target=B[name[0]]['required_operating_value']
        extra_claims[name]={str(u):required_growth(c,target+u) for u in us}
    asset_sens={}
    n=load_case(L,'N_RENEW');f=load_case(L,'F_RENEW')
    for credit_fraction in (.5,.8,1.):
        delta=(credit_fraction-L.v('N_INVESTMENT_CREDIT'))*(L.v('N_PUBLIC_EQUITY')+L.v('N_PRIVATE_TOTAL'))
        asset_sens['N_investment_credit_'+str(credit_fraction)]=required_growth(n,B['N']['required_operating_value']-delta)
    for cash in (0.,20000.,40000.):
        asset_sens['N_required_cash_'+str(cash)]=required_growth(n,B['N']['required_operating_value']+cash-L.v('N_REQUIRED_CASH'))
    for cash in (100.,150.,250.):
        asset_sens['F_required_cash_'+str(cash)]=required_growth(f,B['F']['required_operating_value']+cash-L.v('F_REQUIRED_CASH'))
    asset_sens['F_full_DTA_face_credit_upper_diagnostic']=required_growth(f,B['F']['required_operating_value']-L.v('F_DTA'))
    resource_checks={}
    for name in ('N_RENEW','F_RENEW','F_STRONG'):
        c=load_case(L,name);v=value(c);rr=v['rows']
        def expenses(t):
            w=min(1,(t-1)/(c.cost_fade-1));return tuple(a+(b-a)*w for a,b in zip(c.start_costs,c.end_costs))
        resource_checks[name]=dict(year5_rd=rr[4]['revenue']*expenses(5)[1],
            year5_distribution=rr[4]['revenue']*expenses(5)[2],
            year5_new_grants=rr[4]['new_grant_cost'],year5_gross_fixed=rr[4]['gross_fixed_investment'],
            year10_revenue_multiple=rr[9]['revenue']/c.revenue0,
            year10_quantity_multiple_if_price_declines10=rr[9]['revenue']/c.revenue0/(.9**10),
            cumulative_10y_RD=sum(x['revenue']*expenses(int(x['year']))[1] for x in rr[:10]))
    return dict(units='USD millions and million shares; annual nominal scenarios',bridges=B,cases=cases,
                rate_growth_grid=rate_grid,sensitivity=sensitivity,exact_diagnostics=r,extra_claims=extra_claims,asset_sensitivity=asset_sens,resource_checks=resource_checks,
                freshworks_grant_boundary=dict(required_mature_new_grant_share=grant_needed,
                  implied_mature_economic_operating_margin=1-sum(grant_case(grant_needed).end_costs),
                  annual_h1_gross_grant_share=annual_grant_observed,
                  high_grant_operating_value=value(high_grant)['operating_value'],
                  high_grant_common_equivalent=(value(high_grant)['operating_value']+B['F']['net_nonoperating_credit'])/B['F']['claim_shares']))

def result_exact(L: Ledger) -> dict:
    d=L.d
    n_grant=d('N_NEW_GRANTS')*d('N_GRANT_FAIR');f_grant=d('F_NEW_GRANTS')*d('F_GRANT_FAIR')
    n_wc=sum((d(k) for k in ('N_WC_AR','N_WC_INV','N_WC_PREPAY','N_WC_AP','N_WC_ACCR','N_WC_LONG')),Decimal(0))
    f_wc=sum((d(k) for k in ('F_WC_AR','F_WC_DCA','F_WC_PREPAY','F_WC_AP','F_WC_ACCR','F_WC_DR','F_WC_LEASE')),Decimal(0))
    n_cfo=d('N_H1_NI')+d('N_H1_SBC')+d('N_H1_DA')+d('N_H1_DT')-d('N_H1_EQUITY_GAIN')+d('N_H1_OTHER')+n_wc
    f_cfo=sum((d(k) for k in ('F_H1_NI','F_H1_SBC','F_H1_DA','F_H1_DCA_AMORT','F_H1_LEASE_NONCASH','F_H1_DISCOUNT','F_H1_DT','F_H1_OTHER')),Decimal(0))+f_wc
    collections=d('N_CASH_GATE_COLLECTIONS');cash_opex=2*(d('N_Q_RD')+d('N_Q_SGA')-d('N_Q_RD_SBC')-d('N_Q_SGA_SBC'))
    tax=2*d('N_Q_OI')*d('N_CASH_GATE_TAX')
    gate=d('N_CASH')+d('N_LIQUID_DEBT')+collections-d('N_SUPPLY_H2')-cash_opex-tax-d('N_CAPEX_H2')-d('N_NEW_EQUITY_H2')-d('N_CASH_GATE_DIVIDEND')-d('N_CASH_GATE_EXTRA_BUFFER')-n_grant
    # Gate leaves all debt-service, additional WC, fees/other cash uses in the residual.
    # Compensation charged as a cash-equivalent replacement budget, not forecast cash settlement.
    vals=dict(N_H1_CFO_reconstructed=n_cfo,F_H1_CFO_reconstructed=f_cfo,N_H1_signed_WC=n_wc,F_H1_signed_WC=f_wc,
       N_H1_end_cash=d('N_BEGIN_CASH')+n_cfo+d('N_H1_CFI')+d('N_H1_CFF'),
       F_H1_end_cash_all=d('F_BEGIN_CASH_ALL')+f_cfo+d('F_H1_CFI')+d('F_H1_CFF')+d('F_FX'),
       N_after_cash_capex=d('N_H1_CFO')-d('N_H1_CAPEX'),
       N_after_cash_asset_and_license_and_recognized_SBC=d('N_H1_CFO')-d('N_H1_CAPEX')-d('N_ASSET_PRINCIPAL')-d('N_GROQ_CASH')-d('N_H1_SBC'),
       F_after_cash_capex_software=d('F_H1_CFO')-d('F_H1_CAPEX')-d('F_H1_SOFTWARE'),
       F_after_capital_and_all_recognized_SBC=d('F_H1_CFO')-d('F_H1_CAPEX')-d('F_H1_SOFTWARE')-d('F_H1_SBC')-d('F_CAPITAL_SBC'),
       N_H1_gross_grant_value=n_grant,F_H1_gross_grant_value=f_grant,
       N_annualized_grant_fraction=2*n_grant/(4*d('N_Q_REV')),
       F_acquisition_unallocated_bridge=d('F_ACQ_PRICE')-d('F_ACQ_CASH_ACQUIRED')-d('F_ACQ_HOLDBACK')-d('F_ACQ_CASH'),
       N_supply_vs_25pct_recognition_gap=d('N_SUPPLY_H2')-collections*Decimal('.25'),
       N_conditional_gate_before_debt_service_and_other_uses=gate,
       N_gate_after_60bn_distribution_before_other_uses=gate-d('N_CASH_GATE_BUYBACK'),
       N_fixed_share_repricing=(d('N_PRICE')-d('N_OLD_PRICE'))*d('N_SHARES'),
       F_fixed_share_repricing=(d('F_PRICE')-d('F_OLD_PRICE'))*(d('F_A_SHARES')+d('F_B_SHARES')))
    return {k:float(v) for k,v in vals.items()}

def tests(L: Ledger,R: dict) -> int:
    count=0
    def check(x: bool,message: str) -> None:
        nonlocal count
        if not x:raise AssertionError(message)
        count+=1
    def close(a:float,b:float,message:str) -> None:check(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),message)
    E=R['exact_diagnostics']
    close(E['N_H1_CFO_reconstructed'],L.v('N_H1_CFO'),'N cash reconciliation')
    close(E['F_H1_CFO_reconstructed'],L.v('F_H1_CFO'),'F cash reconciliation')
    close(E['N_H1_end_cash'],L.v('N_CASH'),'N end cash')
    close(E['F_H1_end_cash_all'],L.v('F_END_CASH_ALL'),'F end cash')
    close(E['F_H1_signed_WC'],-4.059,'preserved sign correction')
    close(E['F_acquisition_unallocated_bridge'],18.432,'unallocated is not zero')
    for name in SCENARIOS:
        c=load_case(L,name);v=R['cases'][name]
        close(v['operating_value'],v['pv_first10']+v['pv_after10'],'PV identity')
        close(v['operating_value'],v['pv_first30']+v['pv_after30'],'finite window identity')
        for x in v['rows']:
            close(x['free_cash'],x['economic_ebit']-x['tax']+x['da']-x['maintenance']-x['fixed_growth']-x['working_growth']-x['opening_extra'],'paid costs identity')
            check(x['gross_fixed_investment']>=x['da'],'maintenance not free')
        # Changing DA and equal maintenance cancels; no inconsistent lease/capex convention.
        close(value(replace(c,da_ratio=c.da_ratio+.01))['operating_value'],v['operating_value'],'DA maintenance conservation')
        if 'required_growth' in v:
            close(value(replace(c,growth=v['required_growth']))['operating_value'],R['bridges'][name[0]]['required_operating_value'],'root reprices claim')
    rng=random.Random(38)
    for _ in range(200):
        c=load_case(L,'N_RENEW' if rng.random()<.5 else 'F_RENEW')
        c=replace(c,growth=rng.uniform(.05,.35),rate=rng.uniform(.08,.16),terminal_growth=.02)
        v=value(c)['operating_value']
        check(value(replace(c,extra_renewal=c.extra_renewal+.01))['operating_value']<v,'renewal cost monotonicity')
        check(value(replace(c,rate=c.rate+.01))['operating_value']<v,'discount-rate monotonicity')
        p=rng.uniform(2,300);a=rng.uniform(2,300);q=rng.uniform(.1,100);shares=1000.;cash=100000.
        close((p*(shares-q)-(cash-a*q))-(p*shares-cash),repurchase_effect(p,a,q),'repurchase cash/claim conservation')
        close(repurchase_effect(p,p,q),0,'fair-price capital recycling')
    for bad in (replace(load_case(L,'N_RENEW'),rate=.01),replace(load_case(L,'N_RENEW'),growth=-1),
                replace(load_case(L,'N_RENEW'),tax=1.1),replace(load_case(L,'N_RENEW'),extra_renewal=-.1),
                replace(load_case(L,'F_RENEW'),first_growth=float('nan')),
                replace(load_case(L,'F_RENEW'),start_costs=(-.1,)),replace(load_case(L,'F_RENEW'),cost_fade=1)):
        try:value(bad)
        except ValueError:count+=1
        else:raise AssertionError('invalid scenario accepted')
    return count

def locate_data(explicit: str|None) -> Path:
    if explicit:return Path(explicit)
    here=Path(__file__).resolve()
    candidates=[here.with_name(here.name.replace('calculations.py','data.csv')),here.with_name('data.csv')]
    for p in candidates:
        if p.is_file():return p
    raise ValueError('data.csv not found; pass --data PATH')

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data');p.add_argument('--json',action='store_true');args=p.parse_args()
    try:
        L=Ledger(locate_data(args.data));R=results(L);R['checks_passed']=tests(L,R);R['input_rows']=len(L.rows)
        if args.json: print(json.dumps(R,indent=2,allow_nan=False))
        else:
            print(f"Inputs: {len(L.rows)}; checks passed: {R['checks_passed']}")
            print('USD millions; no probability weights or trade recommendations.\nCLAIM BRIDGES')
            print(json.dumps(R['bridges'],indent=2))
            print('\nSCENARIOS: operating value / conditional common-equivalent / required first-five-year growth')
            for name,v in R['cases'].items():
                print(name,round(v['operating_value'],6),round(v['conditional_common_equivalent'],6),v.get('required_growth','not solved for erosion case'))
            for section in ('rate_growth_grid','freshworks_grant_boundary','exact_diagnostics','sensitivity','extra_claims','asset_sensitivity','resource_checks'):
                print('\n'+section.upper());print(json.dumps(R[section],indent=2))
        return 0
    except (ValueError,OSError,AssertionError) as exc:
        print(f'Error: {exc}',file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
