"""Loss-aware HRC archive settings/state interchange, without executing scripts.

Chip amounts in the app use ``chip_scale`` internal integers per scene unit.
Original state vectors are observations, never a training payoff or warm start.
Unknown fields survive round trips. Unsupported capabilities are explicit.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import math

from .hrc_abstraction import PROFILES

FORMAT = 'hrcz-settings-map-v1'
_FIELDS = ('players', 'chip_scale', 'big_blind', 'small_blind', 'ante', 'ante_type', 'straddle',
           'skip_small_blind', 'moving_button', 'tree_settings', 'max_active',
           'utility', 'payouts', 'other_stacks', 'bounty', 'rake', 'fgs', 'abstractions')


def _number(value, name, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be a finite number >= {minimum}')
    return value


def _integer(value, name, minimum=0, maximum=2**47):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in {minimum}..{maximum}')
    return value


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f'{name} must be an object')
    return value


def _chips(value, scale, name):
    _number(value, name)
    exact = Decimal(str(value)) * Decimal(scale)
    if exact != exact.to_integral_value() or exact > 2**47:
        raise ValueError(f'{name} cannot be represented exactly as internal integer chips')
    return int(exact)


def hand_rules(settings):
    """Strict rule validation shared by mapper and topology-only replayer."""
    hand = _object(_object(settings, 'settings').get('handdata'), 'handdata')
    stacks = hand.get('stacks')
    if not isinstance(stacks, list) or not 2 <= len(stacks) <= 10:
        raise ValueError('handdata.stacks requires 2..10 seats')
    for value in stacks:
        _integer(value, 'stack', 1)
    blinds = hand.get('blinds')
    if not isinstance(blinds, list) or len(blinds) != 3:
        raise ValueError('handdata.blinds must be [big blind, small blind, ante]')
    for value in blinds:
        _integer(value, 'blind/ante')
    if blinds[0] <= 0 or blinds[1] > blinds[0]:
        raise ValueError('Require positive BB and 0 <= SB <= BB')
    for field in ('skipSb', 'movingBu'):
        if type(hand.get(field, False)) is not bool:
            raise ValueError(f'handdata.{field} must be boolean')
    if hand.get('anteType', 'REGULAR') not in ('REGULAR', 'BB_ANTE_ANTE_FIRST', 'BB_ANTE_BLIND_FIRST', 'BB_ANTE_BLINDS_FIRST'):
        raise ValueError('Unsupported handdata.anteType')
    if hand.get('straddleType', 'OFF') not in ('OFF', 'SINGLE', 'DOUBLE', 'BUTTON'):
        raise ValueError('Unsupported handdata.straddleType')
    if len(stacks) < 3 and hand.get('straddleType', 'OFF') != 'OFF':
        raise ValueError('Straddles require at least three seats')
    return deepcopy(hand)


def expand_prizes(structure):
    """oL.createStructure: each key starts a payout step; zero last key ends it."""
    prizes = _object(structure.get('prizes', {}), 'structure.prizes')
    if not prizes:
        return []
    parsed = {}
    for key, value in prizes.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdigit() or str(int(key)) != key:
            raise ValueError('Prize step keys must be canonical positive rank strings')
        rank = _integer(int(key), 'prize rank', 1, 100000)
        parsed[rank] = float(_number(value, 'prize'))
    if min(parsed) != 1:
        raise ValueError('Prize structure must start at rank 1')
    last = max(parsed)
    paid = last - (parsed[last] <= 0)
    current, result = 0., []
    for rank in range(1, paid+1):
        current = parsed.get(rank, current)
        result.append(current)
    if any(a < b for a, b in zip(result, result[1:])):
        raise ValueError('Payout steps must be nonincreasing')
    return result


def _projection(config):
    return {key: deepcopy(config[key]) for key in _FIELDS if key in config}


def settings_to_config(settings, state=None, *, chip_scale=10000):
    """Map a saved setup for viewing/retraining, preserving unsupported metadata.

    ``hrcz_metadata.unsupported`` has scope ``training`` or ``rebuild``.
    The caller must enforce it. A successful mapping is not training approval.
    """
    _integer(chip_scale, 'chip_scale', 1)
    hand = hand_rules(settings)
    n, unsupported = len(hand['stacks']), []
    def issue(scope, field, reason):
        unsupported.append(dict(scope=scope, field=field, reason=reason))
    engine = _object(settings.get('engine', {}), 'engine')
    engine_config = _object(engine.get('configuration', {}), 'engine.configuration')
    if engine.get('type') != 'montecarlo':
        issue('training', 'engine.type', 'Only the audited Monte Carlo archive engine is supported')
    maximum = engine.get('maxactive', 4)
    _integer(maximum, 'engine.maxactive', 2, 10)
    abstractions = deepcopy(engine_config.get('abstractions', []))
    if not isinstance(abstractions, list) or len(abstractions) != 4 or any(not isinstance(a, dict) or a.get('street') != i for i,a in enumerate(abstractions)):
        issue('training', 'engine.configuration.abstractions', 'Four ordered street entries are required; no default profile is substituted')
    else:
        for street, spec in enumerate(abstractions):
            _integer(spec.get('buckets'), f'abstractions[{street}].buckets', -2**31, 2**31-1)
            if street == 0:
                if spec['buckets'] != 169:
                    issue('training', 'abstractions[0]', 'Unimplemented preflop abstraction')
            elif (spec['buckets'], spec.get('id')) != PROFILES[street]:
                issue('training', f'abstractions[{street}]', 'Exact saved resource/profile is not wired to the full-tree trainer; viewing is supported')
    tree = deepcopy(settings.get('treeconfig', {}))
    if not isinstance(tree, dict) or tree.get('mode') != 'ui':
        issue('rebuild', 'treeconfig', 'Saved topology is retained; arbitrary original JavaScript is never executed')
    else:
        from .hrc_tree_builder import default_settings
        for street in ('preflop', 'postflop'):
            spec = tree.get(street, {})
            if not isinstance(spec, dict) or spec.get('id') not in (f'{street}.settings.simple', f'{street}.settings.general'):
                issue('rebuild', f'treeconfig.{street}', 'Unknown tree policy; retain saved topology')
            else:
                kind = spec['id'].split('.')[-1]
                keys = default_settings(n, preflop_policy=kind, postflop_policy=kind)['treeconfig'][street]['settings']
                if not isinstance(spec.get('settings', {}), dict) or set(spec.get('settings', {}))-set(keys):
                    issue('rebuild', f'treeconfig.{street}.settings', 'Unknown policy fields; retain saved topology')
    model = _object(settings.get('eqmodel', {}), 'eqmodel')
    identity = model.get('id')
    cfg = dict(engine='hrc_custom', players=[dict(name=f'P{i+1}', stack=s/chip_scale, range='all') for i,s in enumerate(hand['stacks'])],
               big_blind=hand['blinds'][0]/chip_scale, small_blind=hand['blinds'][1]/chip_scale, ante=hand['blinds'][2]/chip_scale,
               ante_type=hand.get('anteType','REGULAR'), straddle=hand.get('straddleType','OFF'),
               skip_small_blind=hand.get('skipSb',False), moving_button=hand.get('movingBu',False),
               tree_settings=tree, chip_scale=chip_scale, max_active=maximum, node_budget=250000, iterations=100000, seed=42,
               abstractions=abstractions, payouts=[], other_stacks=[],
               bounty=dict(mode='none', amounts=[0.]*n, other_amounts=[], immediate_fraction=1.),
               rake=dict(mode='none', percentage=5., cap=3.))
    if identity == 'chipev':
        cfg['utility'] = 'chips'
        if type(model.get('raked',False)) is not bool:
            raise ValueError('eqmodel.raked must be boolean')
        if model.get('raked',False):
            pct = _number(model.get('rakepct'), 'rakepct')
            if pct > 1:
                raise ValueError('rakepct must be a fraction in [0,1]')
            for flag in ('nfnd', 'raketype_ggnetwork'):
                if type(model.get(flag,False)) is not bool:
                    raise ValueError(f'eqmodel.{flag} must be boolean')
            cfg['rake'] = dict(mode='nfnd' if model.get('nfnd') else 'gg' if model.get('raketype_ggnetwork') else 'full',
                               percentage=float(Decimal(str(pct))*100), cap=_integer(model.get('rakecap'), 'rakecap')/chip_scale)
    elif identity in ('icm', 'mtticm', 'fgs'):
        cfg['utility'] = 'mtt_icm' if identity == 'mtticm' else 'icm'
        structure = _object(model.get('structure'), 'eqmodel.structure')
        cfg['payouts'] = expand_prizes(structure) or [0.]
        others = model.get('otherstacks', []) if identity == 'mtticm' else []
        if not isinstance(others,list) or len(others)>10000:
            raise ValueError('otherstacks must contain at most 10000 stacks')
        for value in others:
            if _number(value,'other stack') <= 0:
                raise ValueError('Other stacks must be positive')
        # jE saves GUI chips; li converts local long[] with kF (x * .01)
        # before passing both arrays to lg. External values are NOT raw longs.
        cfg['other_stacks'] = [v*100/chip_scale for v in others]
        bounty_type = structure.get('bountyType','NONE')
        if bounty_type not in ('NONE','KO','PKO'):
            issue('training','eqmodel.structure.bountyType','Unknown bounty model')
        fixed = _number(structure.get('bounty',0),'fixed bounty')
        if bounty_type == 'PKO':
            amounts = hand.get('bounties')
            if not isinstance(amounts,list) or len(amounts)!=n:
                raise ValueError('PKO handdata.bounties must have one value per seat')
            amounts = [float(_number(v,'individual bounty')) for v in amounts]
            fraction = _number(structure.get('progressiveFactor',.5),'progressiveFactor')
            if fraction>1:
                raise ValueError('progressiveFactor must be in [0,1]')
            average = _number(model.get('otheravgbounty',0),'otheravgbounty')
            cfg['bounty'] = dict(mode='pko',amounts=amounts,other_amounts=[average]*len(others),immediate_fraction=fraction)
        elif fixed>0:
            cfg['bounty'] = dict(mode='ko',amounts=[fixed]*n,other_amounts=[fixed]*len(others),immediate_fraction=1.)
        else:
            cfg['bounty']['other_amounts'] = [0.]*len(others)
        if len(cfg['payouts']) > n+len(others):
            issue('training','eqmodel.structure.prizes','Prize array exceeds remaining field; preserved without truncation')
        if identity == 'fgs':
            from .hrc_fgs_config import DEFAULTS
            fgs = {**deepcopy(DEFAULTS), 'enabled':True, 'depth':model.get('depth'), 'depth3way':model.get('depth3way',1)}
            _integer(fgs['depth'],'FGS depth',0,10)
            _integer(fgs['depth3way'],'FGS depth3way',0,10)
            if 'nextlevel' in model:
                level = _object(model['nextlevel'],'nextlevel')
                fgs['next_level_at'] = _integer(level.get('atdepth'),'nextlevel.atdepth',1,10)
                chips = level.get('tolevel')
                if not isinstance(chips,list) or len(chips)!=3:
                    raise ValueError('nextlevel.tolevel must be [BB,SB,ante]')
                fgs['next_level'] = {name:_integer(v,name)/chip_scale for name,v in zip(('big_blind','small_blind','ante'),chips)}
            cfg['fgs'] = fgs
    else:
        cfg['utility'] = 'unsupported'
        issue('training','eqmodel.id','Unknown payoff model, preserved for read-only viewing')
    if 'subtree' in settings:
        issue('training','subtree','Saved postflop subtree replay/viewing is supported; archive range/profile adapter is not yet wired to training')
    state_value = deepcopy(_object(state,'state')) if state is not None else None
    if state_value is not None:
        for key in ('eqpre','eqpost'):
            if key in state_value:
                values=state_value[key]
                if not isinstance(values,list) or len(values)!=n or any(type(x) not in (int,float) or not math.isfinite(x) for x in values):
                    raise ValueError(f'state.{key} requires {n} finite observed values')
    cfg['hrcz_metadata'] = dict(format=FORMAT, chip_scale=chip_scale, settings=deepcopy(settings), state=state_value,
        state_unit='internal_chips_divided_by_100' if identity=='chipev' else 'payout_currency' if identity in ('icm','mtticm','fgs') else 'unknown',
        state_to_scene=100/chip_scale if identity=='chipev' else 1 if identity in ('icm','mtticm','fgs') else None,
        source_training_iterations=None, other_stacks_unit='internal_chips_divided_by_100',
        unsupported=unsupported, original_projection=_projection(cfg))
    return cfg


def config_to_settings(config, *, template=None, chip_scale=None):
    """Generate original-format settings, retaining template/unknown fields.

    An unchanged mapped config returns its exact JSON object shape. Original
    strategy/results and scripts are neither executed nor used for generation.
    """
    _object(config,'config')
    meta = config.get('hrcz_metadata',{})
    scale = config.get('chip_scale',meta.get('chip_scale',10000)) if chip_scale is None else chip_scale
    _integer(scale,'chip_scale',1)
    source = template if template is not None else meta.get('settings')
    if source is not None and _projection(config)==meta.get('original_projection') and scale==meta.get('chip_scale') and template is None:
        return deepcopy(source)
    result = deepcopy(source) if source is not None else {}
    hand = result.setdefault('handdata',{})
    players = config.get('players')
    if not isinstance(players,list) or not 2<=len(players)<=10:
        raise ValueError('config.players requires 2..10 seats')
    n = len(players)
    hand.update(stacks=[_chips(p['stack'],scale,'stack') for p in players],
                blinds=[_chips(config[k],scale,k) for k in ('big_blind','small_blind','ante')],
                anteType=config.get('ante_type','REGULAR'),straddleType=config.get('straddle','OFF'),
                skipSb=config.get('skip_small_blind',False),movingBu=config.get('moving_button',False))
    hand_rules(result)
    result['treeconfig'] = deepcopy(config['tree_settings'])
    engine = result.setdefault('engine',{})
    engine.setdefault('type','montecarlo')
    engine['maxactive'] = _integer(config.get('max_active',4),'max_active',2,10)
    abstractions=config.get('abstractions')
    if abstractions is None:
        abstractions=[{'street':0,'buckets':169}]+[{'street':s,'buckets':v[0],'id':v[1]} for s,v in PROFILES.items()]
    engine.setdefault('configuration',{})['abstractions']=deepcopy(abstractions)
    model = result.setdefault('eqmodel',{})
    utility = config.get('utility','chips')
    if utility=='unsupported':
        if source is None:
            raise ValueError('Cannot synthesize an unsupported payoff model')
        return result
    # Remove only audited fields whose old meaning would conflict with the new model.
    for key in ('id','raked','rakepct','rakecap','nfnd','raketype_ggnetwork','otherstacks','otheravgbounty','depth','depth3way','nextlevel'):
        model.pop(key,None)
    if utility=='chips':
        from .hrc_rake import validated_rake
        rake=validated_rake(config.get('rake',{'mode':'none'}),utility)
        model.update(id='chipev',raked=rake['mode']!='none')
        if rake['mode']!='none':
            model.update(rakepct=rake['percentage']/100,rakecap=_chips(rake['cap'],scale,'rake cap'))
            if rake['mode']=='nfnd':model['nfnd']=True
            if rake['mode']=='gg':model['raketype_ggnetwork']=True
        model.pop('structure',None)
        hand.pop('bounties',None)
    elif utility in ('icm','mtt_icm'):
        from .tournament import validated_equity
        from .hrc_fgs_config import validated_fgs
        equity=validated_equity(config,n)
        fgs=validated_fgs(config.get('fgs'),equity,n)
        model['id']='fgs' if fgs['enabled'] else 'mtticm' if utility=='mtt_icm' else 'icm'
        structure=model.setdefault('structure',{})
        structure.setdefault('name','Independent research')
        payouts=equity['payouts']
        # A step map with an explicit zero stop reproduces oL's paid-spot length.
        structure['prizes']={str(i+1):v for i,v in enumerate(payouts) if i==0 or v!=payouts[i-1]}
        structure['prizes'][str(len(payouts)+1)]=0.
        bounty=equity['bounty']
        structure['bountyType']=bounty['mode'].upper()
        if bounty['mode']=='pko':
            structure['progressiveFactor']=bounty['immediate_fraction']
            structure['bounty']=0.
            hand['bounties']=deepcopy(bounty['amounts'])
        else:
            structure['bounty']=bounty['amounts'][0] if bounty['mode']=='ko' else 0.
            structure.pop('progressiveFactor',None)
            hand.pop('bounties',None)
        if utility=='mtt_icm':
            model['otherstacks']=[float(Decimal(str(v))*scale/100) for v in equity['other_stacks']]
            if bounty['mode']=='pko':
                other=bounty['other_amounts']
                model['otheravgbounty']=math.fsum(other)/len(other) if other else 0.
        if fgs['enabled']:
            model.update(depth=fgs['depth'],depth3way=fgs['depth3way'])
            if fgs['next_level'] is not None:
                model['nextlevel']={'atdepth':fgs['next_level_at'],'tolevel':[_chips(fgs['next_level'][k],scale,k) for k in ('big_blind','small_blind','ante')]}
    else:
        raise ValueError('Unsupported application utility')
    return result


def config_to_state(config, *, template=None, eqpre=None, eqpost=None, units='archive'):
    """Export explicit observations; require both vectors for a new archive.

    ``scene`` chipEV values multiply by chip_scale/100; ``internal`` divide by
    100. Tournament currency is unchanged. No eqpost is fabricated from stacks.
    """
    if units not in ('archive','scene','internal'):
        raise ValueError('state units must be archive, scene or internal')
    meta=config.get('hrcz_metadata',{})
    source=template if template is not None else meta.get('state')
    if template is None and source is not None and _projection(config)!=meta.get('original_projection') and (eqpre is None or eqpost is None):
        raise ValueError('Edited scene requires new observed eqpre and eqpost; archived state would be stale')
    state=deepcopy(source) if source is not None else {}
    n=len(config['players'])
    factor=1.
    if config.get('utility')=='chips':
        factor=config.get('chip_scale',meta.get('chip_scale',10000))/100 if units=='scene' else .01 if units=='internal' else 1.
    for key,value in (('eqpre',eqpre),('eqpost',eqpost)):
        if value is not None:
            if not isinstance(value,(list,tuple)) or len(value)!=n or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):
                raise ValueError(f'{key} requires {n} finite observed values')
            state[key]=[x*factor for x in value]
        if key not in state:
            raise ValueError(f'Cannot export state without an observed {key} vector')
        if not isinstance(state[key],(list,tuple)) or len(state[key])!=n or any(type(x) not in (int,float) or not math.isfinite(x) for x in state[key]):
            raise ValueError(f'{key} requires {n} finite observed values')
    return state
