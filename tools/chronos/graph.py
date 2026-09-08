"""順序制約グラフと循環検出。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .models import Event


@dataclass
class OrderGraph:
    """有向辺 A→B は「A が B より先」を表す。"""

    successors: dict[str, list[str]] = field(default_factory=dict)
    predecessors: dict[str, list[str]] = field(default_factory=dict)

    def add_node(self, node: str) -> None:
        self.successors.setdefault(node, [])
        self.predecessors.setdefault(node, [])

    def add_edge(self, earlier: str, later: str) -> None:
        if earlier == later:
            self.add_node(earlier)
            if later not in self.successors[earlier]:
                self.successors[earlier].append(later)
            if earlier not in self.predecessors[later]:
                self.predecessors[later].append(earlier)
            return
        self.add_node(earlier)
        self.add_node(later)
        if later not in self.successors[earlier]:
            self.successors[earlier].append(later)
        if earlier not in self.predecessors[later]:
            self.predecessors[later].append(earlier)


def build_order_graph(events: list[Event]) -> OrderGraph:
    """after / before / causes / effects / offset.from を順序辺へ落とす。"""

    graph = OrderGraph()
    by_id = {event.id: event for event in events}
    for event in events:
        graph.add_node(event.id)
        time = event.time
        if time is not None:
            for predecessor in time.after:
                if predecessor in by_id:
                    graph.add_edge(predecessor, event.id)
            for successor in time.before:
                if successor in by_id:
                    graph.add_edge(event.id, successor)
            if time.offset is not None and time.offset.from_event in by_id:
                graph.add_edge(time.offset.from_event, event.id)
        for cause in event.causes:
            if cause in by_id:
                graph.add_edge(cause, event.id)
        for effect in event.effects:
            if effect in by_id:
                graph.add_edge(event.id, effect)
    return graph


def find_cycles(graph: OrderGraph) -> list[list[str]]:
    """反復 DFS で後退辺から閉路を拾う。長い連鎖でも再帰上限に当たらない。"""

    white, gray, black = 0, 1, 2
    color = {node: white for node in graph.successors}
    cycles: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    for start in sorted(graph.successors):
        if color[start] != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        color[start] = gray
        while stack:
            node, index = stack[-1]
            successors = graph.successors.get(node, [])
            if index < len(successors):
                stack[-1] = (node, index + 1)
                nxt = successors[index]
                state = color.get(nxt, white)
                if state == gray:
                    if nxt in path:
                        begin = path.index(nxt)
                        cycle = path[begin:] + [nxt]
                    else:
                        cycle = [node, nxt] if nxt == node else [node, nxt, node]
                    key = frozenset(cycle[:-1] if cycle[0] == cycle[-1] else cycle)
                    if key and key not in seen:
                        seen.add(key)
                        cycles.append(cycle)
                elif state == white:
                    color[nxt] = gray
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[node] = black
                stack.pop()
                path.pop()
    return cycles


def topological_order(graph: OrderGraph, preferred: list[str]) -> list[str]:
    """安定なトポロジカル順。循環があるノードは preferred の末尾に残す。"""

    indegree: dict[str, int] = {node: 0 for node in graph.successors}
    for node, successors in graph.successors.items():
        for successor in successors:
            if successor == node:
                continue
            indegree[successor] = indegree.get(successor, 0) + 1
    remaining = {node: index for index, node in enumerate(preferred)}
    ready = deque(
        sorted(
            (node for node, degree in indegree.items() if degree == 0),
            key=lambda node: remaining.get(node, 10**9),
        )
    )
    ordered: list[str] = []
    while ready:
        node = ready.popleft()
        ordered.append(node)
        next_ready: list[str] = []
        for successor in graph.successors.get(node, []):
            if successor == node:
                continue
            indegree[successor] -= 1
            if indegree[successor] == 0:
                next_ready.append(successor)
        next_ready.sort(key=lambda item: remaining.get(item, 10**9))
        ready.extend(next_ready)
    leftover = [node for node in preferred if node not in set(ordered)]
    return ordered + leftover


def reachable_from(graph: OrderGraph, start: str) -> set[str]:
    """``start`` から到達できる後続（自身は含めない）。"""

    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in graph.successors.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    seen.discard(start)
    return seen


def incomparable_pairs(graph: OrderGraph, event_ids: list[str]) -> list[tuple[str, str]]:
    """到達可能性で前後を比較できない組。ID 昇順で安定化する。"""

    ids = sorted(set(event_ids))
    reach = {event_id: reachable_from(graph, event_id) for event_id in ids}
    pairs: list[tuple[str, str]] = []
    for index, earlier in enumerate(ids):
        for later in ids[index + 1 :]:
            if later not in reach[earlier] and earlier not in reach[later]:
                pairs.append((earlier, later))
    return pairs


def order_by_reachability(graph: OrderGraph, event_ids: list[str]) -> list[str]:
    """互いに比較可能なイベントを、到達数の多い（より先の）順に並べる。"""

    ids = list(dict.fromkeys(event_ids))
    reach = {event_id: reachable_from(graph, event_id) for event_id in ids}
    id_set = set(ids)

    def score(event_id: str) -> tuple[int, str]:
        return (-sum(1 for other in id_set if other in reach[event_id]), event_id)

    return sorted(ids, key=score)


def events_for_actor(events: list[Event], actor_id: str) -> list[Event]:
    return [event for event in events if actor_id in event.actors]


def events_for_location(events: list[Event], location_id: str) -> list[Event]:
    return [event for event in events if event.location == location_id]
