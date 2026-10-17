#!/usr/bin/env python3
"""Recurring business and owner cash: offline, source-scoped reconciliations.

Run beside owner-cash-data.csv (matching prefixed names also work):
    python owner-cash-calculations.py [--data PATH] [--check-only]

Only Python's standard library is required. No network requests, trades or changes
to input files are made. Validation uses temporary test files; no valuation model is performed. All arithmetic uses Decimal. Printed financial
amounts are USD millions, inventories are millions of units, and ratios are
percentages. Gross award units are NOT fair-valued fully diluted shares.

The cash-neutralization comparison is an explicit allocation convention using
rounded historical repurchase prices, not a forecast or observed repurchase
purpose. Opening awards are included once; recognized SBC is not subtracted
again in that cash/claim convention. See the recurring-business-and-owner-cash reader chapter for interpretation limits.
"""
from __future__ import annotations
import argparse
import csv
import json
import random
import sys
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path
from typing import Any

getcontext().prec = 36
D = Decimal
ZERO = D(0)
FIELDS = ('id','company','period','metric','value','unit','status','source_id',
          'source_url','locator','inspection_date','note','period_start','period_end')
SOURCES = {
 'F23':'https://www.sec.gov/Archives/edgar/data/1544522/000154452224000012/frsh-20231231.htm',
 'F24':'https://www.sec.gov/Archives/edgar/data/1544522/000154452225000010/frsh-20241231.htm',
 'F25':'https://www.sec.gov/Archives/edgar/data/1544522/000154452226000036/frsh-20251231.htm',
 'F26H1':'https://www.sec.gov/Archives/edgar/data/1544522/000154452226000137/frsh-20260630.htm',
 'FR25':'https://ir.freshworks.com/news/news-details/2026/Freshworks-Reports-Fourth-Quarter-and-Full-Year-2025-Results/default.aspx',
 'FR26':'https://ir.freshworks.com/news/news-details/2026/Freshworks-Reports-Record-Second-Quarter-2026-Results/default.aspx',
 'S26':'https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm',
 'S27H1':'https://www.sec.gov/Archives/edgar/data/1108524/000110852426000190/crm-20260731.htm',
}
PERIODS = {**{f'CY{y}':(f'{y}-01-01',f'{y}-12-31') for y in range(2021,2026)},
 **{f'FY{y}':(f'{y-1}-02-01',f'{y}-01-31') for y in range(2024,2027)},
 'H1_2025':('2025-01-01','2025-06-30'), 'H1_2026':('2026-01-01','2026-06-30'),
 'H1_FY2027':('2026-02-01','2026-07-31')}
UNITS = {'USD_m','shares_m','USD_per_share','percent','count'}

class Ledger:
    """Reject missing numbers rather than replacing them with zero."""
    def __init__(self, path: Path):
        self.rows: dict[tuple[str,str,str],dict[str,str]] = {}
        self.values: dict[tuple[str,str,str],Decimal] = {}
        with Path(path).open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError('CSV schema does not match the supplied ledger')
            for line, row in enumerate(reader, 2):
                if None in row or any(row[k] is None for k in FIELDS):
                    raise ValueError(f'Row {line}: short or long row')
                if any(not row[k].strip() for k in FIELDS if k != 'note'):
                    raise ValueError(f'Row {line}: blank required field')
                key = (row['company'],row['period'],row['metric'])
                if key in self.rows or row['id'] != '_'.join(key):
                    raise ValueError(f'Row {line}: duplicate or inconsistent identity')
                if row['company'] not in {'FRSH','CRM'} or row['period'] not in PERIODS:
                    raise ValueError(f'Row {line}: unknown company or period')
                if (row['period_start'],row['period_end']) != PERIODS[row['period']]:
                    raise ValueError(f'Row {line}: inconsistent observation window')
                for k in ('inspection_date','period_start','period_end'):
                    date.fromisoformat(row[k])
                if row['inspection_date'] != '2026-10-17':
                    raise ValueError(f'Row {line}: unexpected inspection date')
                if row['unit'] not in UNITS:
                    raise ValueError(f'Row {line}: unknown unit')
                if SOURCES.get(row['source_id']) != row['source_url']:
                    raise ValueError(f'Row {line}: source ID/URL mismatch')
                expected_status = 'reported_indexed' if row['source_id']=='S27H1' else 'reported'
                if row['status'] != expected_status:
                    raise ValueError(f'Row {line}: unsupported evidence status')
                try:
                    v = D(row['value'])
                except InvalidOperation as exc:
                    raise ValueError(f'Row {line}: invalid number') from exc
                if not v.is_finite():
                    raise ValueError(f'Row {line}: non-finite value')
                if row['unit'] in {'shares_m','USD_per_share','percent','count'} and v < 0:
                    raise ValueError(f'Row {line}: negative inventory, price or count')
                if row['unit']=='count' and v != v.to_integral_value():
                    raise ValueError(f'Row {line}: fractional customer count')
                self.rows[key], self.values[key] = row, v
        if not self.rows:
            raise ValueError('Empty ledger')

    def get(self,c: str,p: str,m: str,unit: str='USD_m') -> Decimal:
        key = (c,p,m)
        if key not in self.rows:
            raise ValueError(f'Missing required observation: {key}')
        if self.rows[key]['unit'] != unit:
            raise ValueError(f'Unit mismatch for {key}: expected {unit}')
        return self.values[key]

    def total(self,c: str,p: str,metrics: tuple[str,...],unit: str='USD_m') -> Decimal:
        return sum((self.get(c,p,m,unit) for m in metrics), ZERO)

def pct(a: Decimal,b: Decimal) -> Decimal:
    if b <= 0: raise ValueError('Percentage denominator must be positive')
    return 100*a/b

def neutralization_room(fcf: Decimal, employee_receipts: Decimal, withholding: Decimal,
                        acquisition: Decimal, units: Decimal, price: Decimal,
                        owner_distribution: Decimal=ZERO, reserve: Decimal=ZERO) -> Decimal:
    """Consistent gross-inventory cash convention, NOT an expected award valuation."""
    if any(not x.is_finite() for x in (fcf,employee_receipts,withholding,acquisition,units,price,owner_distribution,reserve)):
        raise ValueError('Non-finite resource input')
    if min(employee_receipts,withholding,acquisition,price,owner_distribution,reserve) < 0:
        raise ValueError('Negative payment, price or distribution assumption')
    return fcf+employee_receipts-withholding-acquisition-price*max(units,ZERO)-owner_distribution-reserve

def operating(L: Ledger,c: str,p: str) -> dict[str,Decimal]:
    v=lambda m:L.get(c,p,m)
    rev,cr=v('revenue'),v('cost_revenue')
    # 2021–22 statement has no separate restructuring row; no missing cost is imputed.
    expenses=('research_development','sales_marketing','general_admin')
    oi=rev-cr-L.total(c,p,expenses)
    if not (c=='FRSH' and p in {'CY2021','CY2022'}): oi-=v('restructuring')
    out={'revenue':rev,'gross_profit':rev-cr,'operating_income':oi,
         'gross_margin_pct':pct(rev-cr,rev),'operating_margin_pct':pct(oi,rev),
         'sales_marketing_ratio_pct':pct(v('sales_marketing'),rev)}
    if (c,p,'sbc_expense') in L.rows:
        s=v('sbc_expense')
        selling=v('sales_marketing')-v('sbc_sales_marketing')-v('commission_amortization')+v('commission_capitalized')
        out.update(sbc_expense=s, operating_income_before_recognized_sbc=oi+s,
                   commission_timing_adjusted_selling_proxy=selling,
                   selling_proxy_ratio_pct=pct(selling,rev))
        if c=='FRSH':
            product=v('research_development')-v('sbc_research_development')+v('cash_software')
            out.update(product_resource_proxy=product, product_resource_ratio_pct=pct(product,rev))
    return out

def frsh_cash(L: Ledger,p: str) -> dict[str,Decimal]:
    v=lambda m:L.get('FRSH',p,m)
    fcf=v('cfo')-v('cash_ppe')-v('cash_software')
    out={'cfo':v('cfo'),'cash_investment':v('cash_ppe')+v('cash_software'),
         'unadjusted_fcf':fcf,'fcf_margin_pct':pct(fcf,v('revenue'))}
    if p in {'CY2021','CY2022'}:return out
    wc=L.total('FRSH',p,('wc_receivables','wc_prepaid_other','wc_payables','wc_accrued',
                         'wc_deferred_revenue','wc_lease_liabilities'))-v('commission_capitalized')
    noncash=L.total('FRSH',p,('depreciation_amortization','commission_amortization','noncash_lease',
                             'sbc_cashflow','securities_discount_amortization','deferred_tax_adjustment','other_noncash'))
    if p.startswith('CY'):
        noncash+=v('private_sale_gain_adjustment')+v('tax_allowance_release_adjustment')
    acquisition=v('acquisition_cash')+(v('acquisition_advance') if p.startswith('CY') else ZERO)
    employee=v('espp_proceeds')+v('option_proceeds')
    net_employee=fcf+employee-v('cash_withholding')
    cfi=(v('securities_maturities')-v('securities_purchases')+v('ppe_sale')
         -v('cash_ppe')-v('cash_software')-acquisition)
    if p.startswith('CY'):cfi+=v('private_sale_proceeds')
    cff=employee-v('cash_withholding')-v('cash_buybacks')
    fx=v('cash_fx') if p.startswith('H1') else ZERO
    out.update(working_capital=wc,noncash_adjustments=noncash,
        cfo_reconciliation_residual=v('net_income')+noncash+wc-v('cfo'),
        employee_receipts=employee,after_employee_cash=net_employee,
        acquisition_cash_including_advance=acquisition,
        after_employee_and_acquisition=net_employee-acquisition,
        after_buybacks_and_acquisition=net_employee-acquisition-v('cash_buybacks'),
        cash_buybacks=v('cash_buybacks'),cash_withholding=v('cash_withholding'),
        securities_net=v('securities_maturities')-v('securities_purchases'),
        ppe_sale=v('ppe_sale'),cash_fx=fx,
        cfi_reconciliation_residual=cfi-v('cfi'),cff_reconciliation_residual=cff-v('cff'),
        cash_change=v('cash_close')-v('cash_open'),
        cash_reconciliation_residual=v('cash_open')+v('cfo')+v('cfi')+v('cff')+fx-v('cash_close'))
    if ('FRSH',p,'interest_income') in L.rows:
        out['fcf_less_accrual_interest_sensitivity']=fcf-v('interest_income')
    return out

def frsh_claims(L: Ledger,p: str,C: dict[str,Decimal]) -> dict[str,Decimal]:
    v=lambda m:L.get('FRSH',p,m,'shares_m')
    opening=v('basic_open')+v('awards_open')+v('options_open')
    closing=v('basic_close')+v('awards_close')+v('options_close')
    # Vesting/exercise moves rights into shares, not an additional grant.
    withheld=v('awards_vested')-v('common_rsu_net')
    q=v('awards_granted')-v('awards_forfeited')-v('options_cancelled')-withheld+v('common_espp_net')
    price=L.get('FRSH',p,'program_average_price','USD_per_share')
    room=neutralization_room(C['unadjusted_fcf'],C['employee_receipts'],C['cash_withholding'],
                            C['acquisition_cash_including_advance'],q,price)
    return {'opening_gross_inventory':opening,'closing_gross_inventory':closing,
        'gross_inventory_change':closing-opening,'basic_share_change':v('basic_close')-v('basic_open'),
        'awards_inventory_change':v('awards_close')-v('awards_open'),
        'implied_units_withheld':withheld,'net_new_inventory_before_buybacks':q,
        'gross_inventory_identity_residual':closing-opening-q+v('common_repurchased'),
        'basic_rollforward_residual':v('basic_open')+v('common_option_exercise')+v('common_rsu_net')+v('common_espp_net')-v('common_repurchased')-v('basic_close'),
        'options_rollforward_residual':v('options_open')-v('options_exercised')-v('options_cancelled')-v('options_close'),
        'historical_price':price,'illustrative_neutralization_purchase':max(q,ZERO)*price,
        'neutralization_room_before_acquisition':room+C['acquisition_cash_including_advance'],
        'neutralization_room_after_acquisition':room,
        'neutralization_room_less_accrual_interest_sensitivity':room-L.get('FRSH',p,'interest_income')}

def crm_cash(L: Ledger,p: str) -> dict[str,Decimal]:
    v=lambda m:L.get('CRM',p,m)
    noncash=L.total('CRM',p,('depreciation_amortization','commission_amortization','sbc_cashflow','investment_gain_adjustment'))
    wc=L.total('CRM',p,('wc_receivables','wc_prepaid_other','wc_payables_accrued','wc_lease_liabilities','wc_deferred_revenue'))-v('commission_capitalized')
    fcf=v('cfo')-v('cash_capex')
    afterprincipal=fcf-v('financing_principal')
    afteremployee=afterprincipal+v('employee_plan_proceeds')-v('cash_withholding')
    cfi=(v('strategic_sales')-v('strategic_purchases')+v('securities_sales')+v('securities_maturities')
         -v('securities_purchases')-v('cash_capex')-v('acquisition_cash'))
    cff=(v('debt_proceeds')+v('employee_plan_proceeds')-v('cash_withholding')-v('cash_buybacks')
         -v('financing_principal')-v('debt_repayment')-v('cash_dividends'))
    return {'cfo':v('cfo'),'working_capital':wc,'noncash_adjustments':noncash,
        'cfo_reconciliation_residual':v('net_income')+noncash+wc-v('cfo'),
        'unadjusted_fcf':fcf,'after_financing_principal':afterprincipal,
        'after_employee_cash':afteremployee,
        'after_buybacks_and_dividends_before_acquisitions':afteremployee-v('cash_buybacks')-v('cash_dividends'),
        'after_acquisitions_and_strategic_net':afteremployee-v('cash_buybacks')-v('cash_dividends')-v('acquisition_cash')-v('strategic_purchases')+v('strategic_sales'),
        'cfi_reconciliation_residual':cfi-v('cfi'),'cff_reconciliation_residual':cff-v('cff'),
        'cash_reconciliation_residual':v('cash_open')+v('cfo')+v('cfi')+v('cff')+v('cash_fx')-v('cash_close')}

def stringify(x: Any) -> Any:
    if isinstance(x,D):return str(x)
    if isinstance(x,dict):return {k:stringify(v) for k,v in x.items()}
    if isinstance(x,list):return [stringify(v) for v in x]
    return x

def analyze(L: Ledger) -> dict[str,Any]:
    periods=['CY2021','CY2022','CY2023','CY2024','CY2025','H1_2025','H1_2026']
    op={p:operating(L,'FRSH',p) for p in periods}
    cash={p:frsh_cash(L,p) for p in periods}
    claims={p:frsh_claims(L,p,cash[p]) for p in ('CY2025','H1_2026')}
    combined={m:cash['CY2025'][m]+cash['H1_2026'][m] for m in (
        'unadjusted_fcf','employee_receipts','cash_withholding','after_employee_cash',
        'acquisition_cash_including_advance','cash_buybacks','after_buybacks_and_acquisition',
        'securities_net','ppe_sale','cash_fx','cash_change')}
    combined['private_sale_proceeds']=L.get('FRSH','CY2025','private_sale_proceeds')
    combined['cash_reconciliation_residual']=(combined['after_buybacks_and_acquisition']+combined['securities_net']
       +combined['ppe_sale']+combined['cash_fx']+combined['private_sale_proceeds']-combined['cash_change'])
    combined['gross_inventory_change']=claims['H1_2026']['closing_gross_inventory']-claims['CY2025']['opening_gross_inventory']
    combined['basic_share_change']=L.get('FRSH','H1_2026','basic_close','shares_m')-L.get('FRSH','CY2025','basic_open','shares_m')
    combined['gross_inventory_decline_pct']=pct(-combined['gross_inventory_change'],claims['CY2025']['opening_gross_inventory'])
    combined['basic_share_decline_pct']=pct(-combined['basic_share_change'],L.get('FRSH','CY2025','basic_open','shares_m'))
    growth={}
    for a,b in [('CY2023','CY2025'),('CY2024','CY2025'),('H1_2025','H1_2026')]:
        growth[f'{a}_to_{b}']={m:op[b][m]-op[a][m] for m in ('revenue','operating_income','sbc_expense','operating_income_before_recognized_sbc','commission_timing_adjusted_selling_proxy','selling_proxy_ratio_pct')}
        growth[f'{a}_to_{b}'].update(cfo_change=cash[b]['cfo']-cash[a]['cfo'],
            fcf_change=cash[b]['unadjusted_fcf']-cash[a]['unadjusted_fcf'],
            working_capital_change=cash[b]['working_capital']-cash[a]['working_capital'])
    fh={m:L.get('FRSH','H1_2026',m) for m in ('acquisition_consideration','acquired_cash','unpaid_acquisition_holdback','acquisition_cash')}
    fh['advance']=L.get('FRSH','CY2025','acquisition_advance')
    fh['reconciliation_residual']=fh['advance']+fh['acquisition_cash']+fh['acquired_cash']+fh['unpaid_acquisition_holdback']-fh['acquisition_consideration']
    crm_op={p:operating(L,'CRM',p) for p in ('FY2024','FY2025','FY2026')}
    return stringify({'units':'USD_m; shares_m; ratios in percent; see report for conventions',
        'observed_numeric_rows':len(L.rows),'FRSH_operating':op,'FRSH_cash':cash,'FRSH_claims':claims,
        'FRSH_changes':growth,'FRSH_18m':combined,'FireHydrant':fh,
        'FRSH_2025_without_specific_award_reversal_sensitivity':op['CY2025']['operating_income']-L.get('FRSH','CY2025','chair_award_forfeiture_reversal'),
        'CRM_operating':crm_op,'CRM_cash':{p:crm_cash(L,p) for p in crm_op},
        'CRM_FY24_to_FY26_pre_sbc_operating_improvement':crm_op['FY2026']['operating_income_before_recognized_sbc']-crm_op['FY2024']['operating_income_before_recognized_sbc']})

def checks(L: Ledger,R: dict[str,Any]) -> int:
    n=0
    def check(ok: bool,msg: str) -> None:
        nonlocal n
        n+=1
        if not ok:raise ValueError('Check failed: '+msg)
    def walk(x: Any) -> None:
        if isinstance(x,dict):
            for k,v in x.items():
                if k.endswith('_residual'):check(D(v)==0,k+' = '+v)
                else:walk(v)
    walk(R)
    for company,periods in [('FRSH',('CY2023','CY2024','CY2025','H1_2025','H1_2026')),('CRM',('FY2024','FY2025','FY2026'))]:
        for p in periods:
            op=operating(L,company,p)
            if (company,p,'operating_income') in L.rows:
                check(op['operating_income']==L.get(company,p,'operating_income'),'GAAP operating statement '+p)
            metrics=('sbc_cost_revenue','sbc_research_development','sbc_sales_marketing','sbc_general_admin')
            s=L.total(company,p,metrics)
            if company=='CRM':s+=L.get(company,p,'sbc_restructuring')
            check(s==L.get(company,p,'sbc_expense'),'SBC functions '+p)
            if (company,p,'commissions_open') in L.rows:
                check(L.get(company,p,'commissions_open')+L.get(company,p,'commission_capitalized')-L.get(company,p,'commission_amortization')==L.get(company,p,'commissions_close'),'commission rollforward '+p)
    for p in ('CY2023','CY2024','CY2025','H1_2026'):
        v=lambda m:L.get('FRSH',p,m,'shares_m')
        check(v('awards_open')+v('awards_granted')-v('awards_vested')-v('awards_forfeited')==v('awards_close'),'award rollforward '+p)
    for p in ('CY2023','CY2024','CY2025'):
        v=lambda m:L.get('FRSH',p,m)
        check(v('deferred_revenue_open')+v('billings')-v('revenue')==v('deferred_revenue_close'),'billings accrual identity '+p)
    frozen=[(R['FRSH_18m']['cash_change'],'-124.586'),(R['FRSH_18m']['gross_inventory_change'],'-31.526'),
      (R['FRSH_18m']['after_buybacks_and_acquisition'],'-405.338'),
      (R['FRSH_claims']['CY2025']['neutralization_room_after_acquisition'],'54.30853'),
      (R['FRSH_claims']['H1_2026']['neutralization_room_after_acquisition'],'-70.56950'),
      (R['FRSH_changes']['CY2023_to_CY2025']['operating_income_before_recognized_sbc'],'119.489'),
      (R['FRSH_changes']['H1_2025_to_H1_2026']['operating_income_before_recognized_sbc'],'-2.103'),
      (R['CRM_cash']['FY2026']['after_buybacks_and_dividends_before_acquisitions'],'323'),
      (R['CRM_FY24_to_FY26_pre_sbc_operating_improvement'],'4042')]
    for a,b in frozen:check(D(a)==D(b),'frozen result '+b)
    rng=random.Random(18)
    for _ in range(200):
        vals=[D(rng.randrange(0,100000))/1000 for _ in range(7)]
        f,e,w,a,q,p,t=vals
        r=neutralization_room(f,e,w,a,q,p)
        check(r==f+e-w-a-q*p,'synthetic conserved cash')
        check(neutralization_room(f,e,w,a,q,p+t)<=r,'price sensitivity')
        check(neutralization_room(f,e,w,a,q,p,owner_distribution=t)==r-t,'distribution funded once')
        check(neutralization_room(f,e,w,a,-q,p)==f+e-w-a,'no negative repurchase cash')
    return n

def rejection_checks(path: Path) -> int:
    """Mutation tests on temporary copies; input is never changed."""
    with path.open(newline='',encoding='utf-8') as f: originals=list(csv.DictReader(f))
    mutations=[('value',''),('value','NaN'),('value','Infinity'),('value','not-a-number'),
        ('status','unobserved'),('source_id','invented'),('source_url','https://example.invalid'),
        ('period_end','2025-12-30'),('unit','USD_bn'),('locator',''),('id','wrong'),('inspection_date','2026-10-18')]
    n=0
    with tempfile.TemporaryDirectory() as directory:
        bad=Path(directory)/'bad.csv'
        for field,value in mutations:
            rows=[r.copy() for r in originals];rows[0][field]=value
            with bad.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
            try:Ledger(bad)
            except ValueError:n+=1
            else:raise ValueError('Malformed ledger accepted: '+field+'='+value)
        for kind in ('duplicate','short','wrong_used_unit'):
            rows=[r.copy() for r in originals]
            if kind=='duplicate':rows.append(rows[0])
            if kind=='wrong_used_unit':rows[0]['unit']='shares_m'
            with bad.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
                if kind=='short':f.write('short,row\n')
            try:analyze(Ledger(bad))
            except ValueError:n+=1
            else:raise ValueError('Malformed ledger accepted: '+kind)
    return n

def locate_data(explicit: str|None) -> Path:
    if explicit:return Path(explicit)
    here=Path(__file__).resolve()
    candidates=[here.with_name(here.name.replace('calculations.py','data.csv')),here.with_name('data.csv')]
    for p in candidates:
        if p.is_file():return p
    raise ValueError('No matching data.csv found; use --data PATH')

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',help='Explicit path to the source-linked CSV')
    parser.add_argument('--check-only',action='store_true',help='Print only check counts')
    args=parser.parse_args()
    try:
        path=locate_data(args.data);L=Ledger(path);R=analyze(L)
        n=checks(L,R);rejected=rejection_checks(path)
        output={'numeric_rows':len(L.rows),'arithmetic_and_domain_checks':n,'malformed_ledgers_rejected':rejected}
        if not args.check_only:output['results']=R
        print(json.dumps(output,indent=2,ensure_ascii=False))
        return 0
    except (ValueError,OSError,InvalidOperation) as exc:
        print(f'Error: {exc}',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
