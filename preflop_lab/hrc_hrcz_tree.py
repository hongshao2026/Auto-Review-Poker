"""Replay saved HRC topology using independently audited rule transitions.

This module never calls the tree builder's policy/children/build methods. It
retains record IDs, edge order, compressed actions and source physical order.
It does not read original saved strategies or terminal utility vectors.
"""
from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import zipfile

from .hrc_tree import HRCAction, ImportedTree, ReplayRules, TreeReplayError, parse_gametree
from .hrc_tree_builder import _Builder, GeneratedState
from .hrc_hrcz_settings import hand_rules, settings_to_config


def _require(condition, message):
    if not condition:
        raise TreeReplayError(message)


class _Rules(_Builder):
    """Only bind reviewed hand-rule primitives; no policy is instantiated."""
    def __init__(self, settings):
        hand = hand_rules(settings)
        self.n, self.stacks = len(hand['stacks']), tuple(hand['stacks'])
        self.bb, self.sb, self.ante = hand['blinds']
        self.skip_sb, self.moving_button = hand.get('skipSb',False),hand.get('movingBu',False)
        self.ante_type, self.straddle = hand.get('anteType','REGULAR'),hand.get('straddleType','OFF')
        self.button = 0 if self.n==2 else self.n-(2 if self.skip_sb else 3)
        self.base = self.bb*(4 if self.straddle=='DOUBLE' else 2 if self.straddle!='OFF' else 1)
        specs=settings.get('engine',{}).get('configuration',{}).get('abstractions',[])
        buckets=[0]*4
        for spec in specs:
            _require(isinstance(spec,dict) and type(spec.get('street')) is int and 0<=spec['street']<4,
                     'Malformed abstraction street; saved topology was not changed')
            _require(type(spec.get('buckets')) is int,'Malformed abstraction bucket count')
            buckets[spec['street']]=spec['buckets']
        self.rules=ReplayRules(self.stacks,self.bb,self.sb,tuple(buckets))


def _record_order(data):
    count,=struct.unpack_from('<i',data)
    position,order=4,[]
    for _ in range(count):
        node_id,_,kind,length,children=struct.unpack_from('<iiBbh',data,position)
        order.append(node_id)
        position+=12+(2 if kind==1 else 0)+length*8+children*4
    return tuple(order)


@dataclass(frozen=True, slots=True)
class ArchiveTree(ImportedTree):
    record_order: tuple[int,...]
    raise_counts: tuple[int,...]
    archive_state: dict | None

    def describe_node(self,path=None,*,node_id=None):
        result=ImportedTree.describe_node(self,path,node_id=node_id)
        state=self.states[result['hrc_node_id']]
        result.update(dead_money=state.dead_money/self.rules.big_blind,
                      minimum_raise_to=state.minimum_raise_to/self.rules.big_blind if state.minimum_raise_to>0 else None,
                      topology_source='imported_hrc_saved_topology',state_source='independent_generic_rule_replay')
        return result

    def compact_export(self):
        result=ImportedTree.compact_export(self)
        result['version']='hrcz-saved-topology-replay-v1'
        for terminal in result['terminals']:
            node_id=terminal['node_id']
            state=self.states[node_id]
            terminal.update(dead_money=state.dead_money,street=state.street,
                            raise_count=self.raise_counts[node_id],participant_mask=state.participant_mask,
                            street_contributions=list(state.street_contributions))
        return result

    def require_trainable(self):
        problems=[x for x in self.validation['unsupported'] if x['scope']=='training']
        if problems:
            raise ValueError('; '.join(x['field']+': '+x['reason'] for x in problems))


def _advance(rules,context,street):
    _require(type(street) is int and context.state.street<=street<=3,'Backward or invalid street transition')
    while context.state.street<street:
        context=rules.advance(context)
    return context


def _apply(rules,context,action,*,check_allin=True):
    context=_advance(rules,context,action.street)
    _require(0<=action.kind<4 and 0<=action.actor<rules.n and action.amount>=0,'Invalid incoming action')
    _require(rules.actor(context)==action.actor,'Incoming action actor disagrees with rule state')
    amount=action.amount
    if action.kind==3:
        # Saved lB actions can contain the own-stack excess caused by applying
        # the minimum after mF's effective cap. Regenerate through that audited
        # clamp, then require the stored amount/all-in bit to agree exactly.
        _,maximum=rules.limits(context,action.actor)
        amount=min(amount,maximum)
    result=rules.apply(context,action.kind,amount)
    actual=result.history[-1]
    _require((actual.kind,actual.actor,actual.street,actual.amount)==(action.kind,action.actor,action.street,action.amount),
             f'Incoming amount/type mismatch: saved {action}, replayed {actual}')
    _require(not check_allin or actual.allin==action.allin,
             f'Incoming all-in bit mismatch: saved {action}, replayed {actual}')
    return result


def _initial_context(rules,settings,root):
    context=rules.initial()
    subtree=settings.get('subtree')
    if subtree is None:
        return context,0
    _require(isinstance(subtree,dict),'Malformed subtree settings')
    sequence=subtree.get('sequence',[])
    _require(isinstance(sequence,list) and len(sequence)<=256,'Malformed subtree action sequence')
    parsed=[]
    for item in sequence:
        _require(isinstance(item,dict) and item.get('type') in ('F','X','C','R'),'Unknown subtree action type')
        for field in ('player','street','amount'):
            _require(type(item.get(field)) is int,f'Invalid subtree action {field}')
        action=HRCAction(('F','X','C','R').index(item['type']),item['player'],item['street'],item['amount'])
        context=_apply(rules,context,action,check_allin=False)
        parsed.append(context.history[-1])
    # Some serialized root paths include the complete setup sequence. Compare
    # exact independently regenerated actions before suppressing a duplicate.
    if parsed and root.incoming_actions[:len(parsed)]==tuple(parsed):
        return rules.initial(),0
    return context,len(parsed)


def replay_archive_tree(settings,gametree,*,state=None,provenance=None):
    """Read bytes, replay every stored edge and return an immutable ArchiveTree.

    Unknown sizing scripts are preserved, never executed. Leaf round closure
    is checked; stopping future betting early remains an explicit saved-tree
    policy choice and is counted rather than replaced with a default tree.
    """
    _require(isinstance(gametree,(bytes,bytearray)),'gametree must be bytes')
    cfg=settings_to_config(settings,state)
    rules=_Rules(settings)
    nodes,root=parse_gametree(gametree)
    initial,prefix_length=_initial_context(rules,settings,nodes[root])
    states,raises=[None]*len(nodes),[0]*len(nodes)
    queue=deque([(root,initial)])
    actions,transitions,forced,early=0,0,0,0
    while queue:
        node_id,context=queue.popleft()
        node=nodes[node_id]
        try:
            if node_id!=root:
                _require(bool(node.incoming_actions),'Child is missing its incoming decision action')
                parent=nodes[node.parent_id]
                first=node.incoming_actions[0]
                _require((first.actor,first.street)==(parent.actor,parent.street),'First edge action does not belong to its parent decision')
            for action in node.incoming_actions:
                transitions+=action.street-context.state.street
                context=_apply(rules,context,action)
                actions+=1
            forced+=max(0,len(node.incoming_actions)-(node_id!=root))
            if not node.terminal:
                transitions+=node.street-context.state.street
                context=_advance(rules,context,node.street)
                _require(node.actor==rules.actor(context),'Saved decision actor disagrees with rule state')
                _require(sum(not context.state.folded&(1<<i) for i in range(rules.n))>1,'Decision with at most one live player')
                if len(node.children)>16 and not any(x['field']=='gametree.action_count' for x in cfg['hrcz_metadata']['unsupported']):
                    cfg['hrcz_metadata']['unsupported'].append(dict(scope='training',field='gametree.action_count',
                        reason='Saved decisions exceed the native 16-action limit; topology remains viewable'))
            else:
                _require(rules.actor(context) is None,'Saved leaf ends an unfinished betting round')
                if context.state.street<3 and context.state.live_count>1:
                    early+=1
            public=rules.public_state(context,node.terminal)
            _require(all(x>=0 for x in public.remaining+public.contributions),'Negative chips after replay')
            _require(sum(public.remaining)+public.pot==sum(rules.stacks),'Total chip conservation failed')
            for i,(remaining,paid,initial_stack) in enumerate(zip(public.remaining,public.contributions,rules.stacks)):
                attributed_ante=public.dead_money if i==rules.n-1 else 0
                _require(remaining+paid+attributed_ante==initial_stack,'Per-seat chip conservation failed')
            if node.terminal:
                for level in set(public.contributions)-{0}:
                    _require(any(not public.folded[i] and paid>=level for i,paid in enumerate(public.contributions)),
                             'Terminal positive pot layer has no eligible player')
            states[node_id]=public
            raises[node_id]=sum(a.kind==3 for a in context.history)
            for child in node.children:
                queue.append((child,context))
        except (ValueError,IndexError) as exc:
            raise TreeReplayError(f'node {node_id}: {exc}') from exc
    counts=Counter(n.street for n in nodes if not n.terminal)
    validation=dict(nodes=len(nodes),edges=len(nodes)-1,decision_nodes=sum(not n.terminal for n in nodes),
        terminal_nodes=sum(n.terminal for n in nodes),decision_nodes_by_street=[counts[i] for i in range(4)],
        replayed_actions=actions,forced_suffix_actions=forced,street_transitions=transitions,
        subtree_prefix_actions=prefix_length,saved_early_checkdown_terminals=early,
        all_nodes_conserve_chips=True,all_actions_rule_checked=True,all_terminal_pot_layers_have_eligible_players=True,
        topology_source='imported saved topology; not rebuilt',unsupported=deepcopy(cfg['hrcz_metadata']['unsupported']))
    origins=dict(provenance or {})
    origins.update(gametree_sha256=hashlib.sha256(gametree).hexdigest(),saved_strategy_loaded=False,
                   saved_terminal_utilities_loaded=False,topology_rebuilt=False)
    return ArchiveTree(deepcopy(settings),rules.rules,nodes,tuple(states),root,origins,validation,
                       _record_order(gametree),tuple(raises),deepcopy(state))


def load_archive_tree(path):
    """Load only settings/state/topology from a bounded archive member set."""
    path=Path(path)
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        payload={}
        for name,limit in (('settings.json',1000000),('state.json',1000000),('gametree.dat',200000000)):
            _require(names.count(name)==1,f'Missing/duplicate {name}')
            _require(archive.getinfo(name).file_size<=limit,f'Oversized {name}')
            payload[name]=archive.read(name)
    try:
        settings=json.loads(payload['settings.json'])
        state=json.loads(payload['state.json'])
    except (ValueError,UnicodeError) as exc:
        raise TreeReplayError('Invalid archive JSON') from exc
    provenance=dict(source_path=str(path.resolve()),read_members=list(payload),
                    settings_sha256=hashlib.sha256(payload['settings.json']).hexdigest(),
                    state_sha256=hashlib.sha256(payload['state.json']).hexdigest())
    return replay_archive_tree(settings,payload['gametree.dat'],state=state,provenance=provenance)
