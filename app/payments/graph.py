"""Who paid whom, around accounts that raised an alert. Built only from what was observed, never from the simulator's answer."""
from __future__ import annotations

import threading
from collections import OrderedDict

MAX_EDGES = 20_000
MAX_PER_COLUMN = 14


class MoneyGraph:
    """The stream thread writes while the API reads, so both go through one lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self.suspects: set[str] = set()
        self.edges: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self.incoming: dict[str, set[str]] = {}
        self.outgoing: dict[str, set[str]] = {}

    def add_suspect(self, vpa: str) -> None:
        with self._lock:
            self.suspects.add(vpa)

    def record(self, payer: str, payee: str, amount: float, status: str, ts: float, count: bool = True) -> None:
        """Remembers money flowing into or out of a suspect. Everything else is ordinary life and is not kept.
        status: moved, stopped, cancelled or pending. Only the first two carry money."""
        with self._lock:
            if payer not in self.suspects and payee not in self.suspects:
                return
            key = (payer, payee)
            e = self.edges.get(key)
            if e is None:
                e = self.edges[key] = {"amount": 0.0, "held": 0.0, "n": 0, "last": ts}
                self.incoming.setdefault(payee, set()).add(payer)
                self.outgoing.setdefault(payer, set()).add(payee)
                if len(self.edges) > MAX_EDGES:
                    (a, b), _ = self.edges.popitem(last=False)
                    self.incoming.get(b, set()).discard(a)
                    self.outgoing.get(a, set()).discard(b)
            else:
                self.edges.move_to_end(key)
            e["n"] += int(count)
            e["last"] = ts
            if status == "moved":
                e["amount"] += amount
            elif status == "stopped":
                e["held"] += amount

    def around(self, vpa: str, directory: dict | None = None, reports=None) -> dict:
        """The network around one account in columns: who paid it, then where the money went next."""
        directory = directory or {}
        with self._lock:
            column = {vpa: 0}
            for payer in self.incoming.get(vpa, ()):
                column.setdefault(payer, -1)
            frontier, depth = [vpa], 0
            while frontier and depth < 4:
                depth += 1
                step = []
                for v in frontier:
                    for payee in self.outgoing.get(v, ()):
                        if payee not in column:
                            column[payee] = depth
                            step.append(payee)
                frontier = step

            # A popular account can have many payers: show the biggest few and say how many more there are.
            victims = [v for v, c in column.items() if c == -1]
            hidden = 0
            if len(victims) > MAX_PER_COLUMN:
                victims.sort(key=lambda v: -sum(self.edges.get((v, vpa), {}).get(k, 0.0) for k in ("amount", "held")))
                for v in victims[MAX_PER_COLUMN:]:
                    del column[v]
                hidden = len(victims) - MAX_PER_COLUMN

            suspects = set(self.suspects)
            edges = []
            for a in column:
                for b in self.outgoing.get(a, ()):
                    e = self.edges.get((a, b))
                    if e is not None and b in column:
                        edges.append({"from": a, "to": b, "amount": round(e["amount"], 2), "held": round(e["held"], 2), "n": e["n"]})

        nodes = []
        for v, c in column.items():
            info = directory.get(v) or {}
            nodes.append({"id": v, "column": c, "role": "payer" if c < 0 else ("focus" if c == 0 else "next"), "merchant": bool(info.get("merchant")),
                          "verified": bool(info.get("verified")), "reports": reports(v) if reports else 0, "suspect": v in suspects})
        return {"focus": vpa, "nodes": nodes, "edges": edges, "hidden_payers": hidden,
                "total_in": round(sum(e["amount"] for e in edges if e["to"] == vpa), 2),
                "total_held": round(sum(e["held"] for e in edges), 2),
                "total_out": round(sum(e["amount"] for e in edges if e["from"] == vpa), 2)}
