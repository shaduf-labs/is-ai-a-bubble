#!/usr/bin/env python3
"""Document-service economics: conditional remaining-cost budgets, not company margins.

Run beside efficiency-data.csv or the delivery-prefixed data file. No network or paid API.
    python efficiency-calculations.py --data efficiency-data.csv
    python efficiency-calculations.py --figure efficiency-remaining-cost-budget.svg

All amounts are USD unless labeled otherwise. Benchmark scores and source-conflict
rows never serve as acceptance rates or operating-cost inputs. Reported timing is
combined with a separately dated posted rental offer; future volumes and resource
allocations are explicit scenarios. Optional figure generation needs matplotlib.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Mapping

STATUSES = {'reported_measurement', 'posted_tariff', 'source_conflict',
            'reported_estimate', 'research_assumption', 'contractual_terms'}
FIELDS = ['id','entity','metric','value','unit','status','observation_period',
          'source_id','source_date','retrieved','source_url','locator','qualification']
# The validation contract prevents silent replacement of units or empirical status.
EXPECTED = {
 'ACL_PAGES':('pages','reported_measurement'),
 'ACL_SECONDS':('seconds','reported_measurement'),
 'ACL_RATE':('USD_per_GPU_hour','posted_tariff'),
 'ACL_TABLE_COST':('USD','source_conflict'),
 'ACL_TABLE_PAGES':('pages','source_conflict'),
 'ACL_MISTRAL_COST':('USD','source_conflict'),
 'ACL_MISTRAL_RATE':('USD_per_1000_pages','posted_tariff'),
 'ACL_SFT_HOURS':('GPU_hours','reported_measurement'),
 'ACL_SYNTH_PAGES':('pages','reported_measurement'),
 'ACL_SYNTH_COST':('USD_per_page','reported_estimate'),
 'ACL_SFT_PAGES':('pages','reported_measurement'),
 'ACL_RL_GPUS':('GPU_count','reported_measurement'),
 'ACL_RL_SEEDS':('count','reported_measurement'),
 'RETRY_OLD':('fraction','reported_estimate'),
 'RETRY_NEW':('fraction','reported_estimate'),
 'PIPELINE_FAILURE':('fraction','reported_estimate'),
 'V1_PAGES':('pages','reported_measurement'),
 'V1_L40_SECONDS':('seconds','reported_measurement'),
 'V1_H100_SECONDS':('seconds','reported_measurement'),
 'V1_L40_RATE':('USD_per_GPU_hour','posted_tariff'),
 'V1_H100_RATE':('USD_per_GPU_hour','posted_tariff'),
 'V1_RUN_HOURS':('node_hours','reported_measurement'),
 'V1_ALL_HOURS':('node_hours','reported_measurement'),
 'V1_TRAIN_GPUS':('GPU_count','reported_measurement'),
 'V1_INPUT_TOKENS':('tokens','reported_measurement'),
 'V1_OUTPUT_TOKENS':('tokens','reported_measurement'),
 'V1_API_IN':('USD_per_million_tokens','posted_tariff'),
 'V1_API_OUT':('USD_per_million_tokens','posted_tariff'),
 'V1_DOWNSTREAM_BASE':('score_points','reported_measurement'),
 'V1_DOWNSTREAM_OLM':('score_points','reported_measurement'),
 'RENT_H100':('USD_per_GPU_hour','posted_tariff'),
 'RENT_B200':('USD_per_GPU_hour','posted_tariff'),
 'RENT_L40':('USD_per_GPU_hour','posted_tariff'),
 'OCR3_STANDARD':('USD_per_1000_pages','posted_tariff'),
 'OCR4_STANDARD':('USD_per_1000_pages','posted_tariff'),
 'BATCH_FACTOR':('fraction','posted_tariff'),
 'COPILOT_CREDIT_VALUE':('USD_per_credit','contractual_terms'),
 'COPILOT_BUSINESS_CREDITS':('credits','contractual_terms'),
 'YEAR_HOURS':('hours_per_year','research_assumption'),
 'PRODUCTIVE_LIMIT':('fraction','research_assumption'),
 'NET_REALIZATION':('fraction','research_assumption'),
 'NET_REALIZATION_STRESS':('fraction','research_assumption'),
 'PRICE_REFERENCE':('USD_per_page','research_assumption'),
 'N_SMALL':('pages_per_year','research_assumption'),
 'N_SHARED_BASE':('pages_per_year','research_assumption'),
 'N_MAIN':('pages_per_year','research_assumption'),
 'PRICE_FAVORABLE_FACTOR':('fraction','research_assumption'),
 'PRICE_EROSION_FACTOR':('fraction','research_assumption'),
 'REFRESH_RUNS':('count','research_assumption'),
 'REVIEW_WAGE':('USD_per_person_hour','research_assumption'),
 'EXTRA_REVIEW_SECONDS':('seconds_per_page','research_assumption'),
 'INTERVENTION_SECONDS':('seconds','research_assumption'),
 'RETRY_DURATION_FACTOR':('duration_ratio','research_assumption'),
 'STANDBY_NODES':('GPU_count','research_assumption'),
 'ACCEPTED_YIELD_EXAMPLE':('fraction','research_assumption'),
}

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    entity: str
    period: str
    source: str
    qualification: str

Inputs = Mapping[str, Input]

def finite(value: float, name: str, *, positive: bool=False) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f'{name} must be finite and {"positive" if positive else "nonnegative"}')
    return value

def fraction(value: float, name: str, *, positive: bool=False) -> float:
    finite(value, name, positive=positive)
    if value > 1:
        raise ValueError(f'{name} must not exceed 1')
    return value

def count(value: int, name: str, *, positive: bool=False) -> int:
    finite(value, name, positive=positive)
    if int(value) != value:
        raise ValueError(f'{name} must be an integer')
    return int(value)

def load_inputs(path: Path) -> dict[str, Input]:
    values: dict[str, Input] = {}
    with Path(path).open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError('Unexpected ledger schema/order')
        for line, row in enumerate(reader, 2):
            if None in row or any(not row.get(k, '').strip() for k in FIELDS):
                raise ValueError(f'Blank or malformed field on line {line}')
            key = row['id']
            if key in values or key not in EXPECTED:
                raise ValueError(f'Duplicate or unknown input: {key}')
            if (row['unit'], row['status']) != EXPECTED[key] or row['status'] not in STATUSES:
                raise ValueError(f'Unit/status mismatch: {key}')
            v = finite(float(row['value']), key)
            if row['unit'] == 'fraction':
                fraction(v,key)
            if row['unit'] in {'pages','tokens','GPU_count','count','credits'}:
                count(v,key)
            if row['source_id'] == 'MODEL' and row['status'] != 'research_assumption':
                raise ValueError('A model assumption cannot become observed')
            if row['source_id'] != 'MODEL' and not row['source_url'].startswith('https://'):
                raise ValueError(f'External source URL missing: {key}')
            values[key] = Input(v,row['unit'],row['status'],row['entity'],
                                row['observation_period'],row['source_id'],row['qualification'])
    if set(values) != set(EXPECTED):
        raise ValueError(f'Missing inputs: {sorted(set(EXPECTED)-set(values))}')
    for key in ['ACL_PAGES','ACL_SECONDS','YEAR_HOURS','PRODUCTIVE_LIMIT','REVIEW_WAGE']:
        finite(values[key].value,key,positive=True)
    return values

def get(data: Inputs, key: str, *, diagnostic: bool=False) -> float:
    item = data[key]
    if item.status == 'source_conflict' and not diagnostic:
        raise ValueError(f'{key} is preserved for source reconciliation, not operating use')
    return item.value

def timed_cost(pages: float, seconds: float, rental_per_hour: float) -> float:
    """Rental dollars per submitted page, including reported elapsed processing."""
    finite(pages,'pages',positive=True); finite(seconds,'seconds',positive=True)
    finite(rental_per_hour,'rental rate')
    return seconds / 3600 * rental_per_hour / pages

def capacity(pages: float, seconds: float, year_hours: float, productive: float,
             active_nodes: int=1) -> float:
    finite(pages,'batch pages',positive=True); finite(seconds,'batch seconds',positive=True)
    finite(year_hours,'year hours',positive=True); fraction(productive,'productive share',positive=True)
    count(active_nodes,'active nodes',positive=True)
    return pages * 3600 / seconds * year_hours * productive * active_nodes

def priced_refresh(data: Inputs) -> float:
    """A priced SFT + synthetic-data subset, emphatically NOT full development."""
    return get(data,'REFRESH_RUNS') * (get(data,'ACL_SFT_HOURS') * get(data,'RENT_B200')
           + get(data,'ACL_SYNTH_PAGES') * get(data,'ACL_SYNTH_COST'))

@dataclass(frozen=True)
class Budget:
    revenue: float
    serving_rent: float
    priced_refresh: float
    extra_review: float
    remaining_cost_budget: float
    submitted_capacity: float

def service_budget(data: Inputs, volume: float, price: float, *, active_nodes: int=1,
                   standby_nodes: int=0, review_seconds: float=0,
                   productive: float|None=None, net_realization: float|None=None,
                   active_only: bool=False) -> Budget:
    finite(volume,'volume'); finite(price,'price'); finite(review_seconds,'review seconds')
    count(active_nodes,'active nodes',positive=True); count(standby_nodes,'standby nodes')
    productive = get(data,'PRODUCTIVE_LIMIT') if productive is None else productive
    realization = get(data,'NET_REALIZATION') if net_realization is None else net_realization
    fraction(realization,'net realization')
    cap = capacity(get(data,'ACL_PAGES'),get(data,'ACL_SECONDS'),get(data,'YEAR_HOURS'),productive,active_nodes)
    if volume > cap + 1e-7:
        raise ValueError('Demand exceeds stipulated productive capacity; add paid capacity or change the assumptions')
    if active_only:
        if standby_nodes:
            raise ValueError('Active-only mode does not include a hot standby; specify a coherent rental mode')
        rent = volume * timed_cost(get(data,'ACL_PAGES'),get(data,'ACL_SECONDS'),get(data,'RENT_H100'))
    else:
        rent = (active_nodes + standby_nodes) * get(data,'YEAR_HOURS') * get(data,'RENT_H100')
    revenue = volume * price * realization
    refresh = priced_refresh(data)
    review = volume * review_seconds / 3600 * get(data,'REVIEW_WAGE')
    return Budget(revenue,rent,refresh,review,revenue-rent-refresh-review,cap)

def accepted_work_cost(accepted_pages: float, accepted_yield: float, price_per_input: float,
                       review_per_input: float, other_total: float) -> float:
    """Failure/retry/rework must be supplied explicitly; a benchmark score is not yield."""
    finite(accepted_pages,'accepted pages',positive=True); fraction(accepted_yield,'accepted yield',positive=True)
    finite(price_per_input,'input price'); finite(review_per_input,'review dollars per input')
    finite(other_total,'other total cost')
    inputs = accepted_pages / accepted_yield
    return (inputs * (price_per_input+review_per_input) + other_total) / accepted_pages

def review_allowance_seconds(avoided_dollars_per_page: float, wage: float) -> float:
    finite(wage,'resource price',positive=True)
    if not math.isfinite(avoided_dollars_per_page):
        raise ValueError('Nonfinite difference')
    return avoided_dollars_per_page / wage * 3600

def retry_work_factor(page_retry_share: float, one_retry_duration: float) -> float:
    fraction(page_retry_share,'retry share'); finite(one_retry_duration,'retry duration factor')
    return 1 + page_retry_share * one_retry_duration

def calculate(data: Inputs) -> dict[str, float]:
    g=lambda key: get(data,key)
    c=timed_cost(g('ACL_PAGES'),g('ACL_SECONDS'),g('RENT_H100'))
    historical=timed_cost(g('ACL_PAGES'),g('ACL_SECONDS'),g('ACL_RATE'))
    p3=g('OCR3_STANDARD')/1000*g('BATCH_FACTOR')
    p4=g('OCR4_STANDARD')/1000*g('BATCH_FACTOR')
    p=g('PRICE_REFERENCE'); n=g('N_MAIN'); refresh=priced_refresh(data)
    main=service_budget(data,n,p)
    standby=service_budget(data,n,p,standby_nodes=int(g('STANDBY_NODES')))
    review=service_budget(data,n,p,review_seconds=g('EXTRA_REVIEW_SECONDS'))
    both=service_budget(data,n,p,standby_nodes=int(g('STANDBY_NODES')),review_seconds=g('EXTRA_REVIEW_SECONDS'))
    small=service_budget(data,g('N_SMALL'),p)
    active_small=service_budget(data,g('N_SMALL'),p,active_only=True)
    initial=service_budget(data,g('N_SHARED_BASE'),p)
    favorable=service_budget(data,n,p*g('PRICE_FAVORABLE_FACTOR'))
    cap=main.submitted_capacity
    cutprice=p*g('PRICE_EROSION_FACTOR')
    erosion=service_budget(data,cap,cutprice)
    retryold=retry_work_factor(g('RETRY_OLD'),g('RETRY_DURATION_FACTOR'))
    retrynew=retry_work_factor(g('RETRY_NEW'),g('RETRY_DURATION_FACTOR'))
    allow=review_allowance_seconds(p3-c,g('REVIEW_WAGE'))
    out={
      'historical_batch_rent_USD':historical*g('ACL_PAGES'),
      'historical_rent_per_million_USD':historical*1e6,
      'printed_cost_to_reconstructed_batch_ratio':get(data,'ACL_TABLE_COST',diagnostic=True)/(historical*g('ACL_PAGES')),
      'historical_mistral_10000_pages_USD':g('ACL_PAGES')/1000*g('ACL_MISTRAL_RATE'),
      'printed_mistral_to_reconstructed_ratio':get(data,'ACL_MISTRAL_COST',diagnostic=True)/(g('ACL_PAGES')/1000*g('ACL_MISTRAL_RATE')),
      'hybrid_batch_rent_USD':c*g('ACL_PAGES'),
      'hybrid_rent_per_million_USD':c*1e6,
      'timed_pages_per_hour':g('ACL_PAGES')*3600/g('ACL_SECONDS'),
      'raw_annual_pages_one_node':capacity(g('ACL_PAGES'),g('ACL_SECONDS'),g('YEAR_HOURS'),1),
      'scenario_annual_pages_one_node':cap,
      'annual_rent_one_node_USD':g('YEAR_HOURS')*g('RENT_H100'),
      'priced_SFT_reference_USD':g('ACL_SFT_HOURS')*g('RENT_B200'),
      'priced_synthetic_data_reference_USD':g('ACL_SYNTH_PAGES')*g('ACL_SYNTH_COST'),
      'priced_refresh_subset_USD':refresh,
      'OCR3_batch_USD_per_million':p3*1e6,
      'OCR4_batch_USD_per_million':p4*1e6,
      'buyer_extra_cost_allowance_per_million_USD':(p3-c)*1e6,
      'buyer_extra_review_seconds_per_input':allow,
      'inputs_per_additional_30_second_review':g('INTERVENTION_SECONDS')/allow,
      'OCR4_upgrade_avoided_review_seconds':review_allowance_seconds(p4-p3,g('REVIEW_WAGE')),
      'main_extra_review_USD':review.extra_review,
      'main_base_budget_USD':main.remaining_cost_budget,
      'main_standby_budget_USD':standby.remaining_cost_budget,
      'main_review_budget_USD':review.remaining_cost_budget,
      'main_standby_review_budget_USD':both.remaining_cost_budget,
      'small_continuous_budget_USD':small.remaining_cost_budget,
      'small_active_only_budget_USD':active_small.remaining_cost_budget,
      'initial_shared_gain_budget_USD':initial.remaining_cost_budget,
      'favorable_budget_USD':favorable.remaining_cost_budget,
      'favorable_incremental_budget_USD':favorable.remaining_cost_budget-initial.remaining_cost_budget,
      'erosion_revenue_preserving_volume':main.revenue/cutprice,
      'erosion_max_one_node_revenue_USD':erosion.revenue,
      'erosion_max_one_node_budget_USD':erosion.remaining_cost_budget,
      'erosion_two_node_volume_to_preserve_budget':(main.remaining_cost_budget+2*main.serving_rent+refresh)/cutprice,
      'erosion_two_node_required_volume_growth':((main.remaining_cost_budget+2*main.serving_rent+refresh)/cutprice/n)-1,
      'retry_equal_duration_work_ratio':retrynew/retryold,
      'retry_equal_duration_work_reduction':1-retrynew/retryold,
      'retry_equal_duration_capacity_ratio':retryold/retrynew,
      'old_program_to_single_run_ratio':g('V1_ALL_HOURS')/g('V1_RUN_HOURS'),
      'old_L40_rent_per_million_USD':timed_cost(g('V1_PAGES'),g('V1_L40_SECONDS'),g('V1_L40_RATE'))*1e6,
      'old_H100_rent_per_million_USD':timed_cost(g('V1_PAGES'),g('V1_H100_SECONDS'),g('V1_H100_RATE'))*1e6,
      'old_general_API_1288_pages_USD':(g('V1_INPUT_TOKENS')*g('V1_API_IN')+g('V1_OUTPUT_TOKENS')*g('V1_API_OUT'))/1e6,
      'old_downstream_score_difference':g('V1_DOWNSTREAM_OLM')-g('V1_DOWNSTREAM_BASE'),
      'Copilot_Business_credit_billing_value_USD':g('COPILOT_CREDIT_VALUE')*g('COPILOT_BUSINESS_CREDITS'),
      'example_98pct_yield_inputs_for_million_accepted':1e6/g('ACCEPTED_YIELD_EXAMPLE'),
      'example_98pct_OCR3_API_cost_per_million_accepted_USD':1e6*accepted_work_cost(1e6,g('ACCEPTED_YIELD_EXAMPLE'),p3,0,0),
      'break_even_volume_before_remaining_costs_one_node':(main.serving_rent+refresh)/p,
      'main_after_10pct_receipt_discount_budget_USD':service_budget(data,n,p,net_realization=g('NET_REALIZATION_STRESS')).remaining_cost_budget,
    }
    return out

def run_tests(data: Inputs) -> int:
    checks=0
    def ok(condition: bool, message: str) -> None:
        nonlocal checks
        if not condition: raise AssertionError(message)
        checks+=1
    def close(x: float,y: float) -> None:
        ok(math.isclose(x,y,rel_tol=1e-10,abs_tol=1e-7),f'{x} != {y}')
    def rejects(fn) -> None:
        try: fn()
        except (ValueError,KeyError):
            ok(True,'rejected'); return
        raise AssertionError('Invalid argument was accepted')
    r=calculate(data)
    frozen={'historical_batch_rent_USD':1.6491194444444446,
            'hybrid_rent_per_million_USD':183.30361111111114,
            'priced_refresh_subset_USD':391.9,'main_base_budget_USD':53415.7,
            'main_standby_budget_USD':27223.3,'favorable_incremental_budget_USD':8000,
            'small_continuous_budget_USD':-16584.3,'Copilot_Business_credit_billing_value_USD':19,
            'old_program_to_single_run_ratio':22.8125,'historical_mistral_10000_pages_USD':10}
    for k,v in frozen.items():close(r[k],v)
    for key,value in r.items(): ok(math.isfinite(value),f'nonfinite {key}')
    main=service_budget(data,get(data,'N_MAIN'),get(data,'PRICE_REFERENCE'))
    close(main.revenue,main.serving_rent+main.priced_refresh+main.extra_review+main.remaining_cost_budget)
    close(r['main_base_budget_USD']-r['main_standby_budget_USD'],r['annual_rent_one_node_USD'])
    close(r['main_base_budget_USD']-r['main_review_budget_USD'],r['main_extra_review_USD'])
    close(r['buyer_extra_cost_allowance_per_million_USD']+r['hybrid_rent_per_million_USD'],r['OCR3_batch_USD_per_million'])
    close(r['retry_equal_duration_work_ratio']*r['retry_equal_duration_capacity_ratio'],1)
    close(accepted_work_cost(1000,1,.001,0,0),.001)
    close(accepted_work_cost(1000,.5,.001,0,0),.002)
    close(accepted_work_cost(1000,1,.001,.002,5),.008)
    ok(r['erosion_revenue_preserving_volume']>r['scenario_annual_pages_one_node'],'capacity mismatch must be visible')
    ok(r['erosion_two_node_volume_to_preserve_budget']<2*r['scenario_annual_pages_one_node'],'two-node path must fit')
    ok(r['example_98pct_yield_inputs_for_million_accepted']>1e6,'failure inputs not free')
    ok(EXPECTED['V1_DOWNSTREAM_OLM'][0]=='score_points','quality-score unit kept')
    rejects(lambda:get(data,'ACL_TABLE_COST'))
    rejects(lambda:timed_cost(0,1,1))
    rejects(lambda:timed_cost(100,-1,1))
    rejects(lambda:accepted_work_cost(100,0,.01,0,0))
    rejects(lambda:accepted_work_cost(100,1.01,.01,0,0))
    rejects(lambda:service_budget(data,1e12,.001))
    rejects(lambda:service_budget(data,10,.001,active_nodes=1.5))
    rejects(lambda:service_budget(data,10,.001,active_only=True,standby_nodes=1))
    rejects(lambda:service_budget(data,10,.001,net_realization=1.1))
    rejects(lambda:capacity(100,1,8760,0))
    rejects(lambda:retry_work_factor(1.2,1))
    rejects(lambda:review_allowance_seconds(.1,0))
    return checks

def render_figure(data: Inputs, destination: Path) -> None:
    import matplotlib.pyplot as plt
    import xml.etree.ElementTree as ET
    r=calculate(data)
    labels=['One active GPU', '+ One passive hot spare', '+ Additional review only', '+ Hot spare and review']
    vals=[r['main_base_budget_USD'],r['main_standby_budget_USD'],r['main_review_budget_USD'],r['main_standby_review_budget_USD']]
    fig,ax=plt.subplots(figsize=(11.5,6.5))
    ax.barh(range(4),[v/1000 for v in vals])
    ax.invert_yaxis();ax.set_yticks(range(4),labels)
    ax.axvline(0,linewidth=.8)
    ax.set_xlim(-29,68)
    ax.set_xlabel('Annual amount left for all other costs and any surplus (USD thousands)')
    for i,v in enumerate(vals):
        ax.text(v/1000+(1.0 if v>=0 else -1.0),i,f'{v/1000:,.1f}',
                ha='left' if v>=0 else 'right',va='center')
    fig.suptitle('Cheap serving leaves a finite budget—not an observed profit',fontsize=15,x=.03,ha='left')
    fig.text(.03,.89,'Conditional operator: 80 million submitted pages/year, $0.001/page collected, one active H100.',fontsize=10)
    fig.text(.03,.08,'All rows pay continuous GPU rent and a $392 priced development subset. Full development, support,\n'
                       'security, taxes and other costs remain to be paid. Review stress: 0.05 extra seconds/page at $40/hour.\n'
                       'Historical timed batch + October 6, 2026 offers; 75% productive-time ceiling. No observed paid volume.\n'
                       'Sources and equations: report §§4–7; data.csv; calculations.py.',fontsize=9)
    fig.subplots_adjust(left=.29,right=.97,bottom=.27,top=.81)
    with plt.rc_context({'svg.fonttype':'none','svg.hashsalt':'document-full-cost-budget'}):
        fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Is AI a Bubble? Document-service calculations'})
    plt.close(fig)
    tree=ET.parse(destination);root=tree.getroot();ns='http://www.w3.org/2000/svg'
    root.set('role','img');root.set('aria-labelledby','budget-title budget-desc')
    title=ET.Element(f'{{{ns}}}title',id='budget-title');title.text='Conditional document operator: remaining annual cost budget'
    desc=ET.Element(f'{{{ns}}}desc',id='budget-desc')
    desc.text=('At 80 million input pages and $0.001 collected per page, continuous H100 rent and the limited priced refresh '
               'leave $53,415.70. Adding a hot spare leaves $27,223.30; extra review alone leaves $8,971.26; '
               'both leave minus $17,221.14. These are conditional budgets before other required costs, not observed margins.')
    root.insert(0,desc);root.insert(0,title)
    # Local presentation attributes keep the generated figure usable under a strict
    # content-security policy; this does not alter any numerical geometry.
    root.set('stroke-linejoin','round'); root.set('stroke-linecap','butt')
    for parent in root.iter():
        for child in list(parent):
            if child.tag in {f'{{{ns}}}metadata', f'{{{ns}}}style'}:
                parent.remove(child)
    for element in root.iter():
        inline_style = element.attrib.pop('style', None)
        if inline_style:
            for declaration in inline_style.split(';'):
                if ':' in declaration:
                    key, value = declaration.split(':', 1)
                    element.set(key.strip(), value.strip())
    tree.write(destination,encoding='utf-8',xml_declaration=True)

def locate_data(explicit: str|None) -> Path:
    if explicit:return Path(explicit)
    folder=Path(__file__).resolve().parent
    for name in [Path(__file__).name.replace('calculations.py','data.csv'),'efficiency-data.csv','data.csv']:
        p=folder/name
        if p.is_file():return p
    raise FileNotFoundError('Place the paired efficiency-data.csv beside this script or supply --data')

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data');parser.add_argument('--figure',type=Path)
    args=parser.parse_args()
    try:
        data=load_inputs(locate_data(args.data));checks=run_tests(data)
        print(json.dumps({'input_records':len(data),'built_in_checks':checks,'results':calculate(data)},indent=2,sort_keys=True))
        if args.figure:render_figure(data,args.figure)
    except (ValueError, OSError, KeyError, AssertionError) as error:
        parser.exit(2,f'Error: {error}\n')
if __name__=='__main__':main()
