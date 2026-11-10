"""Lazy action rows for the desktop-style strategy tree.

Each branch lists available non-fold actions and then follows the ordinary
fold continuation. The selected row identifies an action at its parent node;
expanding it starts a new branch after that action. No policy is invented for
previews or hands without observations.
"""
import math


def compact_classes(selected):
    values = {label: probability for probability, label in selected}
    full = {label for label, probability in values.items() if probability >= .995}
    ranks = 'AKQJT98765432'
    output = []

    def runs(labels):
        start = None
        for index in range(len(labels) + 1):
            if index < len(labels) and labels[index] in full:
                if start is None:
                    start = index
            elif start is not None:
                end = index - 1
                output.append(labels[start] if start == end else labels[end] + '+' if start == 0 else labels[start] + '-' + labels[end])
                start = None
    runs([rank * 2 for rank in ranks])
    for suffix in ('s', 'o'):
        for index, high in enumerate(ranks[:-1]):
            runs([high + low + suffix for low in ranks[index + 1:]])
    output.extend(f'{label}:{probability:.2f}' for probability, label in selected if .005 <= probability < .995)
    return ' '.join(output)


def action_summary(node, index):
    hands = (node.get('strategy') or {}).get('hands', {})
    covered = weighted = 0.0
    selected = []
    for label, hand in hands.items():
        frequencies = hand.get('frequencies')
        if not (hand.get('has_saved_policy') or (hand.get('visits') or 0) > 0) or not frequencies or index >= len(frequencies):
            continue
        probability = frequencies[index]
        if not isinstance(probability, (int, float)) or not math.isfinite(probability):
            continue
        weight = (6 if len(label) == 2 else 4 if label.endswith('s') else 12) if node.get('street', 0) == 0 else 1
        covered += weight
        weighted += weight * probability
        if probability >= .005:
            selected.append((probability, label))
    selected.sort(key=lambda item: (-item[0], item[1]))
    text = compact_classes(selected) if node.get('street', 0) == 0 else ', '.join(label for _, label in selected)
    return {'frequency': weighted / covered if covered else None,
            'covered_combinations': covered, 'range_text': text,
            'weighting': 'uniform combinations among observed classes; not downstream reach'}


def strategy_branch(solver, path=(), *, read_node=None, limit=128):
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError('Strategy branch limit must be in 1..256')
    describe = solver.describe_node
    read = read_node or (solver.result_node if getattr(solver, 'output', None) is not None or getattr(solver, 'source', None) is not None else describe)
    path = list(path)
    node = read(path)
    start_street = node.get('street', 0)
    rows = []
    # A fold continuation eliminates a seat; this guard also bounds malformed
    # or legacy trees. Real rows keep their complete edge paths.
    for _ in range(12):
        if node.get('terminal') or node.get('street', 0) != start_street:
            break
        for index, action in enumerate(node.get('actions', [])):
            if action['kind'] == 'fold':
                continue
            child_path = path + [action['id']]
            child = describe(child_path)
            rows.append({'key': '/'.join(child_path), 'path': list(path), 'child_path': child_path,
                         'action': action, 'actor': node['actor'], 'actor_name': node['actor_name'],
                         'street': node.get('street', 0), 'native_id': node.get('native_id'),
                         'expandable': not child.get('terminal'), **action_summary(node, index)})
            if len(rows) >= limit:
                return {'rows': rows, 'path': list(path), 'truncated': True}
        fold = next((action for action in node.get('actions', []) if action['kind'] == 'fold'), None)
        if fold is None or node.get('special'):
            break
        path = path + [fold['id']]
        node = read(path)
    return {'rows': rows, 'truncated': False}
