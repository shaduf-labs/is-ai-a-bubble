#!/usr/bin/env python3
"""Named holder exposure and bounded loss/funding tests.

Python 3.10+; standard library for calculations/tests; matplotlib only for --figure.
No network requests, trading, or edits to inputs. All model dollars are USD millions.
Usage: python holder-calculations.py [--data holder-data.csv] [--figure holder-absorption.svg]
Delivery-prefixed sibling names also work. Outputs are conditional balance-sheet
arithmetic, NOT default probabilities, recovery appraisals or compliance certificates.
"""
from __future__ import annotations
import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# The delivery prefix, if any, is carried through from this script's filename.
DATA_NAME = Path(__file__).name.replace('holder-calculations.py', 'holder-data.csv')
STATUSES = {'reported', 'contractual', 'announced', 'authorization', 'assumption'}
UNITS = {'USD_million', 'USD_per_share', 'shares', 'units', 'fraction', 'ratio', 'days'}

@dataclass(frozen=True)
class Input:
    value: float
    unit: str
    status: str
    entity: str
    period: str
    source: str


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_inputs(path: Path) -> dict[str, Input]:
    result: dict[str, Input] = {}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        needed = {'id','entity','instrument','metric','value','unit','period','status',
                  'source_id','source_url','locator','notes'}
        require(needed.issubset(reader.fieldnames or []), 'Missing input columns')
        for row in reader:
            require(None not in row and all(row.get(k) is not None for k in needed),
                    'Malformed CSV row / missing or extra column')
            key = row['id']
            require(bool(key) and key not in result, f'Empty/duplicate ID: {key}')
            value = float(row['value'])
            require(math.isfinite(value), f'Nonfinite value: {key}')
            require(row['unit'] in UNITS, f'Unknown unit: {key}')
            require(row['status'] in STATUSES, f'Unknown evidence status: {key}')
            require(all(row[k] for k in ('entity','period','source_id','source_url','locator')),
                    f'Missing provenance: {key}')
            require(not key.startswith('A_') or row['status'] == 'assumption',
                    f'Model input not labeled assumption: {key}')
            result[key] = Input(value,row['unit'],row['status'],row['entity'],
                                row['period'],row['source_id'])
    require(bool(result), 'Empty input file')
    return result


def n(data: Mapping[str, Input], key: str, unit: str = 'USD_million') -> float:
    record = data[key]
    require(record.unit == unit, f'{key}: expected {unit}, got {record.unit}')
    return record.value


def nonnegative(name: str, value: float) -> None:
    require(math.isfinite(value) and value >= 0, f'{name} must be finite and nonnegative')


def fraction(name: str, value: float) -> None:
    require(math.isfinite(value) and 0 <= value <= 1, f'{name} must lie in [0,1]')


@dataclass(frozen=True)
class Holder:
    assets: float
    liabilities: float
    nav: float
    debt_face: float
    debt_carrying: float
    bank_draw: float
    bank_cap: float
    cash: float
    money_market: float
    nav_floor: float
    coverage_min: float

    def __post_init__(self) -> None:
        for key, value in vars(self).items():
            nonnegative(key, value)
        require(self.debt_face > 0 and self.coverage_min > 1, 'Invalid debt or coverage threshold')
        require(self.bank_draw <= self.bank_cap, 'Draw exceeds contractual ceiling')
        require(math.isclose(self.assets-self.liabilities,self.nav,abs_tol=1e-8),
                'Balance sheet does not reconcile')

    def coverage_proxy(self, loss: float = 0.0, debt_repaid: float = 0.0) -> float:
        """Face-debt/NAV convention reproduces the issuer's rounded 166.4%.

        This is not an obtained regulatory or bank certificate. Repayment reduces
        debt and assets equally, leaving NAV unchanged before fees or sale losses.
        """
        nonnegative('loss',loss); nonnegative('repayment',debt_repaid)
        require(debt_repaid < self.debt_face, 'Repayment must leave positive debt')
        debt = self.debt_face-debt_repaid
        return 1+(self.nav-loss)/debt

    def unadjusted_book_coverage(self, loss: float = 0.0) -> float:
        """Disclosure sensitivity: unadjusted book assets and carrying liabilities.

        Lower than the reported-ratio reconstruction by debt issuance-cost/discount
        effects. NOT an alternative certified covenant ratio or allegation of breach.
        """
        nonnegative('loss',loss)
        return (self.assets-(self.liabilities-self.debt_carrying)-loss)/self.debt_face

    def additional_debt_room(self, loss: float = 0.0) -> float:
        """Coverage-only room if new debt brings equal cash; excludes fees/base/NAV test."""
        nonnegative('loss',loss)
        return max(0.,(self.nav-loss)/(self.coverage_min-1)-self.debt_face)


def holder(data: Mapping[str,Input]) -> Holder:
    face = sum(n(data,'G_NOTE_'+k+'_FACE') for k in ('I','H','G')) + n(data,'G_REV_DRAW')
    return Holder(n(data,'G_ASSETS'),n(data,'G_LIABS'),n(data,'G_NAV'),face,
                  n(data,'G_NOTES_CARRY')+n(data,'G_REV_DRAW'),n(data,'G_REV_DRAW'),
                  n(data,'G_REV_CAP'),n(data,'G_CASH'),n(data,'G_MMF'),n(data,'G_NAV_MIN'),
                  n(data,'G_COVER_MIN','ratio'))


def exposure(data: Mapping[str,Input]) -> dict[str,float]:
    secured_fv=sum(n(data,'G_'+k+'_FV') for k in ('II','IV','V'))
    secured_face=sum(n(data,'G_'+k+'_FACE') for k in ('II','IV','V'))
    bond_fv=n(data,'G_BOND_FV'); lp_fv=n(data,'G_LP_FV')
    return {
        'secured_fv':secured_fv,'secured_face':secured_face,
        'debt_fv':secured_fv+bond_fv,'debt_face':secured_face+n(data,'G_BOND_FACE'),
        'bond_fv':bond_fv,'lp_fv':lp_fv,'total_fv':secured_fv+bond_fv+lp_fv,
        'total_cost':sum(n(data,'G_'+k+'_COST') for k in ('II','IV','V','BOND','LP')),
        'coupon_runrate':sum(n(data,'G_'+k+'_FACE')*n(data,'G_'+k+'_RATE','fraction')
                             for k in ('II','IV','V','BOND')),
        'older_face_change':sum(n(data,'G_'+k+'_FACE')-n(data,'G_PRIOR_'+k+'_FACE')
                                for k in ('II','IV')),
    }


def workout_loss(data: Mapping[str,Input], secured_recovery: float,
                 bond_recovery: float, retained_lp_value: float = 0.) -> tuple[float,float]:
    fraction('secured recovery',secured_recovery); fraction('bond recovery',bond_recovery)
    nonnegative('LP residual',retained_lp_value)
    e=exposure(data)
    require(retained_lp_value <= e['lp_fv'], 'LP residual exceeds model starting value')
    recovery=e['secured_face']*secured_recovery+n(data,'G_BOND_FACE')*bond_recovery+retained_lp_value
    return e['total_fv']-recovery,recovery


def case_results(data: Mapping[str,Input]) -> list[dict[str,float|str]]:
    h=holder(data);e=exposure(data)
    orderly,_=workout_loss(data,n(data,'A_SEC_REC','fraction'),n(data,'A_BOND_REC','fraction'))
    losses=[('No change',0.),
            ('LP equity -50%; debt unchanged',e['lp_fv']*n(data,'A_EQ_MARK','fraction')),
            ('Differentiated marks',e['secured_fv']*n(data,'A_SEC_MARK','fraction')+
             e['bond_fv']*n(data,'A_BOND_MARK','fraction')+e['lp_fv']*n(data,'A_LP_MARK','fraction')),
            ('Conditional net workout',orderly),
            ('All five selected positions to zero',e['total_fv']),
            ('Selected zero plus other losses',e['total_fv']+n(data,'A_OTHER_LOSS'))]
    result=[]
    for label,loss in losses:
        result.append({'case':label,'loss':loss,'nav':h.nav-loss,
                       'nav_room':h.nav-loss-h.nav_floor,
                       'coverage_proxy':h.coverage_proxy(loss),
                       'unadjusted_book_sensitivity':h.unadjusted_book_coverage(loss),
                       'coverage_only_debt_room':h.additional_debt_room(loss)})
    return result


def deficiency_cure(draw: float, borrowing_base: float, liquid_pool: float) -> dict[str,float]:
    """Hypothetical certificate; debt repayment is a cash use, not a new investment loss."""
    for key,value in [('draw',draw),('base',borrowing_base),('liquid pool',liquid_pool)]:
        nonnegative(key,value)
    due=max(0.,draw-borrowing_base)
    paid=min(due,liquid_pool)
    return {'deficiency':due,'cash_used':paid,'cash_left':liquid_pool-paid,
            'unfunded_cure':due-paid,'bank_debt_after':draw-paid}


def sale_to_restore_coverage(nav: float,debt: float,minimum: float,discount: float=0.) -> dict[str,float]:
    """Pure deleveraging algebra, not permission to sell collateral or prepay a note.

    Selling book amount X at discount d loses dX of NAV and repays (1-d)X.
    It cannot repair a minimum-NAV breach; fees/priority restrictions are excluded.
    """
    nonnegative('debt',debt);nonnegative('NAV',nav);fraction('sale discount',discount)
    require(debt>0 and minimum>1,'Invalid debt / minimum')
    gap=(minimum-1)*debt-nav
    if gap<=0:return {'book_sold':0.,'cash_repaid':0.,'additional_loss':0.}
    denom=(minimum-1)-minimum*discount
    require(denom>0,'Sale discount prevents restoring coverage in this model')
    book=gap/denom;cash=book*(1-discount)
    require(cash<debt,'Model would require paying all debt')
    return {'book_sold':book,'cash_repaid':cash,'additional_loss':book*discount}


def nvidia(data: Mapping[str,Input]) -> dict[str,float]:
    pool=n(data,'N_CASH')+n(data,'N_DEBT_SEC')
    call=n(data,'A_N_CALL');recovery=n(data,'A_N_RECOVERY')
    require(0<=recovery<=call<=pool,'Support illustration outside model domain')
    marked_loss=n(data,'N_MARKET_EQ')*n(data,'A_N_MARK','fraction')
    return {'cash_reconstructed':n(data,'N_CASH_BEGIN')+n(data,'N_OCF')+n(data,'N_ICF')+n(data,'N_FCF_FIN'),
            'liquid_pool':pool,'debt_carrying':n(data,'N_DEBT_CURRENT')+n(data,'N_DEBT_LONG'),
            'historical_share_sensitivity':n(data,'N_CW_SHARES','shares')*n(data,'A_N_PRICE_MOVE','USD_per_share')/1e6,
            'subscription_product':n(data,'N_NEW_CW_SHARES','shares')*n(data,'N_CW_PRICE','USD_per_share')/1e6,
            'marketable_mark_loss':marked_loss,'mark_loss_fraction_equity':marked_loss/n(data,'N_EQUITY'),
            'after_gross_call':pool-call,'after_delayed_recovery':pool-call+recovery,
            'peak_cash_need':call,'net_cash_outlay':call-recovery}


def close(a: float,b: float) -> None:
    require(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),f'Identity failed: {a} vs {b}')


def run_tests(data: Mapping[str,Input]) -> None:
    h=holder(data);e=exposure(data);nv=nvidia(data)
    close(e['total_fv'],23.311);close(e['debt_face'],16.645);close(e['total_cost'],19.877)
    close(h.nav,110.418);close(h.debt_face,166.4);close(h.nav-h.nav_floor,30.418)
    close(round(h.coverage_proxy(),3),n(data,'G_REPORTED_COVER','ratio'))
    close((h.coverage_proxy()-h.unadjusted_book_coverage())*h.debt_face,h.debt_face-h.debt_carrying)
    close(nv['cash_reconstructed'],n(data,'N_CASH'))
    close(n(data,'N_ASSETS')-n(data,'N_LIABS'),n(data,'N_EQUITY'))
    require(abs(nv['subscription_product']-n(data,'N_CW_PAID'))<.001,'Rounded subscription failed')
    close(nv['after_delayed_recovery'],nv['liquid_pool']-nv['net_cash_outlay'])
    close(e['older_face_change'],-3.146)
    for row in case_results(data):
        close(float(row['nav'])+float(row['loss']),h.nav)
    cure=deficiency_cure(h.bank_draw,n(data,'A_FUTURE_BASE'),h.cash+h.money_market)
    close(cure['deficiency'],3.);close(cure['cash_left'],2.635)
    close(cure['cash_used']+cure['cash_left'],h.cash+h.money_market)
    # A cash repayment reduces assets and liabilities by the same amount.
    close((h.assets-cure['cash_used'])-(h.liabilities-cure['cash_used']),h.nav)
    adverse=h.nav-e['total_fv']-n(data,'A_OTHER_LOSS')
    for d in (0.,n(data,'A_SALE_DISCOUNT','fraction')):
        r=sale_to_restore_coverage(adverse,h.debt_face,h.coverage_min,d)
        close(1+(adverse-r['additional_loss'])/(h.debt_face-r['cash_repaid']),h.coverage_min)
        require(adverse-r['additional_loss']<h.nav_floor,'Debt repayment cannot cure this NAV breach')
    rng=random.Random(2409)
    for _ in range(300):
        loss=rng.uniform(0,45);extra=rng.uniform(.001,5)
        require(h.coverage_proxy(loss+extra)<h.coverage_proxy(loss),'Loss monotonicity')
        require(h.additional_debt_room(loss+extra)<=h.additional_debt_room(loss),'Funding room monotonicity')
        draw=rng.uniform(0,50);base=rng.uniform(0,50);cash=rng.uniform(0,10)
        c=deficiency_cure(draw,base,cash)
        close(c['deficiency'],c['cash_used']+c['unfunded_cure'])
        close(c['cash_left']+c['cash_used'],cash)
    bad_calls=[lambda: h.coverage_proxy(-1),lambda: h.coverage_proxy(0,h.debt_face),
               lambda: deficiency_cure(-1,0,0),lambda: workout_loss(data,1.01,.4),
               lambda: workout_loss(data,.8,-.1),lambda: sale_to_restore_coverage(70,166.4,1.5,.5),
               lambda: n(data,'G_NAV','shares')]
    for call in bad_calls:
        try:call()
        except ValueError:pass
        else:raise ValueError('Invalid-input check failed')


def render_figure(data: Mapping[str,Input],destination: Path) -> None:
    import matplotlib.pyplot as plt
    h=holder(data);e=exposure(data)
    xs=[i*n(data,'A_FIG_MAXLOSS')/300 for i in range(301)]
    fig,ax=plt.subplots(figsize=(11.4,6.6))
    ax.plot(xs,[h.nav-x for x in xs],label='Net assets after stipulated loss',linewidth=2)
    ax.axhline(h.nav_floor,linestyle='--',label='Bank minimum net assets: USD 80m')
    ax.axvline(e['total_fv'],linestyle=':',label='All five selected holdings: USD 23.311m')
    ax.scatter([e['total_fv'],h.nav-h.nav_floor],[h.nav-e['total_fv'],h.nav_floor])
    ax.annotate('Selected holdings to zero:\nnet assets USD 87.107m',
                xy=(e['total_fv'],h.nav-e['total_fv']),xytext=(3,69),
                arrowprops={'arrowstyle':'->'},fontsize=10)
    ax.annotate('Net-assets floor reached at\nUSD 30.418m total loss',
                xy=(h.nav-h.nav_floor,h.nav_floor),xytext=(29,102),
                arrowprops={'arrowstyle':'->'},fontsize=10)
    ax.set_xlabel('Additional loss from June carrying values (USD millions)')
    ax.set_ylabel('GECC net assets (USD millions)')
    ax.set_title('A holder can retain equity yet lose funding flexibility',loc='left',fontsize=16,pad=18)
    ax.set_xlim(0,45);ax.set_ylim(60,114);ax.legend(loc='lower left',fontsize=9)
    ax.grid(axis='y',alpha=.25)
    fig.text(.10,.035,'Frozen June 30, 2026 balance sheet; losses are scenarios, not observed outcomes or probabilities.\n'
             'Other coverage, borrowing-base and cash-payment tests may bind earlier. This is not a compliance certificate.\n'
             'Sources: GECC June 10-Q and bank agreement; dated investigation sections 3–5; holder-data.csv and holder-calculations.py.',fontsize=9)
    fig.subplots_adjust(left=.10,right=.97,bottom=.24,top=.86)
    fig.savefig(destination,format='svg',metadata={'Date':None,'Creator':'Holder exposure calculations'})
    plt.close(fig)


def main() -> None:
    folder=Path(__file__).resolve().parent
    default=next((p for p in (folder/'holder-data.csv',folder/DATA_NAME) if p.exists()),folder/'holder-data.csv')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=default)
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args();data=load_inputs(args.data);run_tests(data)
    h=holder(data);e=exposure(data)
    print('ALL DOLLAR AMOUNTS USD MILLIONS; CONDITIONAL TESTS, NOT CERTIFICATES')
    print('EXPOSURES',e)
    print(f'Selected FV / NAV {e["total_fv"]/h.nav:.6%}; / assets {e["total_fv"]/h.assets:.6%}; / investments {e["total_fv"]/n(data,"G_INVESTMENTS"):.6%}')
    print(f'NAV-floor loss room {h.nav-h.nav_floor:.6f}; coverage-proxy loss room {h.nav-(h.coverage_min-1)*h.debt_face:.6f}')
    print(f'Unadjusted-book coverage sensitivity loss room {(h.unadjusted_book_coverage()-h.coverage_min)*h.debt_face:.6f}; face/carrying reconciliation {h.debt_face-h.debt_carrying:.6f}')
    print('Case | loss | NAV | room over NAV floor | coverage proxy | unadjusted book sensitivity | coverage-only additional debt')
    for r in case_results(data):
        print(f'{r["case"]} | {r["loss"]:.6f} | {r["nav"]:.6f} | {r["nav_room"]:.6f} | {r["coverage_proxy"]:.6%} | {r["unadjusted_book_sensitivity"]:.6%} | {r["coverage_only_debt_room"]:.6f}')
    print('BANK CURE',deficiency_cure(h.bank_draw,n(data,'A_FUTURE_BASE'),h.cash+h.money_market))
    print(f'Bank covenant numerator before GECCI inclusion {n(data,"G_BANK_COVER_MIN","ratio")*h.bank_draw:.6f}; with frozen GECCI principal {n(data,"G_BANK_COVER_MIN","ratio")*(h.bank_draw+n(data,"G_NOTE_I_FACE")):.6f}')
    adverse=h.nav-e['total_fv']-n(data,'A_OTHER_LOSS')
    print('PAR DELEVERAGING ONLY',sale_to_restore_coverage(adverse,h.debt_face,h.coverage_min))
    print('DISCOUNTED DELEVERAGING ONLY',sale_to_restore_coverage(adverse,h.debt_face,h.coverage_min,n(data,'A_SALE_DISCOUNT','fraction')))
    print('NVIDIA',nvidia(data))
    print(f'All tests passed; {len(data)} input records; 300 synthetic cases; 7 invalid-call tests.')
    if args.figure:render_figure(data,args.figure)

if __name__=='__main__':
    try:main()
    except (OSError,KeyError,ValueError) as exc:raise SystemExit(f'Calculation failed: {exc}') from exc
