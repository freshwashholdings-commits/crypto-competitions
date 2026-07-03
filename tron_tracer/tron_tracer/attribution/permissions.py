"""Tier 1 signal: shared permission keys (blueprint Sec 6.1).

Tron's `owner_permission`/`active_permission` structures list the
addresses authorized to sign for an account (each `keys[].address`
entry is itself an account address, not a raw public key -- but
functionally it identifies "whoever holds this address's private key
can act for this account", which is exactly the signer identity the
blueprint's "shared key" signal is built on). If two different accounts'
permission structures list the same signer address, that is on-chain,
cryptographic-grade evidence of common control.
"""

from __future__ import annotations

from dataclasses import dataclass

from tron_tracer.ingest.address import normalize_address

TIER1_BASE_CONFIDENCE = 0.98


def extract_signer_addresses(permission: dict | None) -> set[str]:
    if not permission:
        return set()
    keys = permission.get("keys") or []
    signers = set()
    for k in keys:
        addr = k.get("address")
        if addr:
            signers.add(normalize_address(addr))
    return signers


def extract_all_signers(owner_permission: dict | None, active_permissions: list | None) -> set[str]:
    signers = set(extract_signer_addresses(owner_permission))
    for perm in active_permissions or []:
        signers |= extract_signer_addresses(perm)
    return signers


@dataclass
class SharedKeyLink:
    address_a: str
    address_b: str
    shared_signer: str
    confidence: float = TIER1_BASE_CONFIDENCE


def build_key_index(accounts: dict[str, dict]) -> dict[str, set[str]]:
    """accounts: {address: {'owner_permission': ..., 'active_permissions': ...}}
    Returns {signer_address: {account_address, ...}}."""
    index: dict[str, set[str]] = {}
    for address, acct in accounts.items():
        signers = extract_all_signers(acct.get("owner_permission"), acct.get("active_permissions"))
        for signer in signers:
            index.setdefault(signer, set()).add(address)
    return index


def find_shared_key_links(key_index: dict[str, set[str]]) -> list[SharedKeyLink]:
    """Any signer address appearing under >= 2 accounts creates pairwise links."""
    links: list[SharedKeyLink] = []
    for signer, holders in sorted(key_index.items()):
        ordered = sorted(holders)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                links.append(SharedKeyLink(address_a=ordered[i], address_b=ordered[j], shared_signer=signer))
    return links


def externally_controlled_by(address: str, owner_permission: dict | None) -> str | None:
    """If the account's owner permission is a single key that is NOT the
    account's own address, that account is directly controlled by
    another party -- return the controller's address, else None."""
    signers = extract_signer_addresses(owner_permission)
    if len(signers) == 1:
        (only,) = signers
        if only != address:
            return only
    return None
