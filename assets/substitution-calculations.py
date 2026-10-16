#!/usr/bin/env python3
"""Reproduce the bounded substitution tests. Standard library only; no network.

The source reduction is a historical author-reported, rounded benchmark result.
Contract and capacity scenarios are research conditions, NOT customer invoices.
Run substitution-calculations.py beside substitution-data.csv, or pass --data.
The matching prefixed pair also works. --self-test runs the supplied local tests.
"""
from __future__ import annotations
from decimal import Decimal, localcontext, ROUND_CEILING
from pathlib import Path
import argparse
import csv
import json
import sys
import unittest
import tempfile
from decimal import InvalidOperation

D = Decimal


def reconstruct(reduction: D, saving: D, images: D) -> dict[str, D]:
    """Reconstruct the rounded historical cost scaffold."""
    if not D(0) < reduction < D(1) or saving <= 0 or images <= 0:
        raise ValueError('Need 0 < reduction < 1 and positive saving/images')
    old = saving / reduction
    new = old - saving
    return {'old': old, 'new': new, 'old_per_image': old/images,
            'new_per_image': new/images}


def contract_cash(old: D, new: D, horizon: D, locked: D,
                  migration: D = D(0), reuse: D = D(0)) -> dict[str, D]:
    """Compare no-upfront cash. `reuse` applies only to the stranded-family case.

    Any reuse of portable-plan allowance needs its own eligible-usage account;
    it is excluded here rather than credited from a different contract's saving.
    """
    if (old <= 0 or new <= 0 or horizon <= 0 or not D(0) <= locked <= horizon
            or migration < 0 or reuse < 0):
        raise ValueError('Invalid cost, time, migration or independently avoided cash')
    f = locked / horizon
    commitment = f * old
    fresh = new + migration
    stranded = commitment + new + migration - reuse
    # reuse is avoided outside cash from the abandoned family-specific entitlement.
    # It is NOT automatically the same benefit under a different portable contract.
    portable = max(commitment, f * new) + (1-f)*new + migration
    wait = commitment + (1-f)*new + migration
    return {'stay_cost': old, 'locked_commitment': commitment,
            'fresh_cost': fresh, 'fresh_saving': old-fresh,
            'stranded_cost': stranded, 'stranded_saving': old-stranded,
            'portable_cost': portable, 'portable_saving': old-portable,
            'wait_cost': wait, 'wait_saving': old-wait,
            'stranded_break_even_locked_months': horizon*(old-new-migration+reuse)/old}


def fleet_cost(service_ratio: D, old_seconds: D, extra_seconds: D,
               baseline_load: D, standby: int, acceptance_ratio: D = D(1)) -> dict[str, D | int]:
    if (service_ratio <= 0 or old_seconds <= 0 or extra_seconds < 0
            or baseline_load <= 0 or acceptance_ratio <= 0 or not isinstance(standby, int)
            or isinstance(standby, bool) or standby < 0):
        raise ValueError('Invalid service ratio, measured/assumed time, load or standby')
    theta = (old_seconds + extra_seconds) / old_seconds
    old_active = int(baseline_load.to_integral_value(rounding=ROUND_CEILING))
    new_active = int((baseline_load*theta/acceptance_ratio).to_integral_value(rounding=ROUND_CEILING))
    old_replicas = old_active + standby
    new_replicas = new_active + standby
    tariff_ratio = service_ratio/theta
    return {'time_ratio': theta, 'accepted_work_time_ratio': theta/acceptance_ratio, 'implied_tariff_ratio': tariff_ratio,
            'old_active': old_active, 'new_active': new_active,
            'old_replicas': old_replicas, 'new_replicas': new_replicas,
            'billed_ratio': D(new_replicas)/D(old_replicas)*tariff_ratio,
            'old_capacity_boundary_for_two_new_active': D(2)*acceptance_ratio/theta}


def concession(old: D, new: D, migration: D, discount: D) -> dict[str, D]:
    if old <= 0 or new <= 0 or migration < 0 or not D(0) <= discount <= D(1):
        raise ValueError('Invalid cost, migration or concession')
    allowance = old*(1-discount)-new
    return {'remaining_allowance': allowance,
            'saving_after_migration': allowance-migration,
            'matching_discount': max(D(0), 1-(new+migration)/old)}


FIELDS = ('id', 'value', 'unit', 'status', 'period', 'entity', 'source_id',
          'source_url', 'locator', 'notes')
STATUSES = {'reported_measurement', 'reported_projection', 'reported_method',
            'unobserved', 'published_specification', 'published_terms',
            'published_price_change', 'research_assumption', 'reported_financial',
            'reported_contract', 'buyer_reported_deployment', 'buyer_forecast'}


def read_data(path: Path) -> dict[str, dict[str, str | D | None]]:
    data = {}
    with path.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError('CSV header does not match the documented ledger schema')
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'Line {line}: inconsistent number of cells')
            if any(not row[k].strip() for k in FIELDS if k not in ('value','source_url')):
                raise ValueError(f'Line {line}: missing metadata')
            key, status = row['id'], row['status']
            if key in data or status not in STATUSES:
                raise ValueError(f'Line {line}: duplicate id or unsupported evidence status')
            if status != 'research_assumption' and not row['source_url'].startswith('https://'):
                raise ValueError(f'Line {line}: sourced observation lacks a source URL')
            if status == 'unobserved':
                if row['value'] != '':
                    raise ValueError(f'Line {line}: unobserved must remain blank')
                row['value'] = None
            else:
                try:
                    value = D(row['value'])
                except InvalidOperation as exc:
                    raise ValueError(f'Line {line}: nonnumeric value') from exc
                if not value.is_finite():
                    raise ValueError(f'Line {line}: nonfinite value')
                row['value'] = value
            data[key] = row
    if not data:
        raise ValueError('Empty ledger')
    return data


def number(data: dict, key: str, unit: str) -> D:
    if key not in data or data[key].get('unit') != unit:
        raise ValueError(f'Missing input or incorrect unit: {key} ({unit})')
    value = data[key].get('value')
    if not isinstance(value, D) or not value.is_finite():
        raise ValueError(f'{key} is unobserved or not a finite number; do not replace it with zero')
    return value


def financial_bridge(opening: D, additions: D, depreciation: D, closing: D) -> dict[str, D]:
    return {'net_increase': closing-opening,
            'additions_less_depreciation': additions-depreciation,
            'unallocated_residual': closing-opening-additions+depreciation}


class ResearchTests(unittest.TestCase):
    def test_reported_projection_reconciles(self):
        x = reconstruct(D('.175'), D('14353'), D('10000000'))
        self.assertAlmostEqual(x['old'] - x['new'], D('14353'), places=18)
        self.assertAlmostEqual(x['new'] / x['old'], D('.825'), places=18)

    def test_family_commitment_can_reverse_saving(self):
        r = contract_cash(D(100), D('82.5'), D(12), D(3))
        self.assertEqual(r.get('stranded_saving'), D('-7.5'))

    def test_portability_does_not_refund_unused_commitment(self):
        r = contract_cash(D(100), D('82.5'), D(12), D(3))
        self.assertEqual(r.get('portable_saving'), D('13.125'))

    def test_waiting_avoids_double_service_during_lock(self):
        r = contract_cash(D(100), D('82.5'), D(12), D(3))
        self.assertEqual(r.get('wait_saving'), D('13.125'))

    def test_expensive_alternative_exceeds_portable_floor(self):
        r = contract_cash(D(100), D(120), D(12), D(3))
        self.assertEqual(r.get('portable_cost'), D(120))

    def test_integer_capacity_can_reverse_busy_unit_cost(self):
        r = fleet_cost(D('.825'), D(12), D('.31'), D('1.98'), 1)
        self.assertEqual(r.get('old_replicas'), 3)
        self.assertEqual(r.get('new_replicas'), 4)
        self.assertGreater(r['billed_ratio'], D(1))

    def test_acceptance_changes_capacity_not_the_hardware_tariff(self):
        r = fleet_cost(D('.825'),D(12),D('.31'),D('1.80'),1,D('.8'))
        self.assertEqual(r['new_active'],3)
        self.assertAlmostEqual(r['implied_tariff_ratio'],D('.825')/(D('12.31')/D(12)),places=18)

    def test_concession_reduces_migration_allowance(self):
        r = concession(D(100), D('82.5'), D(5), D('.10'))
        self.assertEqual(r.get('remaining_allowance'), D('7.5'))
        self.assertEqual(r.get('saving_after_migration'), D('2.5'))
        self.assertEqual(r.get('matching_discount'), D('.125'))

    def test_financial_residual_does_not_become_an_impairment(self):
        r = financial_bridge(D(190055), D(90120), D(15353), D(263750))
        self.assertEqual(r.get('net_increase'), D(73695))
        self.assertEqual(r.get('unallocated_residual'), D(-1072))

    def test_blank_unknown_is_not_zero(self):
        row = dict(zip(FIELDS, ['X','','USD','unobserved','2026-10-16',
                    'Test','L','https://example.org','locator','explicit unknown']))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'data.csv'
            with path.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerow(row)
            data = read_data(path)
        self.assertIn('X',data)
        self.assertIsNone(data['X']['value'])
        with self.assertRaises(ValueError):
            number(data,'X','USD')

    def test_loader_rejects_duplicate_identifiers(self):
        row = dict(zip(FIELDS, ['X','1','USD','research_assumption','scenario',
                    'Test','M','','locator','test value']))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'data.csv'
            with path.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows([row,row])
            with self.assertRaises(ValueError):
                read_data(path)

    def test_reuse_of_stranded_entitlement_is_not_credited_to_portable_case(self):
        r = contract_cash(D(100), D('82.5'), D(12), D(3), reuse=D(5))
        self.assertEqual(r['stranded_saving'], D('-2.5'))
        self.assertEqual(r['portable_saving'], D('13.125'))

    def test_invalid_cost_and_time_domains_are_rejected(self):
        calls = [
            lambda: reconstruct(D(0),D(1),D(1)),
            lambda: reconstruct(D(1),D(1),D(1)),
            lambda: contract_cash(D(100),D(80),D(12),D(13)),
            lambda: fleet_cost(D('.8'),D(12),D('.3'),D(1),-1),
            lambda: fleet_cost(D('.8'),D(12),D('.3'),D(1),1,D(0)),
            lambda: concession(D(100),D(80),D(0),D('1.01')),
        ]
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(ValueError): call()

    def test_loading_rejects_bad_values_and_missing_metadata(self):
        base = dict(zip(FIELDS, ['X','1','USD','research_assumption','scenario',
                    'Test','M','','locator','test value']))
        variants = [('value','NaN'),('value','Infinity'),('value','not numeric'),
                    ('status','invented'),('period',''),('unit','')]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'data.csv'
            for key,value in variants:
                row = dict(base);row[key]=value
                with path.open('w',newline='',encoding='utf-8') as f:
                    w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerow(row)
                with self.subTest(key=key,value=value):
                    with self.assertRaises(ValueError): read_data(path)

    def test_value_accessor_checks_units(self):
        with self.assertRaises(ValueError):
            number({'X':{'value':D(1),'unit':'USD'}},'X','seconds')


def calculate(data: dict) -> dict:
    n = lambda key, unit: number(data, key, unit)
    reduction = n('L_REDUCTION', 'fraction')
    images = n('L_IMAGES', 'generated_images')
    scaffold = reconstruct(reduction, n('L_SAVING','USD'), images)
    old, new = scaffold['old'], scaffold['new']
    horizon, locked = n('M_HORIZON','months'), n('M_LOCK','months')
    migration = n('M_MIGRATION','USD')
    extra = n('L_EXTRA_TIME','seconds_per_generated_image')
    assumed_time = n('M_GPU_SECONDS','seconds_per_generated_image')
    standby_d = n('M_STANDBY','replicas')
    if standby_d != standby_d.to_integral_value():
        raise ValueError('Standby replicas must be integer')
    quality_ratio = n('M_ACCEPT_RATIO','ratio')
    if quality_ratio <= 0:
        raise ValueError('Accepted-output ratio must be positive')
    service_ratio = (1-reduction)/quality_ratio
    # Equal quality is the stated reference. Different acceptance changes the bill
    # scaffold proportionately but is NOT evidence that quality is actually worse.
    effective_new = old*service_ratio
    contracts = contract_cash(old,effective_new,horizon,locked,migration,
                              n('M_REUSED_CASH','USD'))
    fleet = {}
    for label,key in [('below_step','M_LOAD_LOW'),('crossing_step','M_LOAD_HIGH')]:
        fleet[label] = fleet_cost(1-reduction,assumed_time,extra,
                                 n(key,'baseline_active_capacity_units'),int(standby_d),quality_ratio)
    fin = financial_bridge(n('AWS_PPE_OPEN','USD_million'),
                          n('AWS_ADDITIONS_H1_26','USD_million'),
                          n('AWS_DA_H1_26','USD_million'),
                          n('AWS_PPE_CLOSE','USD_million'))
    for period in ('H1_25','H1_26','Q2_26'):
        sales=n('AWS_SALES_'+period,'USD_million')
        opex=n('AWS_OPEX_'+period,'USD_million')
        income=n('AWS_OI_'+period,'USD_million')
        if sales-opex != income:
            raise ValueError(f'AWS {period} does not reconcile')
        fin['operating_margin_'+period] = income/sales
    fin['sales_growth_H1'] = n('AWS_SALES_H1_26','USD_million')/n('AWS_SALES_H1_25','USD_million')-1
    fin['operating_income_growth_H1'] = n('AWS_OI_H1_26','USD_million')/n('AWS_OI_H1_25','USD_million')-1
    fin['net_additions_growth_H1'] = n('AWS_ADDITIONS_H1_26','USD_million')/n('AWS_ADDITIONS_H1_25','USD_million')-1
    remaining = n('AMZ_FACILITY_ORIGINAL','USD_million')-n('AMZ_SERIES_H','USD_million')
    if remaining != n('AMZ_FACILITY_REMAINING','USD_million'):
        raise ValueError('Anthropic facility ceiling reconciliation fails')
    buckets = ['FY27','FY28','FY29','FY30','FY31','AFTER']
    supply_sum = sum((n('NV_SUPPLY_'+b,'USD_million') for b in buckets),D(0))
    if supply_sum != n('NV_SUPPLY_TOTAL','USD_million'):
        raise ValueError('NVIDIA supply timing buckets do not reconcile')
    return {
        'boundary': 'Historical rounded-cost reconstruction plus conditional contract and finite-capacity tests; not actual customer bills, current quotes, cash forecasts or supplier margins.',
        'ledger_records':len(data),
        'explicit_unknowns':sum(row['value'] is None for row in data.values()),
        'historical_scaffold_USD':scaffold,
        'benchmark_timed_runs_per_platform':n('L_PROMPTS','prompts')*n('L_REPEATS','timed_runs_per_prompt_per_platform'),
        'additional_serial_occupied_hours_at_projected_volume':images*extra/D(3600),
        'equal_quality_reference_cost_ratio':1-reduction,
        'assumed_quality_adjusted_cost_ratio':service_ratio,
        'contract_scenario_USD':contracts,
        'concession_scenario_USD':concession(old,effective_new,n('M_MIGRATION_ALT','USD'),n('M_CONCESSION','fraction')),
        'finite_replica_scenarios':fleet,
        'paid_volume_ratio_for_unchanged_rental_revenue':1/service_ratio,
        'active_resource_ratio_for_same_revenue_serial_example':(assumed_time+extra)/assumed_time/quality_ratio/service_ratio,
        'AWS_financial_reconciliation_USD_million':fin,
        'Anthropic_remaining_facility_ceiling_USD_million':remaining,
        'NVIDIA_supply_bucket_sum_USD_million':supply_sum,
    }


def default_data() -> Path:
    here = Path(__file__).resolve()
    if here.name.endswith('calculations.py'):
        matching = here.with_name(here.name[:-len('calculations.py')]+'data.csv')
        if matching.is_file():
            return matching
    conventional=here.with_name('data.csv')
    if conventional.is_file():
        return conventional
    raise ValueError('No matching CSV beside the script; use --data PATH')


def encode_result(value):
    if isinstance(value,D):
        return format(value.quantize(D('.000001')), 'f')
    raise TypeError(f'Cannot serialize {type(value)}')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,help='Explicit matching ledger path')
    parser.add_argument('--self-test',action='store_true',help='Run local unit tests before calculations')
    parser.add_argument('--tests-only',action='store_true',help='Run local tests without loading the research ledger')
    args=parser.parse_args()
    if args.self_test or args.tests_only:
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(ResearchTests)
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
            return 1
        if args.tests_only:
            return 0
    try:
        with localcontext() as ctx:
            ctx.prec=42
            results=calculate(read_data(args.data or default_data()))
            print(json.dumps(results,default=encode_result,indent=2,sort_keys=True))
    except (OSError,ValueError,InvalidOperation,KeyError) as exc:
        print(f'Calculation not performed: {exc}',file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
