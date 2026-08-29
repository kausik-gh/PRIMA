"use strict";

let seen = new Set();
let seenOrder = [];

function txSignature(tx) {
  if (tx && tx.transaction_id) {
    return String(tx.transaction_id);
  }
  const source = String((tx && (tx.sender || tx.source)) || "");
  const target = String((tx && (tx.receiver || tx.target)) || "");
  const amount = Number((tx && tx.amount) || 0).toFixed(2);
  const timestamp = String((tx && tx.timestamp) || "");
  return `${source}-${target}-${amount}-${timestamp}`;
}

function normalizeTx(tx, suspicious) {
  return {
    sender: String((tx && tx.sender) || ""),
    receiver: String((tx && tx.receiver) || ""),
    amount: Number((tx && tx.amount) || 0),
    channel: String((tx && tx.channel) || "TXN"),
    is_attack: Boolean(tx && tx.is_attack),
    transaction_id: (tx && tx.transaction_id) ? String(tx.transaction_id) : "",
    timestamp: (tx && tx.timestamp) ? String(tx.timestamp) : "",
    suspicious: Boolean(suspicious),
  };
}

self.onmessage = (event) => {
  const payload = event.data || {};
  if (payload.type === "reset") {
    seen = new Set();
    seenOrder = [];
    return;
  }

  if (payload.type !== "ingest") {
    return;
  }

  const fraudIds = new Set((payload.fraudIds || []).map((v) => String(v)));
  const earlyIds = new Set((payload.earlyIds || []).map((v) => String(v)));
  const stage = String(payload.attackSequenceStage || "idle");
  const hasActiveAttack = Boolean(payload.activeAttackName);
  const maxSeen = Math.max(1000, Number(payload.maxSeen || 12000));
  const txs = Array.isArray(payload.transactions) ? payload.transactions : [];
  const prepared = [];

  for (let i = 0; i < txs.length; i += 1) {
    const tx = txs[i];
    const signature = txSignature(tx);
    if (seen.has(signature)) {
      continue;
    }
    seen.add(signature);
    seenOrder.push(signature);
    while (seenOrder.length > maxSeen) {
      const removed = seenOrder.shift();
      if (removed) {
        seen.delete(removed);
      }
    }

    const sender = String((tx && tx.sender) || "");
    const receiver = String((tx && tx.receiver) || "");
    const suspicious =
      fraudIds.has(sender) ||
      fraudIds.has(receiver) ||
      earlyIds.has(sender) ||
      earlyIds.has(receiver) ||
      Boolean(tx && tx.is_attack);

    const shouldSkipAttackTxVisual =
      Boolean(tx && tx.is_attack) &&
      stage !== "idle" &&
      hasActiveAttack;

    if (shouldSkipAttackTxVisual) {
      prepared.push(normalizeTx(tx, suspicious));
      continue;
    }

    prepared.push(normalizeTx(tx, suspicious));
  }

  self.postMessage({
    type: "prepared",
    transactions: prepared,
  });
};
