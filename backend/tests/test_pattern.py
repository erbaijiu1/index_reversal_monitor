from decimal import Decimal
from app.services.pattern import identify,Rule

def k(o,c,h=None,l=None,complete=True,volume=100,sessions=5):
    return {'open':o,'close':c,'high':h if h is not None else max(o,c),'low':l if l is not None else min(o,c),'is_complete':complete,'volume':volume,'actual_sessions':sessions}

def test_mixed_colors_engulf():
    rows=[k(110,100),k(100,105),k(105,90),k(85,115,volume=300)]
    x=identify(rows)
    assert x and x['engulfed_count']==3 and x['bearish_count']==2

def test_no_skip_unengulfed():
    rows=[k(150,140),k(110,95),k(95,85),k(80,120)]
    x=identify(rows)
    assert x and x['engulfed_count']==2 and x['max_engulfable_count']==2

def test_reject_missing_decline():
    assert identify([k(100,90),k(98,95),k(85,110)]) is None  # earliest close 90 < latest close 95

def test_reject_wick_only():
    assert identify([k(110,100),k(100,90),k(85,105,h=120)]) is None

def test_partial_volume_not_confirmed():
    rows=[k(120,110),k(110,100),k(95,125,complete=False,volume=500,sessions=2)]
    x=identify(rows)
    assert x and x['status']=='FORMING' and x['volume_ratio'] is None and x['signal_level']=='BASE'

def test_later_max_eligible():
    rows=[k(119,108),k(107,98),k(101,103),k(103,91),k(89,121)]
    x=identify(rows)
    assert x and x['engulfed_count']==4
