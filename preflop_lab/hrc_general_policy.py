"""Independent selectors for the two audited bundled Advanced sizing policies.

Only explicit data settings are accepted. The research oracle separately executes
hash-pinned shipped scripts; this production module does not run JavaScript.
"""
from __future__ import annotations

import copy
import math
import re

PRE_DEFAULTS={
    'SIZES_OPEN_OTHERS':'2.3bb + 1.0bb','SIZES_OPEN_BU':'2.3bb + 1.0bb',
    'SIZES_OPEN_SB':'3.5bb + 1.0bb','SIZES_OPEN_BB':'3.5bb + 1.0bb','SIZES_OPEN_BB_VS_SB':'3.0bb',
    'SIZES_3BET_IP':'2.5x + 1.0x','SIZES_3BET_OOP':None,'SIZES_3BET_BB_VS_SB':'2.5x',
    'SIZES_3BET_BB_VS_OTHER':'3.3x + 1.0x','SIZES_3BET_SB_VS_BB':'2.6x + 1.0x',
    'SIZES_3BET_SB_VS_OTHER':'3.3x + 1.0x','SIZES_4BET_IP':'90.0%, all-in','SIZES_4BET_OOP':'120.0%, all-in',
    'SIZES_5BET_IP':'90.0%, all-in','SIZES_5BET_OOP':'120.0%, all-in','PREFLOP_ALLIN_THRESHOLD':40,
    'PREFLOP_ADD_ALLIN_SPR':7,'ALLOWED_FLATS_PER_RAISE':[0,1,1,1,0],
    'ALLOW_COLD_CALLS':False,'ALLOW_FLATS_CLOSING_ACTION':True,'ALLOW_SB_COMPLETE':True,
}
POST_DEFAULTS={
    **{f'POSTFLOP_{street}_{kind}':(['66%','66%'] if street=='FLOP' and kind=='BET' else [None,None])
       for street in ('FLOP','TURN','RIVER') for kind in ('BET','RAISE','DONK')},
    'POSTFLOP_LOW_SPR_THRESHOLD':[2.5,2.5],'POSTFLOP_LOW_SPR_BET':['66g','66g'],
    'POSTFLOP_LOW_SPR_RAISE':[None,None],'POSTFLOP_ADD_ALLIN_SPR':[5,5],
    'POSTFLOP_ALLOW_DONK':[False,False],'POSTFLOP_ALLOW_DONK_PREV_AGGRESSION':[True,True],
    'POSTFLOP_FORCE_CHECKDOWN_AFTER':[3,3,2,1,0,0,0,0,0],'POSTFLOP_MAX_BETS_PER_STREET':[-1,-1],
}


def defaults(street):
    return copy.deepcopy(PRE_DEFAULTS if street=='preflop' else POST_DEFAULTS)


def _require(ok,message):
    if not ok:raise ValueError(message)


def post_specs(text):
    _require(isinstance(text,str),'Postflop sizing requires a string')
    text=text.strip().lower()
    if text in ('','-','none'):return []
    allin=bool(re.search(r'all-in|allin|ai',text));text=re.sub(r'all-in|allin|ai','',text)
    result=[]
    for item in re.split(r'[,\s]+',text):
        if not item:continue
        match=re.fullmatch(r'(\d+(?:\.\d*)?|\.\d+)(bb|g|e|x|%)?',item)
        _require(match is not None,f'Unsupported postflop sizing: {item}')
        number,unit=float(match[1]),match[2] or '%'
        _require(math.isfinite(number),'Sizing must be finite')
        if unit=='e':
            number=round(number)  # Original Math.rint, ties to even.
            _require(number!=0,'Geometric step count must round to at least one')
        if unit=='g':_require(number>0,'Geometric hints must be positive')
        result.append((unit,number))
    if allin:result.append(('allin',0.))
    return result


def validate(pre,post,parse_pre):
    finite=lambda x:type(x) in (int,float) and math.isfinite(x)
    if pre is not None:
        _require(set(pre)==set(PRE_DEFAULTS),'Unknown general preflop setting')
        optional={'SIZES_3BET_OOP','SIZES_3BET_BB_VS_SB','SIZES_3BET_BB_VS_OTHER','SIZES_3BET_SB_VS_BB','SIZES_3BET_SB_VS_OTHER'}
        for key,value in pre.items():
            if key.startswith('SIZES_'):
                if value is None:_require(key in optional,f'{key} requires a sizing string')
                else:parse_pre(value)
            elif key.startswith('ALLOW_'):_require(type(value) is bool,f'{key} must be boolean')
            elif key=='ALLOWED_FLATS_PER_RAISE':_require(isinstance(value,list) and all(type(x) is int and x>=0 for x in value),'Flat limits must be nonnegative integers')
            else:_require(finite(value) and (key!='PREFLOP_ALLIN_THRESHOLD' or value>=0),f'Invalid {key}')
    if post is not None:
        _require(set(post)==set(POST_DEFAULTS),'Unknown general postflop setting')
        for key,value in post.items():
            _require(isinstance(value,list),f'{key} must be an array')
            if key=='POSTFLOP_FORCE_CHECKDOWN_AFTER':_require(all(type(x) is int and 0<=x<=3 for x in value),'Checkdown streets must lie in 0..3')
            else:
                _require(len(value)==2,f'{key} requires HU and multiway values')
                for x in value:
                    if key.endswith(('_BET','_RAISE','_DONK')) and not key.startswith('POSTFLOP_ALLOW_'):
                        if x is None:_require(key not in ('POSTFLOP_FLOP_BET','POSTFLOP_LOW_SPR_BET'),f'{key} requires sizing strings')
                        else:post_specs(x)
                    elif key.startswith('POSTFLOP_ALLOW_'):_require(type(x) is bool,f'{key} must be boolean')
                    elif key=='POSTFLOP_MAX_BETS_PER_STREET':_require(type(x) is int and x>=-1,f'Invalid {key}')
                    else:_require(finite(x),f'Invalid {key}')


def in_position(builder,player,opponent):
    button=builder.button
    offset=lambda p:p-button if p>button else p+builder.n-button
    return offset(player)>offset(opponent)


def closing_action(builder,context,actor):
    s=context.state
    return all(i==actor or s.folded&(1<<i) or s.remaining[i]==0 or
               (s.participants&(1<<i) and s.street_paid[i]>=s.current_bet) for i in range(builder.n))


def spr(builder,context,actor):
    _,pot,effective=builder._pot_geometry(context,actor)
    # Retain qp's operation order at low-SPR threshold boundaries.
    return ((pot+2*effective)/pot-1)/2


def pre_text(builder,context,actor):
    p,s=builder.pre,context.state;sb=-1 if builder.skip_sb else builder.n-2;bb=builder.n-1
    if s.bets==1:
        if actor==bb and sb>=0 and not s.folded&(1<<sb) and s.folded.bit_count()==builder.n-2:
            return p['SIZES_OPEN_BB_VS_SB']
        position='BB' if actor==bb else 'SB' if actor==sb else 'BU' if actor==builder.button else 'OTHERS'
        return p['SIZES_OPEN_'+position]
    raiser=next(a.actor for a in reversed(context.history) if a.kind==3)
    ip=in_position(builder,actor,raiser)
    if s.bets==2:
        key=('SIZES_3BET_SB_VS_'+('BB' if raiser==bb else 'OTHER')) if actor==sb else (
            'SIZES_3BET_BB_VS_'+('SB' if raiser==sb else 'OTHER')) if actor==bb else None
        if key is not None and p[key] is not None:return p[key]
        return p['SIZES_3BET_OOP'] if not ip and p['SIZES_3BET_OOP'] is not None else p['SIZES_3BET_IP']
    return p[f'SIZES_{s.bets+1}BET_'+('IP' if ip else 'OOP')]


def can_flat(builder,context,actor):
    p,s=builder.pre,context.state
    if s.bets==1 and p['ALLOW_SB_COMPLETE'] and s.street_paid[actor]>0:return True
    if p['ALLOW_FLATS_CLOSING_ACTION'] and closing_action(builder,context,actor):return True
    if not p['ALLOW_COLD_CALLS'] and s.bets>2 and not any(a.actor==actor and a.street==s.street for a in context.history):return False
    return s.bets-1<len(p['ALLOWED_FLATS_PER_RAISE']) and s.flats<p['ALLOWED_FLATS_PER_RAISE'][s.bets-1]


def post_text(builder,context,actor):
    p,s=builder.post,context.state;idx=int(s.live_count>2)
    if spr(builder,context,actor)<=p['POSTFLOP_LOW_SPR_THRESHOLD'][idx]:
        raised=p['POSTFLOP_LOW_SPR_RAISE'][idx]
        return raised if s.bets>0 and raised is not None else p['POSTFLOP_LOW_SPR_BET'][idx]
    kind='RAISE' if s.bets else 'DONK' if builder.is_donk(context,actor) else 'BET'
    streets=('FLOP','TURN','RIVER')
    for street in range(s.street,0,-1):
        value=p[f'POSTFLOP_{streets[street-1]}_{kind}'][idx]
        if value is not None:return value
    return p['POSTFLOP_FLOP_BET'][idx]


def post_sizes(builder,context,actor,text):
    minimum,maximum=builder.limits(context,actor);s=context.state;result=[]
    for unit,number in post_specs(text):
        if maximum<=minimum or unit=='allin':value=maximum
        elif unit=='g':value=builder.geometric(context,actor,number*.01)
        elif unit=='%':value=builder.pot_size(context,actor,number*.01)
        elif unit=='e':
            if number<=1:value=maximum
            else:
                current,pot,effective=builder._pot_geometry(context,actor)
                fraction=(((pot+2*effective)/pot)**(1/number)-1)/2
                value=min(max(current+math.ceil(pot*fraction),builder.bb),maximum)
        elif unit=='x':
            base=builder.base if s.bets==0 else next(a.amount for a in reversed(context.history) if a.kind==3)
            value=math.floor(base*number+.5)
        else:value=math.floor(builder.bb*number+.5)
        result.append(min(max(value,minimum),maximum))
    return result
