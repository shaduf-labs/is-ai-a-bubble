#!/usr/bin/env python3
"""Reproduce 'Who funds the next purchase?' with an inspectable local CSV.

Python standard library only; no network, trades, file mutation or external data.
Usage: python repeat-investment-calculations.py [--data PATH] [--skip-tests]
The script finds the CSV with the matching filename prefix automatically.
Amounts are USD millions unless an output is explicitly a percent.

IMPORTANT: NVIDIA's account bridge is NOT measured gross customer receipts.
CoreWeave's before-working-capital subtotal is NOT normalized free cash flow.
The Meta repeat test is a historical-use counterfactual, NOT a Q3 forecast.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, getcontext
import json
from pathlib import Path
import random
import re
import sys
from typing import Iterable

getcontext().prec = 34
D = Decimal
FIELDS = ('id','entity','metric','value','unit','status','kind','period_start','period_end','source_id','source_url','locator','note')
STATUSES = {'reported','reported_rounded','contractual_rounded','issuer_operational','unobserved','assumption'}
UNITS = {'USD_million','percent','shares','USD_per_share','GPUs'}
KINDS = {'flow','stock','event'}
WC = ('cf_ar','cf_prepaid','cf_ap','cf_deferred','cf_lease')
NONCASH = ('net_income','da','debt_amort','sbc','noncash_lease','deferred_tax','fairvalue','other_noncash')

@dataclass(frozen=True)
class Observation:
    key: str
    entity: str
    value: Decimal | None
    unit: str
    status: str
    kind: str
    start: date
    end: date
    source: str


def read_rows(rows: Iterable[dict[str, str]]) -> dict[str, Observation]:
    out = {}
    for n, r in enumerate(rows, 2):
        if set(r) != set(FIELDS) or any(v is None for v in r.values()):
            raise ValueError(f'Row {n}: wrong number of columns')
        key = r['id']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key) or key in out:
            raise ValueError(f'Row {n}: invalid or duplicate id {key!r}')
        if r['status'] not in STATUSES or r['unit'] not in UNITS or r['kind'] not in KINDS:
            raise ValueError(f'Row {n}: unsupported status, unit or kind')
        if any(not r[x].strip() for x in ('entity','metric','source_id','source_url','locator','note')):
            raise ValueError(f'Row {n}: missing provenance or definition')
        try:
            start, end = date.fromisoformat(r['period_start']), date.fromisoformat(r['period_end'])
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Row {n}: invalid ISO date') from exc
        if start > end or (r['kind'] in ('stock','event') and start != end):
            raise ValueError(f'Row {n}: inconsistent period')
        if r['status'] == 'unobserved':
            if r['value'] != '':
                raise ValueError(f'Row {n}: unobserved is blank, never an assumed zero')
            value = None
        else:
            try:
                value = D(r['value'])
            except InvalidOperation as exc:
                raise ValueError(f'Row {n}: nonnumeric value') from exc
            if not value.is_finite():
                raise ValueError(f'Row {n}: nonfinite value')
            if r['unit'] == 'percent' and not D(0) <= value <= D(100):
                raise ValueError(f'Row {n}: percent outside 0-100')
            if r['unit'] in ('shares','GPUs') and (value < 0 or value != value.to_integral_value()):
                raise ValueError(f'Row {n}: invalid count')
            if r['kind'] == 'stock' and value < 0:
                raise ValueError(f'Row {n}: negative stock for selected metrics')
        out[key] = Observation(key,r['entity'],value,r['unit'],r['status'],r['kind'],start,end,r['source_id'])
    if not out:
        raise ValueError('Empty ledger')
    return out


def load(path: Path) -> dict[str, Observation]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError('CSV header does not match the documented schema')
        return read_rows(reader)


class Ledger:
    def __init__(self, obs: dict[str, Observation]):
        self.obs = obs

    def v(self, key: str, unit: str = 'USD_million') -> Decimal:
        try:
            x = self.obs[key]
        except KeyError as exc:
            raise ValueError(f'Missing required input: {key}') from exc
        if x.value is None:
            raise ValueError(f'Cannot calculate with unknown input {key}')
        if x.unit != unit:
            raise ValueError(f'{key}: expected {unit}, found {x.unit}')
        return x.value

    def q2(self, half: str, first: str, metric: str) -> Decimal:
        a, b = self.obs[f'{half}_{metric}'], self.obs[f'{first}_{metric}']
        if a.entity != b.entity or a.start != b.start or a.end <= b.end or a.unit != b.unit:
            raise ValueError(f'Unmatched cumulative periods for {metric}')
        if a.kind != 'flow' or b.kind != 'flow':
            raise ValueError('Quarter subtraction is only valid for flows')
        y = a.start.year
        if (a.start, a.end, b.end) != (date(y,1,1), date(y,6,30), date(y,3,31)):
            raise ValueError('This Q2 comparison requires January-June less January-March of the same year')
        return self.v(a.key, a.unit) - self.v(b.key, b.unit)


def pct(num: Decimal, den: Decimal) -> Decimal:
    if den <= 0:
        raise ValueError('Percentage denominator must be positive')
    return D(100)*num/den


def customer_position(ar: Decimal, dr: Decimal, program: Decimal) -> Decimal:
    if min(ar,dr,program) < 0:
        raise ValueError('Selected account stocks must be nonnegative')
    return ar-dr-program


def account_bridge(revenue: Decimal, opening: Decimal, closing: Decimal) -> Decimal:
    if revenue < 0:
        raise ValueError('Revenue cannot be negative in this selected-period model')
    return revenue+opening-closing


def repeat_need(cfo: Decimal, ppe: Decimal, lease: Decimal, withholding: Decimal,
                dividends: Decimal, other_uses: Decimal = D(0), cash_change: Decimal = D(0)) -> Decimal:
    """Signed funding requirement, before opening cash or financing; negative = room.
    Other uses may be signed (e.g. a disposal receipt); positive cash_change means
    a higher operating cash result, not a second use of an already observed receipt.
    """
    if min(ppe,lease,withholding,dividends) < 0:
        raise ValueError('Specified payment magnitudes must be nonnegative')
    return ppe+lease+withholding+dividends+other_uses-cfo-cash_change


def calculate(L: Ledger) -> dict:
    V = L.v
    nv = {}
    for y in (24,25,26,27):
        prev=y-1
        opening_obs = L.obs[f'N{prev}_ar']
        closing_obs = L.obs[f'N{y}_ar']
        revenue_obs = L.obs[f'NF{y}_revenue']
        if (revenue_obs.kind != 'flow' or opening_obs.kind != 'stock' or closing_obs.kind != 'stock'
                or revenue_obs.start != opening_obs.end + timedelta(days=1)
                or revenue_obs.end != closing_obs.end
                or len({revenue_obs.entity, opening_obs.entity, closing_obs.entity}) != 1):
            raise ValueError(f'Unmatched NVIDIA account period {y}')
        for k, anchor_obs in ((f'N{prev}_deferred',opening_obs),(f'N{prev}_program',opening_obs),
                              (f'N{y}_deferred',closing_obs),(f'N{y}_program',closing_obs)):
            obs = L.obs[k]
            if obs.kind != 'stock' or obs.end != anchor_obs.end or obs.entity != anchor_obs.entity:
                raise ValueError(f'Unmatched selected account {k}')
        opening=customer_position(V(f'N{prev}_ar'),V(f'N{prev}_deferred'),V(f'N{prev}_program'))
        closing=customer_position(V(f'N{y}_ar'),V(f'N{y}_deferred'),V(f'N{y}_program'))
        r=V(f'NF{y}_revenue')
        delta_ar=V(f'N{y}_ar')-V(f'N{prev}_ar')
        delta_dr=V(f'N{y}_deferred')-V(f'N{prev}_deferred')
        delta_program=V(f'N{y}_program')-V(f'N{prev}_program')
        nv[str(y)]=dict(revenue=r,opening_customer_position=opening,closing_customer_position=closing,
            delta_ar=delta_ar,delta_dr=delta_dr,delta_program=delta_program,
            increase_net_customer_position=closing-opening,
            account_bridge_NOT_gross_receipts=account_bridge(r,opening,closing),
            receivable_only_reconciliation=r-delta_ar,
            ar_balance_less_cashflow_increase=delta_ar+V(f'NF{y}_cf_ar'),
            cfo=V(f'NF{y}_cfo'))
    nv['growth']=dict(h1_revenue_percent=pct(V('NF27_revenue')-V('NH26_revenue'),V('NH26_revenue')),
        h1_data_center_percent=pct(V('NF27_data_center')-V('NH26_data_center'),V('NH26_data_center')),
        h1_hyperscale_growth=V('NH27_hyperscale')-V('NH26_hyperscale'),
        h1_acie_growth=V('NH27_acie')-V('NH26_acie'),
        h1_edge_growth=V('NH27_edge')-V('NH26_edge'))
    nv['concentration']=dict(july_large_AR_percent=sum(V(f'N27_ar_conc_{i}','percent') for i in range(1,6)),
        january_large_AR_percent=sum(V(f'N26_ar_conc_{i}','percent') for i in range(1,4)),
        h1_large_revenue_percent=sum(V(f'NH27_rev_conc_{i}','percent') for i in range(1,4)))
    c={}
    cm=('revenue',)+NONCASH+WC+('cfo','ppe','principal','cfi','cff','debt_proceeds','equity_proceeds','cash_interest')
    for name,half in [('Q1',False),('Q2',True)]:
        d={m:(L.q2('CH','C1',m) if half else V(f'C1_{m}')) for m in cm}
        d['before_five_WC_movements']=sum(d[m] for m in NONCASH)
        d['five_WC_movements']=sum(d[m] for m in WC)
        d['cash_after_PPE']=d['cfo']-d['ppe']
        d['cash_after_PPE_and_principal']=d['cfo']-d['ppe']-d['principal']
        d['cash_change']=d['cfo']+d['cfi']+d['cff']
        c[name]=d
    c['change']=dict(cfo=c['Q2']['cfo']-c['Q1']['cfo'],
        before_WC=c['Q2']['before_five_WC_movements']-c['Q1']['before_five_WC_movements'],
        WC=c['Q2']['five_WC_movements']-c['Q1']['five_WC_movements'],
        revenue_percent=pct(c['Q2']['revenue']-c['Q1']['revenue'],c['Q1']['revenue']))
    dr0=V('C0_dr_current')+V('C0_dr_long'); dr1=V('C1_dr_current')+V('C1_dr_long'); dr2=V('C2_dr_current')+V('C2_dr_long')
    c['reported_liquidity']=dict(cash=L.v('C2_cash_unrestricted'),securities=L.v('C2_marketable'),
        undrawn_facility_availability=L.v('C2_facility_available'),
        total=L.v('C2_cash_unrestricted')+L.v('C2_marketable')+L.v('C2_facility_available'),
        boundary='Includes conditional borrowing availability, not all cash or universally fungible resources')
    c['classification']=dict(dr_december=dr0,dr_march=dr1,dr_june=dr2,
        q1_dr_change=dr1-dr0,q2_dr_change=dr2-dr1,
        q1_DR_stock_change_less_CF_line=dr1-dr0-V('C1_cf_deferred'),
        q1_addback_rounded_reclass_residual=dr1-dr0+V('C1_dr_reclass')-V('C1_cf_deferred'),
        q1_customer_liability_change=V('C1_customer_liability')-V('C0_customer_liability'),
        q1_combined_liability_change=dr1-dr0+V('C1_customer_liability')-V('C0_customer_liability'),
        q1_combined_change_less_CF_line=dr1-dr0+V('C1_customer_liability')-V('C0_customer_liability')-V('C1_cf_deferred'),
        h1_AR_balance_less_CF_effect=V('C0_ar')-V('C2_ar')-V('CH_cf_ar'),
        h1_DR_change_less_CF_line=dr2-dr0-V('CH_cf_deferred'),
        q2_other_current_liability_change=V('C2_other_current_liability')-V('C1_other_current_liability'),
        june_customer_liability='unobserved; not zero')
    m={}
    mm=('cfo','ppe','lease_principal','equity_withholding','dividends')
    for tag,half,first in [('2026Q1',None,'M1'),('2026Q2','MH','M1'),('2025Q1',None,'MP1'),('2025Q2','MPH','MP1')]:
        d={x:(L.q2(half,first,x) if half else V(f'{first}_{x}')) for x in mm}
        d['cash_capital_spending']=d['ppe']+d['lease_principal']
        d['cash_after_capital']=d['cfo']-d['cash_capital_spending']
        d['cash_after_capital_withholding_dividends']=d['cash_after_capital']-d['equity_withholding']-d['dividends']
        m[tag]=d
    q=m['2026Q2'];p=m['2025Q2']
    m['change']=dict(qoq_cash_after_capital=q['cash_after_capital']-m['2026Q1']['cash_after_capital'],
        yoy_cfo_percent=pct(q['cfo']-p['cfo'],p['cfo']),
        yoy_capital_percent=pct(q['cash_capital_spending']-p['cash_capital_spending'],p['cash_capital_spending']))
    m['repeat']=dict(cfo_required_before_other_uses=q['cash_capital_spending']+q['equity_withholding']+q['dividends'],
        unchanged_reference_need=repeat_need(q['cfo'],q['ppe'],q['lease_principal'],q['equity_withholding'],q['dividends'],V('REF_meta_other_uses'),V('REF_meta_cfo_change')),
        no_dividend_reference_need=repeat_need(q['cfo'],q['ppe'],q['lease_principal'],q['equity_withholding'],D(0)),
        cfo_required_increase_percent=pct(-q['cash_after_capital_withholding_dividends'],q['cfo']))
    m['Q2_total_cash_account']={x:L.q2('MH','M1',x) for x in ('cfo','cfi','cff','fx','debt_proceeds','other_financing','securities_purchases','securities_sales')}
    m['Q2_total_cash_account']['cash_change']=sum(m['Q2_total_cash_account'][x] for x in ('cfo','cfi','cff','fx'))
    return dict(units='USD millions except fields explicitly named percent',nvidia=nv,coreweave=c,meta=m,
        notes=['No estimated gross supplier or named-customer receipts.',
        'Q2 equals cumulative H1 less the corresponding Q1 at the same consolidated perimeter.',
        'Positive CFO includes working-capital and advance timing; future replacement is not free.',
        'Cash uses already inside CFO or PPE are not charged a second time.'])


def run_tests(L: Ledger, out: dict) -> int:
    n=0
    def eq(a,b):
        nonlocal n
        n+=1
        if a!=b:raise AssertionError(f'Check {n}: {a} != {b}')
    for y in (24,25,26,27):
        V=L.v
        eq(V(f'N{y-1}_deferred')+V(f'NF{y}_dr_add')-V(f'NF{y}_dr_recognized'),V(f'N{y}_deferred'))
        q=out['nvidia'][str(y)]
        eq(q['revenue']-q['increase_net_customer_position'],q['account_bridge_NOT_gross_receipts'])
    for name in ('Q1','Q2'):
        d=out['coreweave'][name]
        eq(d['before_five_WC_movements']+d['five_WC_movements'],d['cfo'])
    eq(out['coreweave']['change']['before_WC']+out['coreweave']['change']['WC'],out['coreweave']['change']['cfo'])
    eq(L.v('C0_cash_total')+out['coreweave']['Q1']['cash_change'],L.v('C1_cash_total'))
    eq(L.v('C1_cash_total')+out['coreweave']['Q2']['cash_change'],L.v('C2_cash_total'))
    eq(L.v('M0_cash_total')+L.v('M1_cfo')+L.v('M1_cfi')+L.v('M1_cff')+L.v('M1_fx'),L.v('M1_cash_total'))
    eq(L.v('M1_cash_total')+out['meta']['Q2_total_cash_account']['cash_change'],L.v('M2_cash_total'))
    for k in ('M0','M1','M2'):
        eq(L.v(k+'_cash_total'),L.v(k+'_cash_unrestricted')+L.v(k+'_restricted'))
    for k in ('C1','C2'):
        eq(L.v(k+'_cash_total'),L.v(k+'_cash_unrestricted')+L.v(k+'_restricted_current')+L.v(k+'_restricted_long'))
    for k in ('M1','MH'):
        expected=L.v(k+'_debt_proceeds')-L.v(k+'_equity_withholding')-L.v(k+'_dividends')-L.v(k+'_lease_principal')-L.v(k+'_other_financing')-L.v(k+'_buybacks')
        eq(expected,L.v(k+'_cff'))
    eq(out['nvidia']['27']['account_bridge_NOT_gross_receipts'],D(159157))
    eq(out['coreweave']['Q2']['cfo'],D(679))
    eq(out['coreweave']['Q2']['cash_after_PPE_and_principal'],D(-9627))
    eq(out['coreweave']['classification']['q1_addback_rounded_reclass_residual'],D(63))
    eq(out['meta']['2026Q2']['cash_after_capital'],D(784))
    eq(out['meta']['repeat']['unchanged_reference_need'],D(4850))
    eq(out['coreweave']['reported_liquidity']['total'],D(15553))
    rng=random.Random(16102026)
    for _ in range(200):
        rev, ar0, ar1, dr0, dr1, pr0, pr1 = (D(rng.randrange(0,100000)) for i in range(7))
        a=customer_position(ar0,dr0,pr0);b=customer_position(ar1,dr1,pr1)
        eq(account_bridge(rev,a,b),rev-(ar1-ar0)+(dr1-dr0)+(pr1-pr0))
        base=repeat_need(rev,ar0,ar1,dr0,dr1)
        eq(repeat_need(rev,ar0,ar1,dr0,dr1,pr0),base+pr0)
        eq(repeat_need(rev,ar0,ar1,dr0,dr1,D(0),pr1),base-pr1)
    return n


def default_data(script: Path) -> Path:
    if script.name.endswith('calculations.py'):
        candidate=script.with_name(script.name[:-len('calculations.py')]+'data.csv')
        if candidate.is_file():return candidate
    return script.with_name('data.csv')


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data',type=Path,default=default_data(Path(__file__).resolve()))
    ap.add_argument('--skip-tests',action='store_true',help='Calculate without the built-in implementation checks')
    args=ap.parse_args()
    try:
        L=Ledger(load(args.data));results=calculate(L)
        tests=0 if args.skip_tests else run_tests(L,results)
    except (OSError,ValueError,KeyError,InvalidOperation,AssertionError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 2
    payload=dict(input_rows=len(L.obs),checks_passed=tests,results=results)
    print(json.dumps(payload,indent=2,ensure_ascii=False,default=str))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
