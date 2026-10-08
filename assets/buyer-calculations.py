#!/usr/bin/env python3
"""Buyer demand and budget substitution: reproducible diagnostics, not estimated company ROI.

Python 3.10+, standard library. Optional --figure requires matplotlib.
Run beside buyer-data.csv or the matching delivery-prefixed CSV; --data overrides.
Amounts never mix GBP and USD. Contract capacity is not actual consumption;
reported expense is not cash; scenarios are not probabilities or predictions.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Mapping

D = Decimal
FIELDS = ('id','entity','metric','value','unit','period','status','source_id',
          'source_url','locator','qualification')
ALLOWED_STATUS = frozenset(('contractual','buyer_reported','buyer_estimate',
    'buyer_policy','buyer_budget','secondary_payment_record','secondary_award_record',
    'reported_account','reported_interim','issuer_adjusted','attributed_buyer_claim',
    'research_assumption'))
# This is a frozen evidential package. Units/statuses are part of the input, not decoration.
SCHEMA: dict[str, tuple[str, str]] = {
 'N_FEE':('GBP','contractual'), 'N_HOURS':('recorded_hours','contractual'),
 'N_REPORTS':('reports','contractual'), 'N_MONTHS':('months','contractual'),
 'N_SUPPORT_FEE':('GBP','contractual'), 'N_NONRENEWAL':('days','contractual'),
 'N_REPRICE':('days','contractual'), 'N_DATA_REQUEST':('days','contractual'),
 'N_DATA_DELIVERY':('days','contractual'), 'N_THERAPY_UPLIFT':('fraction','buyer_reported'),
 'N_TRANSFER_DAYS':('days','buyer_policy'), 'N_RETENTION_DAYS':('days','buyer_policy'),
 'N_REPORTED_PAYMENT':('GBP','secondary_payment_record'),
 'N_FOLLOWON_FEE':('GBP','secondary_award_record'),
 'N_FOLLOWON_MONTHS':('months','secondary_award_record'),
 'N_BUDGET_EFFICIENCIES':('GBP_million','buyer_budget'),
 'K_SUPPLIER_REDUCTION':('USD_million','buyer_reported'),
 'K_AI_ATTRIBUTION':('fraction','buyer_estimate'),
 'K_AI_YEAR_ESTIMATE':('USD_million','buyer_estimate'),
 'K_AGENCY_2022':('USD_million','buyer_reported'),
 'K_AGENCY_2024':('USD_million','buyer_reported'),
 **{k:('USD_million','reported_account') for k in (
 'K_SM_2023','K_SM_2024','K_SM_2025','K_SM_CHANGE_PRINTED','K_REFERRAL_2024',
 'K_REFERRAL_2025','K_TECH_2024','K_TECH_2025')},
 **{k:('USD_million','reported_interim') for k in (
 'K_Q2_SM_2025','K_Q2_SM_2026','K_Q2_SBC_2025','K_Q2_SBC_2026',
 'K_Q2_OP_2025','K_Q2_OP_2026')},
 **{k:('USD_million','issuer_adjusted') for k in ('K_Q2_ADJ_SM_2025','K_Q2_ADJ_SM_2026')},
 **{k:('calendar_days','attributed_buyer_claim') for k in ('K_CYCLE_OLD','K_CYCLE_NEW')},
 'K_IMAGE_SAVING_Q1':('USD_million','attributed_buyer_claim'),
 **{k:('USD_million_per_year','attributed_buyer_claim') for k in ('K_IMAGE_RUNRATE','K_AGENCY_RUNRATE')},
 **{k:('fraction','research_assumption') for k in ('A_N_ATTRIBUTION','A_N_HALF_USE')},
 **{k:('GBP','research_assumption') for k in ('A_N_EXTRA','A_N_BASE')},
 **{k:('USD_million','research_assumption') for k in ('A_K_EXTRA_LOW','A_K_EXTRA_HIGH')},
}

@dataclass(frozen=True)
class Observation:
    value: Decimal
    unit: str
    status: str
    source_id: str
    period: str


def load_inputs(path: Path) -> dict[str, Observation]:
    """Reject incomplete provenance, duplicate keys, unit drift and status promotion."""
    path = Path(path)
    data: dict[str, Observation] = {}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError('Unexpected CSV header or column order')
        for lineno, row in enumerate(reader, 2):
            if None in row or any(not str(row.get(k) or '').strip() for k in FIELDS):
                raise ValueError(f'Incomplete row/provenance at line {lineno}')
            key = row['id']
            if key not in SCHEMA or key in data:
                raise ValueError(f'Unknown or duplicate id: {key}')
            if (row['unit'],row['status']) != SCHEMA[key] or row['status'] not in ALLOWED_STATUS:
                raise ValueError(f'Unit or evidence-status mismatch for {key}')
            try:
                value = D(row['value'])
            except InvalidOperation as exc:
                raise ValueError(f'Invalid number for {key}') from exc
            if not value.is_finite():
                raise ValueError(f'Nonfinite input: {key}')
            if value < 0 and not key.startswith('K_Q2_OP_'):
                raise ValueError(f'Unexpected negative input: {key}')
            if row['unit']=='fraction' and not D(0) <= value <= D(1):
                raise ValueError(f'Fraction outside [0,1]: {key}')
            if row['unit'] in ('days','months','reports','recorded_hours','calendar_days'):
                if value <= 0 or value != value.to_integral_value():
                    raise ValueError(f'Positive integer required for {key}')
            if row['status']=='research_assumption' and row['source_id'] != 'MODEL':
                raise ValueError(f'Assumption without MODEL provenance: {key}')
            if not (row['source_url'].startswith('https://') or
                    row['source_url'].startswith('report.md#')):
                raise ValueError(f'Unsupported source locator: {key}')
            data[key] = Observation(value,row['unit'],row['status'],row['source_id'],row['period'])
    if set(data) != set(SCHEMA):
        raise ValueError(f'Missing inputs: {sorted(set(SCHEMA)-set(data))}')
    for key in ('N_FEE','N_HOURS','N_MONTHS','N_FOLLOWON_MONTHS','K_SM_2023','K_SM_2024',
                'K_AGENCY_2022','K_Q2_SM_2025'):
        if data[key].value <= 0:
            raise ValueError(f'Nonpositive denominator/fee: {key}')
    return data


def capacity_test(fee: Decimal, extra: Decimal, uplift: Decimal,
                  base_resources: Decimal) -> dict[str, Decimal | None]:
    """Two alternatives, never additive: expand output or save divisible resources.

    Equal-quality output, recurring uplift and comparable period are assumptions.
    extra must include only burdens not already in fee or the net uplift.
    Returned resource thresholds are not estimates of the buyer's actual budget.
    """
    if any(not x.is_finite() or x < 0 for x in (fee,extra,uplift,base_resources)):
        raise ValueError('Finite nonnegative inputs required')
    cost = fee + extra
    if uplift == 0:
        return dict(expansion_threshold=None, same_output_threshold=None,
                    resource_fraction=D(0), expansion_room=-cost, same_output_room=-cost)
    fraction = uplift/(1+uplift)
    return dict(expansion_threshold=cost/uplift,
                same_output_threshold=cost/fraction, resource_fraction=fraction,
                expansion_room=base_resources*uplift-cost,
                same_output_room=base_resources*fraction-cost)


def bundle_ratio(fee: Decimal, capacity: Decimal, used_fraction: Decimal) -> Decimal:
    """Fee per used recording hour with entire bundled fee allocated to audio.

    This is not the vendor's stand-alone audio price or an observed usage result.
    """
    if not all(x.is_finite() for x in (fee,capacity,used_fraction)):
        raise ValueError('Nonfinite bundle input')
    if fee < 0 or capacity <= 0 or not D(0) < used_fraction <= D(1):
        raise ValueError('Invalid fee/capacity/use fraction')
    return fee/(capacity*used_fraction)


def results(data: Mapping[str, Observation]) -> dict[str, Decimal | None]:
    v = lambda key: data[key].value
    with localcontext() as ctx:
        ctx.prec=32
        fee, q, base = v('N_FEE'),v('N_THERAPY_UPLIFT'),v('A_N_BASE')
        r: dict[str, Decimal | None]={}
        for label,extra,uplift in (
            ('n_full_fee_only',D(0),q),
            ('n_full_with_extra',v('A_N_EXTRA'),q),
            ('n_half_with_extra',v('A_N_EXTRA'),q*v('A_N_ATTRIBUTION'))):
            for key,value in capacity_test(fee,extra,uplift,base).items():
                r[label+'_'+key]=value
        r['n_bundle_full_use_GBP_per_hour']=bundle_ratio(fee,v('N_HOURS'),D(1))
        r['n_bundle_half_use_GBP_per_hour']=bundle_ratio(fee,v('N_HOURS'),v('A_N_HALF_USE'))
        r['n_notice_window_days']=v('N_REPRICE')-v('N_NONRENEWAL')
        # A matching amount is not an invoice join or a tax-recovery determination.
        r['n_secondary_payment_above_fee_GBP']=v('N_REPORTED_PAYMENT')-fee
        r['n_secondary_payment_to_fee_ratio']=v('N_REPORTED_PAYMENT')/fee
        r['n_followon_value_ratio_unmatched_scope']=v('N_FOLLOWON_FEE')/fee
        r['n_original_GBP_per_term_month']=fee/v('N_MONTHS')
        r['n_followon_GBP_per_term_month_unmatched_scope']=v('N_FOLLOWON_FEE')/v('N_FOLLOWON_MONTHS')
        r['k_q1_AI_attributed_reduction_USDm']=v('K_SUPPLIER_REDUCTION')*v('K_AI_ATTRIBUTION')
        r['k_q1_other_unassigned_reduction_USDm']=v('K_SUPPLIER_REDUCTION')-r['k_q1_AI_attributed_reduction_USDm']
        r['k_q1_claim_less_low_extra_USDm']=r['k_q1_AI_attributed_reduction_USDm']-v('A_K_EXTRA_LOW')
        r['k_q1_claim_less_high_extra_USDm']=r['k_q1_AI_attributed_reduction_USDm']-v('A_K_EXTRA_HIGH')
        r['k_agency_reduction_2022_2024_USDm']=v('K_AGENCY_2022')-v('K_AGENCY_2024')
        r['k_agency_reduction_fraction']=r['k_agency_reduction_2022_2024_USDm']/v('K_AGENCY_2022')
        r['k_marketing_change_2023_2024_USDm']=v('K_SM_2024')-v('K_SM_2023')
        r['k_marketing_change_2024_2025_USDm']=v('K_SM_2025')-v('K_SM_2024')
        r['k_marketing_endpoint_vs_printed_change_USDm']=r['k_marketing_change_2024_2025_USDm']-v('K_SM_CHANGE_PRINTED')
        r['k_referral_change_2024_2025_USDm']=v('K_REFERRAL_2025')-v('K_REFERRAL_2024')
        r['k_other_marketing_2024_USDm']=v('K_SM_2024')-v('K_REFERRAL_2024')
        r['k_other_marketing_2025_USDm']=v('K_SM_2025')-v('K_REFERRAL_2025')
        r['k_other_marketing_change_USDm']=r['k_other_marketing_2025_USDm']-r['k_other_marketing_2024_USDm']
        r['k_Q2_marketing_change_USDm']=v('K_Q2_SM_2026')-v('K_Q2_SM_2025')
        r['k_Q2_SBC_component_change_USDm']=v('K_Q2_SBC_2026')-v('K_Q2_SBC_2025')
        r['k_Q2_other_change_USDm']=r['k_Q2_marketing_change_USDm']-r['k_Q2_SBC_component_change_USDm']
        r['k_Q2_2026_displayed_subtraction_USDm']=v('K_Q2_SM_2026')-v('K_Q2_SBC_2026')
        r['k_Q2_2026_displayed_minus_adjusted_USDm']=r['k_Q2_2026_displayed_subtraction_USDm']-v('K_Q2_ADJ_SM_2026')
        r['k_Q2_operating_result_change_USDm']=v('K_Q2_OP_2026')-v('K_Q2_OP_2025')
        r['k_cycle_calendar_days_reduced']=v('K_CYCLE_OLD')-v('K_CYCLE_NEW')
        r['k_cycle_calendar_fraction_reduced']=r['k_cycle_calendar_days_reduced']/v('K_CYCLE_OLD')
        return r


def run_tests(data: Mapping[str, Observation]) -> int:
    """Frozen arithmetic, resource conservation and non-conflation checks."""
    r=results(data); count=0
    def check(condition: bool, message: str) -> None:
        nonlocal count
        count += 1
        if not condition: raise AssertionError(message)
    def near(key: str, expected: str, tolerance: str='0.000001') -> None:
        value=r[key]
        check(value is not None and abs(value-D(expected))<=D(tolerance),key)
    for key,expected in {
      'n_full_fee_only_expansion_threshold':'342857.142857142857',
      'n_full_fee_only_same_output_threshold':'390857.142857142857',
      'n_full_with_extra_expansion_threshold':'428571.428571428571',
      'n_full_with_extra_same_output_threshold':'488571.428571428571',
      'n_half_with_extra_expansion_threshold':'857142.857142857143',
      'n_half_with_extra_same_output_threshold':'917142.857142857143',
      'n_full_with_extra_expansion_room':'10000',
      'n_full_with_extra_same_output_room':'1403.508771929825',
      'n_half_with_extra_expansion_room':'-25000',
      'n_half_with_extra_same_output_room':'-27289.719626168224',
      'n_bundle_full_use_GBP_per_hour':'4.033613445378151',
      'n_bundle_half_use_GBP_per_hour':'8.067226890756303',
      'n_notice_window_days':'30',
      'n_secondary_payment_above_fee_GBP':'9600',
      'n_secondary_payment_to_fee_ratio':'1.2',
      'n_followon_value_ratio_unmatched_scope':'1.0625',
      'n_original_GBP_per_term_month':'4000',
      'n_followon_GBP_per_term_month_unmatched_scope':'10200',
      'k_q1_AI_attributed_reduction_USDm':'2.59',
      'k_q1_other_unassigned_reduction_USDm':'4.41',
      'k_q1_claim_less_low_extra_USDm':'0.59',
      'k_q1_claim_less_high_extra_USDm':'-0.41',
      'k_agency_reduction_2022_2024_USDm':'25',
      'k_marketing_change_2023_2024_USDm':'-53',
      'k_marketing_change_2024_2025_USDm':'86',
      'k_marketing_endpoint_vs_printed_change_USDm':'-1',
      'k_referral_change_2024_2025_USDm':'28',
      'k_other_marketing_2024_USDm':'247',
      'k_other_marketing_2025_USDm':'305',
      'k_other_marketing_change_USDm':'58',
      'k_Q2_marketing_change_USDm':'35',
      'k_Q2_SBC_component_change_USDm':'8',
      'k_Q2_other_change_USDm':'27',
      'k_Q2_2026_displayed_subtraction_USDm':'110',
      'k_Q2_2026_displayed_minus_adjusted_USDm':'-1',
      'k_Q2_operating_result_change_USDm':'73',
      'k_cycle_calendar_days_reduced':'35',
    }.items(): near(key,expected)
    check(r['k_referral_change_2024_2025_USDm']+r['k_other_marketing_change_USDm']==r['k_marketing_change_2024_2025_USDm'],'Annual expense conservation')
    check(r['k_Q2_SBC_component_change_USDm']+r['k_Q2_other_change_USDm']==r['k_Q2_marketing_change_USDm'],'Quarter expense conservation')
    check(r['k_q1_AI_attributed_reduction_USDm']+r['k_q1_other_unassigned_reduction_USDm']==data['K_SUPPLIER_REDUCTION'].value,'Attribution not total saving')
    check(r['n_full_with_extra_expansion_threshold']>r['n_full_fee_only_expansion_threshold'],'Extra costs increase hurdle')
    check(r['n_full_with_extra_same_output_threshold']>r['n_full_with_extra_expansion_threshold'],'Savings and expansion differ')
    check(capacity_test(D(48000),D(0),D(0),D(500000))['expansion_threshold'] is None,'No fabricated zero-effect payback')
    check(data['N_REPORTED_PAYMENT'].status=='secondary_payment_record','No receipt promotion')
    check(data['N_THERAPY_UPLIFT'].status=='buyer_reported','No causal promotion')
    for args in ((D(-1),D(10),D(1)),(D(1),D(0),D(1)),(D(1),D(10),D(0)),(D(1),D(10),D('1.1'))):
        try: bundle_ratio(*args)
        except ValueError: check(True,'Rejected invalid bundle')
        else: check(False,'Accepted invalid bundle')
    return count


def render_figure(data: Mapping[str, Observation], destination: Path) -> None:
    """Observed expense decomposition, not allocation of the gain to AI suppliers."""
    import matplotlib.pyplot as plt
    r=results(data)
    start=float(data['K_SM_2024'].value)
    inc1=float(r['k_referral_change_2024_2025_USDm'])
    inc2=float(r['k_other_marketing_change_USDm'])
    end=float(data['K_SM_2025'].value)
    fig,ax=plt.subplots(figsize=(10.8,6.1))
    ax.bar([0,1,2,3],[start,inc1,inc2,end],bottom=[0,start,start+inc1,0],width=.62)
    ax.set_xticks([0,1,2,3],['2024 total','Referral commissions\nchange','Remaining expense\nchange','2025 total'])
    ax.set_ylabel('USD millions; reported rounded expense')
    ax.set_ylim(0,470)
    ax.set_title('Klarna: total marketing expense is not an AI-cost measure',pad=22)
    for i,label,y in ((0,'328',start),(1,'+28',start+inc1),(2,'+58',end),(3,'414',end)):
        ax.text(i,y+9,label,ha='center',fontsize=12)
    fig.text(.10,.095,'Klarna: 328 + 28 + 58 = 414. The remaining basket is not AI spending or cash.\n'
             'The issuer separately prints an 87 million increase; this bridge uses its rounded endpoints.\n'
             'Source: 2025 Annual Report, income statement and Note 2; report §6 and data.csv.',fontsize=9)
    fig.subplots_adjust(left=.10,right=.98,bottom=.27,top=.85)
    with plt.rc_context({'svg.fonttype':'none','svg.hashsalt':'buyer-marketing-budget'}):
        fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Buyer-budget calculations'})
    # Keep the drawing inspectable and give it a concise accessible description.
    import xml.etree.ElementTree as ET
    tree=ET.parse(destination); root=tree.getroot()
    ns='http://www.w3.org/2000/svg'
    root.set('role','img'); root.set('aria-labelledby','buyer-title buyer-desc')
    title=ET.Element('{'+ns+'}title',{'id':'buyer-title'})
    title.text='Klarna marketing expense: 328 plus 28 plus 58 equals 414 million dollars'
    desc=ET.Element('{'+ns+'}desc',{'id':'buyer-desc'})
    desc.text=('2024 to 2025 rounded reported sales and marketing expense. Referral commissions increased '
               '28 million and the remaining expense basket 58 million. Neither is an AI-only cash measure. '
               'The issuer separately prints an 87 million total change because values are rounded.')
    root.insert(0,desc); root.insert(0,title)
    # Convert Matplotlib CSS declarations to SVG presentation attributes.
    import re
    for element in list(root.iter()):
        for child in list(element):
            if child.tag in ('{'+ns+'}style', '{'+ns+'}metadata'):
                element.remove(child)
        declarations = element.attrib.pop('style', '')
        for declaration in declarations.split(';'):
            if ':' not in declaration:
                continue
            key, value = (part.strip() for part in declaration.split(':', 1))
            if key == 'font':
                match = re.fullmatch(r'(?:(\d+)\s+)?([\d.]+)px\s+(.+)', value)
                if match is None:
                    raise ValueError('Unsupported SVG font shorthand: ' + value)
                if match[1]:
                    element.set('font-weight', match[1])
                element.set('font-size', match[2])
                element.set('font-family', match[3])
            else:
                element.set(key, value)
    root.set('stroke-linejoin', 'round')
    root.set('stroke-linecap', 'butt')
    ET.register_namespace('',ns); ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
    tree.write(destination,encoding='utf-8',xml_declaration=True)
    plt.close(fig)


def default_data_path() -> Path:
    here=Path(__file__).resolve()
    prefixed=here.with_name(here.name.replace('calculations.py','data.csv'))
    canonical=here.with_name('data.csv')
    for path in (prefixed,canonical):
        if path.is_file(): return path
    raise FileNotFoundError('Place data.csv or the matching prefixed CSV beside this script, or use --data')


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,help='Exact source-linked input CSV')
    parser.add_argument('--figure',type=Path,help='Optional SVG path (requires matplotlib)')
    args=parser.parse_args()
    try:
        data=load_inputs(args.data or default_data_path())
        count=run_tests(data)
        print(f'{len(data)} records; {count} built-in checks passed.')
        for key,value in results(data).items():
            print(f'{key}: '+('not identified at zero assumed effect' if value is None else f'{value:.6f}'))
        if args.figure: render_figure(data,args.figure)
    except (OSError,ValueError,AssertionError,InvalidOperation) as exc:
        parser.exit(2,f'Input/calculation error: {exc}\n')

if __name__=='__main__': main()
