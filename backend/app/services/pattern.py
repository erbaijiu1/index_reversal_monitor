"""Pure decimal-based engulfment detector. Input candles ordered oldest -> newest."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

D=lambda x: Decimal(str(x))

def valid(k):
    try:
        o,h,l,c=(D(k[x]) for x in ('open','high','low','close'))
        return l>0 and l<=min(o,c) and h>=max(o,c) and h>=l
    except (KeyError, ValueError, TypeError, InvalidOperation): return False

@dataclass(frozen=True)
class Rule:
    min_engulfed: int=2
    min_bearish: int=2
    max_lookback: int=26
    volume_lookback: int=5
    volume_warm: Decimal=Decimal('1.2')
    volume_strong: Decimal=Decimal('1.5')

def identify(candles: list[dict[str,Any]], rule: Rule=Rule()):
    if len(candles)<rule.min_engulfed+1: return None
    current=candles[-1]
    if not valid(current) or D(current['close'])<=D(current['open']): return None
    if any(not valid(k) or not k.get('is_complete',True) for k in candles[:-1][-rule.max_lookback:]): return None
    previous=list(reversed(candles[:-1]))
    maximum=0
    for k in previous[:rule.max_lookback]:
        if D(current['open'])<=min(D(k['open']),D(k['close'])) and D(current['close'])>=max(D(k['open']),D(k['close'])):
            maximum+=1
        else: break
    chosen=None
    for n in range(rule.min_engulfed,maximum+1):
        part=previous[:n]
        bearish=sum(D(k['close'])<D(k['open']) for k in part)
        if bearish>=rule.min_bearish and D(part[-1]['close'])>D(part[0]['close']):
            chosen=(n,bearish,part)
    if chosen is None:return None
    n,bearish,part=chosen
    breakout=D(current['close'])>max(D(k['high']) for k in part)
    is_complete=bool(current.get('is_complete',False))
    basis=next((b for b in ('volume','amount') if current.get(b) is not None and all(k.get(b) is not None for k in previous[:rule.volume_lookback])),None)
    ratio=None; cumulative=None; pace=None
    if basis and len(previous)>=rule.volume_lookback:
        old=previous[:rule.volume_lookback]
        vals=[D(k[basis]) for k in old]
        avg=sum(vals)/len(vals)
        if avg>0:
            cumulative=D(current[basis])/avg
            if is_complete:ratio=cumulative
            else:
                sessions=D(current.get('actual_sessions',0))
                session_rates=[D(k[basis])/D(k.get('actual_sessions',0)) for k in old if D(k.get('actual_sessions',0))>0]
                if sessions>0 and len(session_rates)==len(old) and sum(session_rates)>0:
                    pace=(D(current[basis])/sessions)/(sum(session_rates)/len(session_rates))
    effective=ratio if is_complete else pace
    vol_level='UNAVAILABLE' if effective is None else ('STRONG' if effective>=rule.volume_strong else 'WARM' if effective>=rule.volume_warm else 'LOW' if effective<Decimal('0.8') else 'NORMAL')
    level='STRONG' if is_complete and ratio is not None and ratio>=rule.volume_strong and breakout else 'VOLUME_CONFIRMED' if is_complete and ratio is not None and ratio>=rule.volume_warm else 'BASE'
    return dict(engulfed_count=n,max_engulfable_count=maximum,bearish_count=bearish,
                previous_first_close=part[-1]['close'],previous_last_close=part[0]['close'],
                breakout_high=breakout,volume_basis=basis.upper() if basis else 'NONE',
                volume_ratio=ratio,cumulative_volume_ratio=cumulative,pace_ratio=pace,
                volume_level=vol_level,signal_level=level,
                current_open=current['open'],current_close=current['close'],
                status='CONFIRMED' if is_complete else 'FORMING')
