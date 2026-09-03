"""In-memory directed graph of accounts, devices, and payee handles.

SQLite is the source of truth. This graph is a working copy so later
phases can walk a few hops without scanning every ledger row.
Quoted rows are not money edges. Only settled and held are.
"""

from __future__ import annotations

from datetime import datetime, timezone

import networkx as nx
from sqlmodel import Session, select

from backend.core.models import Account, Event, Transaction

_MONEY_STATUSES = frozenset({"settled", "held"})

# Replaced on rebuild_from_db. Empty until first build.
_graph: nx.DiGraph = nx.DiGraph()


def get_graph() -> nx.DiGraph:
    """The in-memory graph. Empty DiGraph if never built."""
    return _graph


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _device_node_id(device_id: str) -> str:
    return f"device:{device_id}"


def _payee_node_id(handle: str) -> str:
    return f"payee:{handle}"


def _money_edges(graph: nx.DiGraph, account_id: str, direction: str):
    if direction == "in":
        edges = graph.in_edges(account_id, data=True)
    else:
        edges = graph.out_edges(account_id, data=True)
    for src, dst, data in edges:
        if data.get("edge_type") == "money":
            yield src, dst, data


def _ensure_account_node(graph: nx.DiGraph, account: Account) -> None:
    graph.add_node(account.id, node_type="account")
    device_nid = _device_node_id(account.device_id)
    graph.add_node(device_nid, node_type="device")
    graph.add_edge(account.id, device_nid, edge_type="used_device")


def _add_money_edge(
    graph: nx.DiGraph,
    tx: Transaction,
    sender: Account,
    receiver: Account,
) -> None:
    if tx.status not in _MONEY_STATUSES:
        return
    _ensure_account_node(graph, sender)
    _ensure_account_node(graph, receiver)
    graph.add_edge(
        sender.id,
        receiver.id,
        edge_type="money",
        amount_paise=int(tx.amount_paise),
        amount=int(tx.amount_paise) / 100.0,
        channel=tx.channel,
        ts=tx.attempted_at,
        taint=tx.taint_ratio,
        tx_id=tx.id,
    )


def rebuild_from_db(session: Session) -> nx.DiGraph:
    """Full rebuild from accounts + settled|held transactions + events."""
    global _graph
    graph = nx.DiGraph()

    accounts = {row.id: row for row in session.exec(select(Account)).all()}
    for account in accounts.values():
        _ensure_account_node(graph, account)

    for tx in session.exec(select(Transaction)).all():
        if tx.status not in _MONEY_STATUSES:
            continue
        sender = accounts.get(tx.sender_id)
        receiver = accounts.get(tx.receiver_id)
        if sender is None or receiver is None:
            continue
        _add_money_edge(graph, tx, sender, receiver)

    for event in session.exec(select(Event)).all():
        account = accounts.get(event.account_id)
        if account is None:
            continue
        _apply_event(graph, event, account)

    _graph = graph
    return _graph


def upsert_transaction(tx: Transaction, sender: Account, receiver: Account) -> None:
    """Incremental money-edge update for later quote/commit."""
    graph = get_graph()
    _add_money_edge(graph, tx, sender, receiver)


def upsert_event(event: Event, account: Account) -> None:
    """Incremental event-edge update for later quote/commit."""
    graph = get_graph()
    _ensure_account_node(graph, account)
    _apply_event(graph, event, account)


def _apply_event(graph: nx.DiGraph, event: Event, account: Account) -> None:
    if event.event_type != "payee_added":
        return
    payload = event.payload or {}
    handle = payload.get("payee_handle")
    if not handle:
        return
    payee_nid = _payee_node_id(str(handle))
    graph.add_node(payee_nid, node_type="payee_handle")
    graph.add_edge(account.id, payee_nid, edge_type="added_payee")


def two_hop_money_subgraph(account_id: str) -> nx.DiGraph:
    """Undirected 2-hop neighbourhood over money edges, plus device nodes.

    GAT must not run on the full 500-node graph. This slice is what it sees.
    """
    graph = get_graph()
    money = nx.Graph()
    for src, dst, data in graph.edges(data=True):
        if data.get("edge_type") == "money":
            money.add_edge(src, dst)

    if account_id in money:
        hop_accounts = set(
            nx.single_source_shortest_path_length(money, account_id, cutoff=2)
        )
    else:
        hop_accounts = {account_id}

    keep = set(hop_accounts)
    for acc_id in hop_accounts:
        if acc_id not in graph:
            continue
        for _, dest, data in graph.out_edges(acc_id, data=True):
            if data.get("edge_type") == "used_device":
                keep.add(dest)

    return nx.DiGraph(graph.subgraph(keep).copy())


def node_features(account_id: str, subgraph: nx.DiGraph, session: Session) -> dict:
    """Feature dict for one account. Degrees and amounts use the FULL graph.

    `amount` on money edges is rupees (paise/100) so GAT scale matches the
    inherited weights. Never use it for ledger math.
    """
    graph = get_graph()
    # Degrees and amounts come from the full graph; the subgraph selects
    # which nodes GAT sees, not how this row is measured.
    _ = subgraph

    incoming = list(_money_edges(graph, account_id, "in"))
    outgoing = list(_money_edges(graph, account_id, "out"))

    in_degree = len(incoming)
    out_degree = len(outgoing)
    total_in_amount = sum(data.get("amount", 0.0) for _, _, data in incoming)
    total_out_amount = sum(data.get("amount", 0.0) for _, _, data in outgoing)

    if total_in_amount > 0:
        retention_ratio = max(0.0, (total_in_amount - total_out_amount) / total_in_amount)
    else:
        retention_ratio = 0.0

    neighbors: set[str] = set()
    channels: set[str] = set()
    for src, dst, data in incoming:
        neighbors.add(src)
        if data.get("channel"):
            channels.add(data["channel"])
    for src, dst, data in outgoing:
        neighbors.add(dst)
        if data.get("channel"):
            channels.add(data["channel"])

    account = session.get(Account, account_id)
    account_age_days = 0
    device_cluster_size = 1
    if account is not None:
        account_age_days = (_utc_now() - _aware(account.created_at)).days
        device_id = account.device_id
        peers = session.exec(
            select(Account).where(Account.device_id == device_id)
        ).all()
        device_cluster_size = len(peers)

    return {
        "account_id": account_id,
        "in_degree": in_degree,
        "out_degree": out_degree,
        "total_in_amount": total_in_amount,
        "total_out_amount": total_out_amount,
        "retention_ratio": retention_ratio,
        "unique_neighbors": len(neighbors),
        "unique_channels": len(channels),
        "device_cluster_size": device_cluster_size,
        "transaction_count": in_degree + out_degree,
        "account_age_days": account_age_days,
    }
