#!/usr/bin/env python3
"""Customer persistence, complete costs and cash capture — 29 September 2026.

Python 3.10+, standard library for all calculations/tests. No network calls.
Usage:
  python capture-calculations.py [--data capture-data.csv] [--figure capture-bridge.svg]
The delivery-prefixed sibling filenames work without changes.
Matplotlib is required only for --figure. Reported values remain dated inputs.

All money inputs are USD millions. Accrual profit is NOT collected cash. Company
retention is NOT AI-product retention. Diagnostic expense-envelope sensitivities
are not forecasts. The advertiser example holds a reported outcome gain fixed
under a hypothetical budget change; it is not an observed campaign cash result.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path
from typing import Mapping

DATA_NAME = 'capture-data.csv'
DELIVERED_DATA_NAME = Path(__file__).name.replace('capture-calculations.py', DATA_NAME)
FIELDS = ('id','entity','metric','period_start','period_end','value','unit','status',
          'source_id','source_url','locator','notes')
STATUSES = {'reported_actual','company_estimate','company_claim',
            'provider_reported_experiment','research_assumption','reported_commitment'}
UNITS = {'USD_million','USD_million_per_year','fraction','accounts'}
Row = dict[str, str]
Inputs = dict[str, Row]


def need(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def near(actual: float, expected: float, label: str = '') -> None:
    need(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7),
         f'{label}: {actual} != {expected}')


def load_inputs(path: Path) -> Inputs:
    out: Inputs = {}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        need(tuple(reader.fieldnames or ()) == FIELDS, 'Unexpected CSV schema')
        for row in reader:
            need(None not in row and all(value is not None for value in row.values()),
                 'Malformed CSV record')
            key = row['id']
            need(bool(key) and key not in out, f'Missing or duplicate ID: {key}')
            number = float(row['value'])
            need(math.isfinite(number), f'Nonfinite value: {key}')
            need(row['unit'] in UNITS, f'Unknown unit: {key}')
            need(row['status'] in STATUSES, f'Unknown status: {key}')
            need(bool(row['entity'] and row['metric'] and row['locator']), f'Missing perimeter: {key}')
            for field in ('period_start','period_end'):
                if row[field]:
                    date.fromisoformat(row[field])
            if row['period_start'] and row['period_end']:
                need(row['period_start'] <= row['period_end'], f'Reversed period: {key}')
            if row['status'] != 'research_assumption':
                need(row['source_url'].startswith('https://'), f'Missing source URL: {key}')
            out[key] = row
    need(bool(out), 'Empty data file')
    return out


def value(d: Mapping[str, Row], key: str, unit: str = 'USD_million') -> float:
    row = d[key]
    need(row['unit'] == unit, f'Wrong unit for {key}: {row["unit"]}')
    result = float(row['value'])
    need(math.isfinite(result), f'Nonfinite input: {key}')
    return result


def f(d: Inputs, period: str, metric: str) -> float:
    return value(d, 'F_'+period+'_'+metric)


def m(d: Inputs, period: str, metric: str) -> float:
    return value(d, 'M_'+period+'_'+metric)


def growth(new: float, old: float) -> float:
    need(old > 0, 'Growth denominator must be positive')
    return new / old - 1


@dataclass(frozen=True)
class PersistenceBridge:
    prior_revenue: float
    existing_increase: float
    implied_existing_revenue: float
    residual_new_revenue: float
    rounded_new_disclosure: float
    current_revenue: float
    cost_envelope: float
    minimum_existing_with_new_unchanged: float


def persistence(d: Inputs, half_year: bool = False) -> PersistenceBridge:
    now, old, suffix = ('H126','H125','H1') if half_year else ('Q226','Q225','Q2')
    prior, current = f(d,old,'revenue'), f(d,now,'revenue')
    increase = value(d,'F_existing_growth_'+suffix)
    existing = prior + increase
    new = current - existing
    rounded_new = value(d,'F_new_growth_'+suffix)
    costs = f(d,now,'cost_revenue') + f(d,now,'operating_expenses')
    return PersistenceBridge(prior,increase,existing,new,rounded_new,current,costs,costs-new)


NONCASH = ('da','contract_amort','noncash_lease','sbc_cf','discount_amort','deferred_tax','other_noncash')
WORKING = ('ar_change','capitalized_contract_cost','prepaid_change','ap_change',
           'accrued_change','deferred_rev_change','lease_liab_change')


def fresh_cash(d: Inputs, period: str) -> dict[str, float]:
    ocf = f(d,period,'ocf')
    raw = ocf - f(d,period,'cash_ppe') - f(d,period,'cash_software')
    result = {'ocf':ocf, 'raw_cash_residual':raw,
              'adjusted_fcf':raw+f(d,period,'adjustment_costs_paid')}
    if period.startswith('H1'):
        noncash = sum(f(d,period,k) for k in NONCASH)
        wc = sum(f(d,period,k) for k in WORKING)
        net = f(d,period,'net_income')
        result.update(net_income=net, noncash_adjustments=noncash,
                      working_capital=wc, reconstructed_ocf=net+noncash+wc)
    return result


def operating_profit_after_revenue_change(revenue: float, cost_revenue: float,
                                         operating_expenses: float,
                                         revenue_ratio: float,
                                         proportional_delivery: bool = False) -> float:
    need(revenue > 0 and cost_revenue >= 0 and operating_expenses >= 0,
         'Invalid cost envelope')
    need(math.isfinite(revenue_ratio) and revenue_ratio >= 0, 'Invalid revenue ratio')
    delivery = cost_revenue * revenue_ratio if proportional_delivery else cost_revenue
    return revenue * revenue_ratio - delivery - operating_expenses


def diagnostics(d: Inputs) -> dict[str, float]:
    rev, cor, opx, op = (f(d,'Q226',k) for k in ('revenue','cost_revenue','operating_expenses','operating_income'))
    gp = rev-cor
    need(op > 0 and gp > 0, 'Positive reference margin required')
    d_rev = rev-f(d,'Q225','revenue')
    d_cor = cor-f(d,'Q225','cost_revenue')
    d_opx = opx-f(d,'Q225','operating_expenses')
    d_op = op-f(d,'Q225','operating_income')
    sbc_decline = f(d,'Q225','sbc_expense')-f(d,'Q226','sbc_expense')
    return dict(revenue_increase=d_rev,delivery_increase=d_cor,opex_increase=d_opx,
                operating_income_increase=d_op,sbc_expense_decline=sbc_decline,
                sbc_share_of_operating_increase=sbc_decline/d_op,
                operating_increase_holding_sbc_change_out=d_op-sbc_decline,
                gross_margin=gp/rev,operating_margin=op/rev,
                fixed_cost_revenue_decline=op/rev,
                proportional_delivery_revenue_decline=op/gp,
                hosting_increase_share=value(d,'F_hosting_growth_Q2')/d_cor)


def meta_analysis(d: Inputs) -> dict[str, float]:
    ad_new, ad_old = m(d,'Q226','ad_revenue'),m(d,'Q225','ad_revenue')
    volume,price = value(d,'M_impression_growth','fraction'),value(d,'M_price_growth','fraction')
    proxy=(1+volume)*(1+price)-1
    actual=growth(ad_new,ad_old)
    result={'ad_growth':actual,'rounded_price_volume_growth':proxy,
            'price_volume_rounding_gap_pp':100*(proxy-actual),
            'revenue_increase':m(d,'Q226','revenue')-m(d,'Q225','revenue'),
            'cost_increase':m(d,'Q226','total_cost')-m(d,'Q225','total_cost'),
            'operating_income_change':m(d,'Q226','operating_income')-m(d,'Q225','operating_income'),
            'h1_operating_income_change':m(d,'H126','operating_income')-m(d,'H125','operating_income'),
            'op_plus_selected_charges':m(d,'Q226','operating_income')+value(d,'M_legal_charge')+value(d,'M_severance_charge')}
    for period in ('Q226','Q225','H126','H125'):
        result[period+'_cash_residual']=m(d,period,'ocf')-m(d,period,'cash_ppe')-m(d,period,'finance_lease_principal')
    return result


def buyer_cost_per_outcome(outcome_gain: float, spend_growth: float) -> float:
    """Relative cost per outcome. Not an estimate of advertiser profit or ROAS."""
    need(math.isfinite(outcome_gain) and outcome_gain > -1,'Invalid outcome gain')
    need(math.isfinite(spend_growth) and spend_growth > -1,'Invalid spend growth')
    return (1+spend_growth)/(1+outcome_gain)


def run_tests(d: Inputs) -> None:
    for period in ('Q226','Q225','H126','H125'):
        near(f(d,period,'revenue')-f(d,period,'cost_revenue'),f(d,period,'gross_profit'),period+' gross profit')
        near(sum(f(d,period,k) for k in ('research_development','sales_marketing','general_admin','restructuring')),
             f(d,period,'operating_expenses'),period+' expenses')
        near(f(d,period,'gross_profit')-f(d,period,'operating_expenses'),f(d,period,'operating_income'),period+' op')
        near(f(d,period,'operating_income')+f(d,period,'interest_other')-f(d,period,'income_tax'),f(d,period,'net_income'),period+' net')
        c = fresh_cash(d,period)
        near(c['adjusted_fcf'], f(d,period,'adjusted_fcf'),period+' FCF')
        if 'reconstructed_ocf' in c:
            near(c['reconstructed_ocf'],c['ocf'],period+' cash bridge')
        near(m(d,period,'revenue')-m(d,period,'total_cost'),m(d,period,'operating_income'),period+' Meta op')
        near(sum(m(d,period,k) for k in ('cost_revenue','research_development','sales_marketing','general_admin')),
             m(d,period,'total_cost'),period+' Meta costs')
    for half in (False,True):
        p=persistence(d,half)
        near(p.implied_existing_revenue+p.residual_new_revenue,p.current_revenue,'persistence allocation')
        need(abs(p.residual_new_revenue-p.rounded_new_disclosure) < .1,'Rounded growth bridge mismatch')
        near(p.minimum_existing_with_new_unchanged+p.residual_new_revenue,p.cost_envelope,'required existing revenue')
    near(fresh_cash(d,'H126')['working_capital'],-4.059,'Component WC sign, not MD&A prose')
    near(fresh_cash(d,'H125')['working_capital'],-10.349,'Prior WC')
    near(fresh_cash(d,'H126')['raw_cash_residual'],107.120,'H1 raw cash')
    near(fresh_cash(d,'Q226')['raw_cash_residual'],52.011,'Q2 raw cash')
    near(value(d,'F_cash_start')+f(d,'H126','ocf')+value(d,'F_investing_cf')+
         value(d,'F_financing_cf')+value(d,'F_fx_cash'),value(d,'F_cash_end'),'Ending cash')
    z=diagnostics(d)
    near(z['revenue_increase']-z['delivery_increase']-z['opex_increase'],z['operating_income_increase'],'increment bridge')
    near(z['operating_income_increase'],14.716)
    near(z['sbc_expense_decline'],11.432)
    rev,cor,opx=(f(d,'Q226',k) for k in ('revenue','cost_revenue','operating_expenses'))
    for proportional,key in ((False,'fixed_cost_revenue_decline'),(True,'proportional_delivery_revenue_decline')):
        threshold=z[key]
        near(operating_profit_after_revenue_change(rev,cor,opx,1-threshold,proportional),0,'zero-profit threshold')
        need(operating_profit_after_revenue_change(rev,cor,opx,1-threshold-.001,proportional)<0,'Adverse direction')
        need(operating_profit_after_revenue_change(rev,cor,opx,1-threshold+.001,proportional)>0,'Favorable direction')
    a=meta_analysis(d)
    near(a['revenue_increase']-a['cost_increase'],a['operating_income_change'],'Meta increment')
    near(a['Q226_cash_residual'],784,'Meta cash')
    near(a['Q225_cash_residual'],8549,'Meta prior cash')
    near(a['H126_cash_residual'],13170,'Meta H1 cash')
    q=value(d,'L_conversion_uplift','fraction')
    near(buyer_cost_per_outcome(q,q),1,'Equal sharing boundary')
    need(buyer_cost_per_outcome(q,0)<buyer_cost_per_outcome(q,.02)<1,'Buyer benefit monotonicity')
    # Interpretation protections: paid lower bounds and experiments are not realized cash facts.
    need(d['F_paid_AI_accounts_lower']['status']=='company_claim','Paid-account status')
    need(d['L_conversion_uplift']['status']=='provider_reported_experiment','Experiment status')
    need(d['A_spend_growth']['status']=='research_assumption','Scenario status')
    for func,args in ((buyer_cost_per_outcome,(-1,0)),(buyer_cost_per_outcome,(.1,-1)),
                      (growth,(1,0)),(operating_profit_after_revenue_change,(1,1,1,-.1))):
        try:
            func(*args)
        except ValueError:
            pass
        else:
            raise ValueError('Invalid-input test did not reject')
    try:
        value(d,'F_NDR_Jun26','USD_million')
    except ValueError:
        pass
    else:
        raise ValueError('Unit validation did not reject')


def print_results(d: Inputs) -> None:
    print('FRESHWORKS: all-product perimeter; USD million; not AI-only cohort cash')
    for half in (False,True):
        p=persistence(d,half)
        print(('H1' if half else 'Q2')+f' growth bridge: existing {p.implied_existing_revenue:.3f}; new residual {p.residual_new_revenue:.3f}; total {p.current_revenue:.3f}; complete expense envelope {p.cost_envelope:.3f}')
        print(f'  Required existing revenue with reconstructed new contribution unchanged: {p.minimum_existing_with_new_unchanged:.3f}')
    for period in ('Q226','Q225','H126','H125'):
        print(period, {key:round(val,6) for key,val in fresh_cash(d,period).items()})
    for key,val in diagnostics(d).items():
        print(key,f'{val:.9f}')
    print('META: USD million, all company/FoA where stated; not model-attributed profit')
    for key,val in meta_analysis(d).items():
        print(key,f'{val:.9f}')
    q=value(d,'L_conversion_uplift','fraction')
    for spend in (0,value(d,'A_spend_growth','fraction'),q):
        print(f'Conditional outcome gain {q:.3%}, spend increase {spend:.3%}: cost/outcome change {buyer_cost_per_outcome(q,spend)-1:.6%}')
    print('FY2025 Freshworks unadjusted cash residual:',value(d,'F_FY25_OCF')-value(d,'F_FY25_PPE')-value(d,'F_FY25_software'))
    print('Seagate buyer-resource context cash residual:',value(d,'S_ocf')-value(d,'S_cash_ppe'))
    print(f'All accounting, status, unit, threshold and invalid-input checks passed; {len(d)} input records.')


def render_figure(d: Inputs, destination: Path) -> None:
    """One explanatory accrual-profit waterfall; defaults preserve neutral styling."""
    import matplotlib.pyplot as plt
    z=diagnostics(d)
    changes=[z['revenue_increase'],-z['delivery_increase'],-z['opex_increase'],z['operating_income_increase']]
    bottoms=[0,z['revenue_increase'],z['revenue_increase']-z['delivery_increase'],0]
    fig,ax=plt.subplots(figsize=(11.5,6.8))
    ax.bar(range(4),changes,bottom=bottoms)
    labels=['Additional\nrevenue','Additional cost\nof revenue','Additional\noperating expenses','Increase in\noperating income']
    ax.set_xticks(range(4),labels)
    ax.set_ylabel('USD million; Q2 2026 less Q2 2025')
    ax.set_title('Freshworks: what remains of the additional customer revenue?',pad=22)
    for i,(change,bottom) in enumerate(zip(changes,bottoms)):
        top=bottom+change
        text_y=(bottom+top)/2 if i in (1,2) else top+1.0
        ax.text(i,text_y,f'{change:+.3f}',ha='center',va='center',fontsize=12)
    ax.set_ylim(0,38)
    ax.axhline(0,linewidth=.7)
    fig.text(.10,.10,'Whole-company accrual accounting, NOT AI-only revenue or a cash-flow waterfall.\n'
             'Operating income rose from -8.656m to +6.060m. An 11.432m stock-compensation decline is already\n'
             'inside these costs; do not count it again. Sources: Freshworks June 2026 Form 10-Q; report sections 3–4.',fontsize=10)
    fig.subplots_adjust(bottom=.29,left=.10,right=.98,top=.85)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Shaduf; capture-calculations.py'})
    plt.close(fig)


def main() -> None:
    folder=Path(__file__).resolve().parent
    default=folder/DATA_NAME
    if not default.exists():
        default=folder/DELIVERED_DATA_NAME
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=default)
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args()
    d=load_inputs(args.data)
    run_tests(d)
    print_results(d)
    if args.figure:
        render_figure(d,args.figure)


if __name__=='__main__':
    try:
        main()
    except (OSError,KeyError,TypeError,ValueError) as error:
        raise SystemExit(f'Calculation failed: {error}') from error
