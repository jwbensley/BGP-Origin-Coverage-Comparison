import json
import logging
from typing import Any

from radix import radix  # type: ignore

"""
Functions for loading, saving, parsing, comparing the origin data
"""


def write_json(data: Any, filename: str) -> None:
    with open(filename, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)
    logging.info(f"Wrote data to {filename}")


def load_json(filename: str) -> Any:
    logging.info(f"Loading data from {filename}")
    with open(filename, "r") as f:
        data = json.load(f)
    logging.info(f"Loaded {len(data):,} items from {filename}")
    return data


def load_tree_from_json(filename: str) -> radix.Radix:
    """
    Load a radix.Radix tree from a JSON file.
    """
    logging.info(f"Loading tree from {filename}")

    with open(filename, "r") as f:
        data = json.load(f)
    tree = radix.Radix()
    for prefix, value in data.items():
        node = tree.add(prefix)  # type: ignore
        if isinstance(value, dict):
            # IRR/ROA data: {"origins": [...], "max_length": N}
            node.data["origins"]: set[int] = set(value["origins"])  # type: ignore
            node.data["max_length"] = int(value["max_length"])  # type: ignore
        elif isinstance(value, list):
            # DFZ data: plain list of origin ASNs
            node.data["origins"] = set(value)  # type: ignore

    logging.info(f"Loaded {len(tree.nodes()):,} prefixes from {filename}")
    return tree


def find_covering_origins(tree: radix.Radix, prefix: str) -> set[int] | None:
    """
    Search `tree` for every node that covers `prefix` i.e., every equal or
    less-specific ancestor of it - since a single, more specific query prefix
    (e.g. a /22) can be covered by several registered entries of different
    lengths (e.g. a /16 and a /20), each potentially declaring a different
    origin ASN.

    Of those covering nodes, only the ones whose "max_length" is long
    enough to actually authorize a prefix as specific as `prefix` are kept
    (a node registered as /16 with a max_length of /24 covers queries up
    to /24, but not /25 and beyond).

    Returns the combined set of origin ASNs from all valid covering nodes,
    or None if no covering node was found within its allowed max_length.
    """
    query_length = int(prefix.rsplit("/", 1)[1])
    asns: set[int] = set()
    found = False

    for node in tree.search_covering(prefix):  # type: ignore
        if query_length <= node.data["max_length"]:  # type: ignore
            found = True
            asns.update(node.data["origins"])  # type: ignore

    return asns if found else None


def compare_origins(
    dfz_origins: radix.Radix,
    irr_origins: radix.Radix,
    roa_origins: radix.Radix,
    comparison_file: str,
    stats_file: str,
) -> dict[str, int]:
    """
        We need to do a three-way check between DFZ, IRR, and ROA data.

        Phase 1: First, this function compares every prefix in the DFZ to the IRR and ROA data.

        DFZ vs IRR:
        * It gets all prefixes in the IRR data which cover the DFZ prefix based on prefix length and the IRR prefixes max_length attribute
        (a DFZ prefix may be covered by an IRR prefix based on prefix length, but if the DFZ prefix is more specific, it must fit within the max_length attribute of the IRR prefix).
        * It builds a set of origin ASNs from all the covering prefixes found in the IRR data.
          * It compares each origin ASN of the prefix in the DFZ with each origin ASN in the set of IRR data origins.
          * If an ASN from the DFZ prefix is found in the IRR set, the DFZ origin ASN is added to dfz_irr_origin_matches[DFZ prefix].
          * If an ASN from the DFZ prefix is not found in the IRR set, the DFZ origin ASN is added to dfz_irr_origin_mismatches[DFZ prefix].
        * If no IRR prefix covers the DFZ prefix at all, the DFZ prefix is recorded in dfz_irr_prefix_not_found.
        DFZ vs ROA:
        * The same approach is used to compare the DFZ data to the ROA data.
        * It gets all prefixes in the ROA data which cover the DFZ prefix based on prefix length and the ROA prefixes max_length attribute
        (a DFZ prefix may be covered by a ROA prefix based on prefix length, but if the DFZ prefix is more specific, it must fit within the max_length attribute of the ROA prefix).
          * It builds a set of origin ASNs from all the covering prefixes found in the ROA data.
            * It compares each origin ASN of the prefix in the DFZ with each origin ASN in the set of ROA data origins.
            * If an ASN from the DFZ prefix is found in the ROA set, the DFZ origin ASN is added to dfz_roa_origin_matches[DFZ prefix].
            * If an ASN from the DFZ prefix is not found in the ROA set, the DFZ origin ASN is added to dfz_roa_origin_mismatches[DFZ prefix].
        * If no ROA prefix covers the DFZ prefix at all, the DFZ prefix is recorded in dfz_roa_prefix_not_found.

        Phase 2: Next this function compares every prefix in the IRR data, to the DFZ and ROA data.

        IRR vs DFZ:
        * Create empty skip-IRR-prefixes list.
        * A route(6) object in the IRR data can match equal length or more specific prefixes in the DFZ data
        (up to /24 for route objects and up to /48 for routes6 objects, because of how route(6) objects are converted to prefix filter entries).
        * However, a more specific route(6) object may exist in the IRR data than the IRR prefix currently being checked, with a different origin.
        * Therefore, loop over each IRR prefix, skip the prefix if it is in the list of skip-IRR-prefixes,
        if not, additionally get all more specific IRR prefixes based on prefix length only (no max_length attribute check here).
        * Then get all DFZ prefixes equal to or more specific than the IRR prefix currently being checked (based on prefix length only, no max_length attribute check here).
        * If the DFZ-sub-set of prefixes built for the IRR prefix is empty (no DFZ-sub-set prefixes exists at or below the IRR prefix), the IRR prefix is recorded in irr_dfz_prefix_not_found,
        move on to the next IRR prefix, and skip the rest of the steps below for this IRR prefix.
        * Using these two outer sub-sets of prefixes:
          * Loop over the IRR-outer-sub-set of prefixes from most specific to least specific.
            * For each IRR prefix in the IRR-outer-sub-set, get all DFZ prefixes from the DFZ-outer-sub-set equal to or more specific than the IRR-outer-sub-set prefix based on prefix length only (no max_length attribute check here).
            * Build a set of unique origin ASNs from these DFZ-inner-sub-set prefixes.
              * Compare each origin ASN of the IRR-outer-sub-set prefix with the set of DFZ origins just from the DFZ-inner-sub-set.
              * If an ASN from the IRR-outer-sub-set prefix is found in the DFZ origin set, the IRR origin ASN is added to irr_dfz_origin_matches[IRR prefix].
              * If an ASN from the IRR-outer-sub-set prefix is not found in the DFZ origin set, the IRR origin ASN is added to irr_dfz_origin_mismatches[IRR prefix].
            * After checking all the origins of the IRR-outer-sub-set prefix, remove the prefixes in the DFZ-inner-sub-set from the DFZ-outer-sub-set.
        * To avoid double counting, we need to add the IRR prefixes in the IRR-outer-sub-set to skip-IRR-prefixes, and skip them as we continue the IRR-vs-DFZ loop over the remaining IRR prefixes.
        IRR vs ROA:
        * To match IRR route(6) objects (IRR prefixes) to ROA data, we need to do two separate matching steps.
        * First, match covering ROAs.
          * No skip list here.
          * For each IRR prefix, get all covering (equal length or shorter) ROA prefixes based on prefix length and based on the max_length attribute of the ROA prefixes
          (even though a ROA prefix length may be short/less specific than the IRR prefix length, it might not cover the IRR prefix if the ROA prefix has a max_length that is shorter than the IRR prefix length).
            * If no covering ROA prefixes are found for the current IRR prefix, the IRR prefix is recorded in irr_roa_prefix_not_found, and the rest of the steps below are skipped for this IRR prefix.
            * Build a set of origin ASNs from all the covering ROA prefixes found.
              * Compare each origin ASN of the current IRR prefix with each origin ASN in the set of ROA origins.
              * If an ASN from the IRR prefix is found in the ROA origin set, the IRR origin ASN is added to irr_roa_origin_matches[IRR prefix].
              * If an ASN from the IRR prefix is not found in the ROA origin set, the IRR origin ASN is added to irr_roa_origin_mismatches[IRR prefix].
        * Second, match more specific ROAs.
          * This step is needed because a route object (IRR prefix) for a /20, is converted into a prefix filter which matches /20-/24, and can be used to announce 4x /24s into the DFZ.
          * This may be implemented in the RPKI as 4x /24 ROAs.
          * Create empty skip-IRR-prefixes list.
          * For each IRR prefix, check if it is in the list of "to skip" IRR prefixes, if yes, skip the prefix,
          if not, additionally get all more specific IRR prefixes under the current IRR prefix based on prefix length only (no max_length attribute check here).
          * Then get all ROA prefixes equal to or more specific than the IRR prefix currently being checked, based on prefix length only (no max_length attribute check here).
          * Using these two sub-sets of prefixes:
            * For each ROA prefix in the ROA-sub-set, get all covering IRR prefixes from the IRR-sub-set based on prefix length only (no max_length attribute check here), then build a set of origin ASNs from these covering IRR prefixes sub-set.
              * Compare each origin ASN of the ROA prefix with the set of origin ASNs from the covering IRR prefixes.
              * If an ASN from the ROA-sub-set prefix is found in the IRR-sub-set origin set, the IRR origin ASN is added to irr_roa_origin_matches[IRR prefix].
              * If an ASN from the ROA-sub-set prefix is not found in the IRR-sub-set origin set, the IRR origin ASN is added to irr_roa_origin_mismatches[IRR prefix].
            * If the ROA-sub-set is empty (there are no ROA prefixes equal to or more specific than the IRR prefix), the IRR prefix is recorded in irr_roa_prefix_not_found.
          * To avoid double counting, we need to add the IRR prefixes in the IRR-sub-set to skip-IRR-prefixes, and skip them as we continue the IRR-vs-ROA loop over all IRR prefixes.

        Phase 3: Finally this function compares every prefix in the ROA data to the DFZ and IRR data.

        ROA vs DFZ:
        * Create empty skip-ROA-prefixes list.
        * For each ROA prefix, skip if it is in the list of skip-ROA-prefixes, if not,
        additionally get all more specific ROA prefixes under that prefix in the ROA data based on prefix length and the max_length attribute or the ROA prefixes
        (the more specific ROAs must fit within the max_length of the covering ROA prefix).
        * For the ROA prefix currently being checked, get all DFZ prefixes equal to or more specific than the ROA prefix based on prefix length and on the max_length attribute of the current ROA prefix
        (the more specific DFZ prefixes must fit within the max_length of the covering ROA prefix).
        * If the sub-set of DFZ prefixes is empty (no DFZ prefix exists at or below the ROA current prefix), the ROA prefix is recorded in roa_dfz_prefix_not_found and the rest of the steps below are skipped.
        * Using these two sub-sets of prefixes:
          * For each DFZ-sub-set prefix, get all covering ROA prefixes from the ROA-sub-set and build a set of unique origin ASNs from these covering prefixes.
            * Compare each origin ASN of the DFZ-sub-set prefix with the set of origin ASNs from the covering ROA-sub-set prefixes.
    !!        * If an ASN from the DFZ-sub-set prefix is found in the ROA-sub-set origin set, the ROA origin ASN is added to roa_dfz_origin_matches[DFZ-sub-set prefix].
    !!        * If an ASN from the DFZ-sub-set prefix is not found in the ROA-sub-set origin set, the ROA origin ASN is added to roa_dfz_origin_mismatches[DFZ-sub-set prefix].
        * To avoid double counting, we need to record the prefixes in this ROA prefix sub-set in skip-ROA-prefixes, and skip them as we continue the ROA-vs-DFZ loop over each ROA prefix.
        ROA vs IRR:
        * To match ROA prefixes to IRR data, we need to do two separate matching steps.
        * First, match covering IRR prefixes.
          * No skip list here.
          * For each ROA prefix, get all covering (equal length or shorter) IRR prefixes based on prefix length only (no max_length attribute check here).
          * This is because IRR route objects are expanded to /24 or /48 when building prefix filters.
          * If no covering IRR prefixes are found for the current ROA prefix, skip the rest of the steps below for this ROA prefix.
          * Build a set of origin ASNs from all the covering IRR prefixes found.
              * Compare each origin ASN of the ROA prefix with each origin ASN in the set of IRR covering prefix origins.
              * If an ASN from the ROA prefix is found in the IRR origin set, the ROA origin ASN is added to roa_irr_origin_matches[ROA prefix].
              * If an ASN from the ROA prefix is not found in the IRR origin set, the ROA origin ASN is added to roa_irr_origin_mismatches[ROA prefix].
        * Second, match more specific IRR prefixes.
          * This step is needed because a ROA for a /20 with max_length up to /24, can be used to announce 4x /24s into the DFZ.
          * This may be implemented in the IRR as 4x /24 route objects though.
          * Create empty skip-ROA-prefixes list.
          * For each ROA prefix, skip it if it is found in skip-ROA-prefixes, if not,
          additionally get all more specific ROA prefixes under the current ROA prefix based on prefix length only (no max_length attribute check here).
          * Then get all IRR prefixes more specific than the ROA prefix currently being checked based on prefix length only (no max_length attribute check here).
          * If the sub-set of IRR prefixes is empty (no IRR prefix exists at or below the current ROA prefix), the ROA prefix is recorded in roa_irr_prefix_not_found, and the rest of the steps for this ROA prefix are skipped.
          * Using these two sub-sets of prefixes:
              * For each IRR-sub-set prefix, get all covering ROA prefixes from the ROA-sub-set, based on prefix length and based on the max_length attribute of each ROA prefix in the sub-net.
                * From these ROA-sub-set prefixes, build a set of unique origin ASNs.
                * Compare each origin ASN of the IRR-sub-set prefix with the set of origin ASNs from the ROA-sub-set prefixes.
    !!            * If an ASN from the IRR-sub-set prefix is found in the ROA-sub-set origin set, the IRR origin ASN is added to roa_irr_origin_matches[IRR-sub-set prefix].
    !!            * If an ASN from the IRR-sub-set prefix is not found in the ROA-sub-set origin set, the IRR origin ASN is added to roa_irr_origin_mismatches[IRR-sub-set prefix].
          * To avoid double counting, we need to record the ROA prefixes in the ROA sub-set in the skip-ROA-prefixes list, and skip them as we continue to the ROA-vs-IRR loop.
    """
    logging.info(f"Comparing origins between DFZ<>IRR<>RPKI data")

    dfz_prefixes_v4 = len([n for n in dfz_origins.nodes() if ":" not in str(n.prefix)])  # type: ignore
    dfz_prefixes_v6 = len([n for n in dfz_origins.nodes() if ":" in str(n.prefix)])  # type: ignore
    dfz_irr_origin_matches: dict[str, list[int]] = {}
    dfz_irr_origin_matches_v4 = 0
    dfz_irr_origin_matches_v6 = 0
    dfz_irr_origin_mismatches: dict[str, list[int]] = {}
    dfz_irr_origin_mismatches_v4 = 0
    dfz_irr_origin_mismatches_v6 = 0
    dfz_irr_prefix_not_found: set[str] = set()
    dfz_irr_prefix_not_found_v4 = 0
    dfz_irr_prefix_not_found_v6 = 0
    dfz_roa_origin_matches: dict[str, list[int]] = {}
    dfz_roa_origin_matches_v4 = 0
    dfz_roa_origin_matches_v6 = 0
    dfz_roa_origin_mismatches: dict[str, list[int]] = {}
    dfz_roa_origin_mismatches_v4 = 0
    dfz_roa_origin_mismatches_v6 = 0
    dfz_roa_prefix_not_found: set[str] = set()
    dfz_roa_prefix_not_found_v4 = 0
    dfz_roa_prefix_not_found_v6 = 0
    irr_prefixes_v4 = len([n for n in irr_origins.nodes() if ":" not in str(n.prefix)])  # type: ignore
    irr_prefixes_v6 = len([n for n in irr_origins.nodes() if ":" in str(n.prefix)])  # type: ignore
    irr_dfz_origin_matches: dict[str, list[int]] = {}
    irr_dfz_origin_matches_v4 = 0
    irr_dfz_origin_matches_v6 = 0
    irr_dfz_origin_mismatches: dict[str, list[int]] = {}
    irr_dfz_origin_mismatches_v4 = 0
    irr_dfz_origin_mismatches_v6 = 0
    irr_dfz_prefix_not_found: set[str] = set()
    irr_dfz_prefix_not_found_v4 = 0
    irr_dfz_prefix_not_found_v6 = 0
    irr_roa_origin_matches: dict[str, list[int]] = {}
    irr_roa_origin_matches_v4 = 0
    irr_roa_origin_matches_v6 = 0
    irr_roa_origin_mismatches: dict[str, list[int]] = {}
    irr_roa_origin_mismatches_v4 = 0
    irr_roa_origin_mismatches_v6 = 0
    irr_roa_prefix_not_found: set[str] = set()
    irr_roa_prefix_not_found_v4 = 0
    irr_roa_prefix_not_found_v6 = 0
    roa_prefixes_v4 = len([n for n in roa_origins.nodes() if ":" not in str(n.prefix)])  # type: ignore
    roa_prefixes_v6 = len([n for n in roa_origins.nodes() if ":" in str(n.prefix)])  # type: ignore
    roa_dfz_origin_matches: dict[str, list[int]] = {}
    roa_dfz_origin_matches_v4 = 0
    roa_dfz_origin_matches_v6 = 0
    roa_dfz_origin_mismatches: dict[str, list[int]] = {}
    roa_dfz_origin_mismatches_v4 = 0
    roa_dfz_origin_mismatches_v6 = 0
    roa_dfz_prefix_not_found: set[str] = set()
    roa_dfz_prefix_not_found_v4 = 0
    roa_dfz_prefix_not_found_v6 = 0
    roa_irr_origin_matches: dict[str, list[int]] = {}
    roa_irr_origin_matches_v4 = 0
    roa_irr_origin_matches_v6 = 0
    roa_irr_origin_mismatches: dict[str, list[int]] = {}
    roa_irr_origin_mismatches_v4 = 0
    roa_irr_origin_mismatches_v6 = 0
    roa_irr_prefix_not_found: set[str] = set()
    roa_irr_prefix_not_found_v4 = 0
    roa_irr_prefix_not_found_v6 = 0

    # --- Pass 1: loop over DFZ prefixes, compare against IRR and ROA ---
    for dfz_node in dfz_origins.nodes():  # type: ignore
        prefix: str = str(dfz_node.prefix)
        dfz_asns: set[int] = set(dfz_node.data["origins"])

        # --- IRR comparison ---
        irr_asns_found = find_covering_origins(irr_origins, prefix)

        if irr_asns_found is not None:
            for dfz_asn in dfz_asns:
                if dfz_asn in irr_asns_found:
                    dfz_irr_origin_matches.append((prefix, dfz_asn))
                else:
                    # Convert irr_asns_found to list for JSON serialization
                    dfz_irr_origin_mismatches.append(
                        (prefix, dfz_asn, list(irr_asns_found))
                    )
        else:
            dfz_irr_prefix_not_found.append(prefix)

        # --- ROA comparison ---
        roa_asns_found = find_covering_origins(roa_origins, prefix)
        if roa_asns_found is not None:
            for dfz_asn in dfz_asns:
                if dfz_asn in roa_asns_found:
                    dfz_roa_origin_matches.append((prefix, dfz_asn))
                else:
                    # Convert roa_asns_found to list for JSON serialization
                    dfz_roa_origin_mismatches.append(
                        (prefix, dfz_asn, list(roa_asns_found))
                    )
        else:
            dfz_roa_prefix_not_found.append(prefix)

    # --- Pass 2: loop over IRR prefixes, compare against DFZ and ROA ---
    for irr_node in irr_origins.nodes():  # type: ignore
        prefix = str(irr_node.prefix)
        irr_asns = set(irr_node.data["origins"])

        # --- DFZ comparison ---
        dfz_node = dfz_origins.search_exact(prefix)  # type: ignore

        if dfz_node is not None:
            dfz_asns = set(dfz_node.data["origins"])
            for irr_asn in irr_asns:
                if irr_asn in dfz_asns:
                    irr_dfz_origin_matches.append((prefix, irr_asn))
                else:
                    # Convert dfz_asns to list for JSON serialization
                    irr_dfz_origin_mismatches.append(
                        (prefix, irr_asn, list(dfz_asns))
                    )
        else:
            irr_dfz_prefix_not_found.append(prefix)

        # --- ROA comparison ---
        roa_asns_found = find_covering_origins(roa_origins, prefix)
        if roa_asns_found is not None:
            for irr_asn in irr_asns:
                if irr_asn in roa_asns_found:
                    irr_roa_origin_matches.append((prefix, irr_asn))
                else:
                    # Convert roa_asns_found to list for JSON serialization
                    irr_roa_origin_mismatches.append(
                        (prefix, irr_asn, list(roa_asns_found))
                    )
        else:
            irr_roa_prefix_not_found.append(prefix)

    # --- Pass 3: loop over ROA prefixes, compare against DFZ and IRR ---
    for roa_node in roa_origins.nodes():  # type: ignore
        prefix = str(roa_node.prefix)
        roa_asns = set(roa_node.data["origins"])

        # --- DFZ comparison (always longest prefix match) ---
        dfz_node = dfz_origins.search_best(prefix)  # type: ignore
        if dfz_node is not None:
            dfz_asns = set(dfz_node.data["origins"])
            for roa_asn in roa_asns:
                if roa_asn in dfz_asns:
                    roa_dfz_origin_matches.append((prefix, roa_asn))
                else:
                    # Convert dfz_asns to list for JSON serialization
                    roa_dfz_origin_mismatches.append(
                        (prefix, roa_asn, list(dfz_asns))
                    )
        else:
            roa_dfz_prefix_not_found.append(prefix)

        # --- IRR comparison (always longest prefix match) ---
        irr_asns_found = find_covering_origins(irr_origins, prefix)
        if irr_asns_found is not None:
            for roa_asn in roa_asns:
                if roa_asn in irr_asns_found:
                    roa_irr_origin_matches.append((prefix, roa_asn))
                else:
                    # Convert irr_asns_found to list for JSON serialization
                    roa_irr_origin_mismatches.append(
                        (prefix, roa_asn, list(irr_asns_found))
                    )
        else:
            roa_irr_prefix_not_found.append(prefix)

    dfz_irr_origin_matches_v4 = len(
        [m for m in dfz_irr_origin_matches if ':' not in m[0]]
    )
    dfz_irr_origin_matches_v6 = (
        len(dfz_irr_origin_matches) - dfz_irr_origin_matches_v4
    )
    dfz_irr_origin_mismatches_v4 = len(
        [m for m in dfz_irr_origin_mismatches if ':' not in m[0]]
    )
    dfz_irr_origin_mismatches_v6 = (
        len(dfz_irr_origin_mismatches) - dfz_irr_origin_mismatches_v4
    )
    dfz_roa_origin_matches_v4 = len(
        [m for m in dfz_roa_origin_matches if ':' not in m[0]]
    )
    dfz_roa_origin_matches_v6 = (
        len(dfz_roa_origin_matches) - dfz_roa_origin_matches_v4
    )
    dfz_roa_origin_mismatches_v4 = len(
        [m for m in dfz_roa_origin_mismatches if ':' not in m[0]]
    )
    dfz_roa_origin_mismatches_v6 = (
        len(dfz_roa_origin_mismatches) - dfz_roa_origin_mismatches_v4
    )
    dfz_irr_prefix_not_found_v4 = len(
        [p for p in dfz_irr_prefix_not_found if ':' not in p]
    )
    dfz_irr_prefix_not_found_v6 = (
        len(dfz_irr_prefix_not_found) - dfz_irr_prefix_not_found_v4
    )
    dfz_roa_prefix_not_found_v4 = len(
        [p for p in dfz_roa_prefix_not_found if ':' not in p]
    )
    dfz_roa_prefix_not_found_v6 = (
        len(dfz_roa_prefix_not_found) - dfz_roa_prefix_not_found_v4
    )
    irr_dfz_origin_matches_v4 = len(
        [m for m in irr_dfz_origin_matches if ':' not in m[0]]
    )
    irr_dfz_origin_matches_v6 = (
        len(irr_dfz_origin_matches) - irr_dfz_origin_matches_v4
    )
    irr_dfz_origin_mismatches_v4 = len(
        [m for m in irr_dfz_origin_mismatches if ':' not in m[0]]
    )
    irr_dfz_origin_mismatches_v6 = (
        len(irr_dfz_origin_mismatches) - irr_dfz_origin_mismatches_v4
    )
    irr_roa_origin_matches_v4 = len(
        [m for m in irr_roa_origin_matches if ':' not in m[0]]
    )
    irr_roa_origin_matches_v6 = (
        len(irr_roa_origin_matches) - irr_roa_origin_matches_v4
    )
    irr_roa_origin_mismatches_v4 = len(
        [m for m in irr_roa_origin_mismatches if ':' not in m[0]]
    )
    irr_roa_origin_mismatches_v6 = (
        len(irr_roa_origin_mismatches) - irr_roa_origin_mismatches_v4
    )
    irr_dfz_prefix_not_found_v4 = len(
        [p for p in irr_dfz_prefix_not_found if ':' not in p]
    )
    irr_dfz_prefix_not_found_v6 = (
        len(irr_dfz_prefix_not_found) - irr_dfz_prefix_not_found_v4
    )
    irr_roa_prefix_not_found_v4 = len(
        [p for p in irr_roa_prefix_not_found if ':' not in p]
    )
    irr_roa_prefix_not_found_v6 = (
        len(irr_roa_prefix_not_found) - irr_roa_prefix_not_found_v4
    )
    roa_dfz_origin_matches_v4 = len(
        [m for m in roa_dfz_origin_matches if ':' not in m[0]]
    )
    roa_dfz_origin_matches_v6 = (
        len(roa_dfz_origin_matches) - roa_dfz_origin_matches_v4
    )
    roa_dfz_origin_mismatches_v4 = len(
        [m for m in roa_dfz_origin_mismatches if ':' not in m[0]]
    )
    roa_dfz_origin_mismatches_v6 = (
        len(roa_dfz_origin_mismatches) - roa_dfz_origin_mismatches_v4
    )
    roa_irr_origin_matches_v4 = len(
        [m for m in roa_irr_origin_matches if ':' not in m[0]]
    )
    roa_irr_origin_matches_v6 = (
        len(roa_irr_origin_matches) - roa_irr_origin_matches_v4
    )
    roa_irr_origin_mismatches_v4 = len(
        [m for m in roa_irr_origin_mismatches if ':' not in m[0]]
    )
    roa_irr_origin_mismatches_v6 = (
        len(roa_irr_origin_mismatches) - roa_irr_origin_mismatches_v4
    )
    roa_dfz_prefix_not_found_v4 = len(
        [p for p in roa_dfz_prefix_not_found if ':' not in p]
    )
    roa_dfz_prefix_not_found_v6 = (
        len(roa_dfz_prefix_not_found) - roa_dfz_prefix_not_found_v4
    )
    roa_irr_prefix_not_found_v4 = len(
        [p for p in roa_irr_prefix_not_found if ':' not in p]
    )
    roa_irr_prefix_not_found_v6 = (
        len(roa_irr_prefix_not_found) - roa_irr_prefix_not_found_v4
    )

    write_json(
        {
            "dfz_irr_origin_matches": dfz_irr_origin_matches,
            "dfz_irr_origin_mismatches": dfz_irr_origin_mismatches,
            "dfz_irr_prefix_not_found": dfz_irr_prefix_not_found,
            "dfz_roa_origin_matches": dfz_roa_origin_matches,
            "dfz_roa_origin_mismatches": dfz_roa_origin_mismatches,
            "dfz_roa_prefix_not_found": dfz_roa_prefix_not_found,
            "irr_dfz_origin_matches": irr_dfz_origin_matches,
            "irr_dfz_origin_mismatches": irr_dfz_origin_mismatches,
            "irr_dfz_prefix_not_found": irr_dfz_prefix_not_found,
            "irr_roa_origin_matches": irr_roa_origin_matches,
            "irr_roa_origin_mismatches": irr_roa_origin_mismatches,
            "irr_roa_prefix_not_found": irr_roa_prefix_not_found,
            "roa_dfz_origin_matches": roa_dfz_origin_matches,
            "roa_dfz_origin_mismatches": roa_dfz_origin_mismatches,
            "roa_dfz_prefix_not_found": roa_dfz_prefix_not_found,
            "roa_irr_origin_matches": roa_irr_origin_matches,
            "roa_irr_origin_mismatches": roa_irr_origin_mismatches,
            "roa_irr_prefix_not_found": roa_irr_prefix_not_found,
        },
        comparison_file,
    )

    stats = {
        "dfz_prefixes_v4": dfz_prefixes_v4,
        "dfz_prefixes_v6": dfz_prefixes_v6,
        "dfz_irr_origin_matches_v4": dfz_irr_origin_matches_v4,
        "dfz_irr_origin_matches_v6": dfz_irr_origin_matches_v6,
        "dfz_irr_origin_mismatches_v4": dfz_irr_origin_mismatches_v4,
        "dfz_irr_origin_mismatches_v6": dfz_irr_origin_mismatches_v6,
        "dfz_irr_prefix_not_found_v4": dfz_irr_prefix_not_found_v4,
        "dfz_irr_prefix_not_found_v6": dfz_irr_prefix_not_found_v6,
        "dfz_roa_origin_matches_v4": dfz_roa_origin_matches_v4,
        "dfz_roa_origin_matches_v6": dfz_roa_origin_matches_v6,
        "dfz_roa_origin_mismatches_v4": dfz_roa_origin_mismatches_v4,
        "dfz_roa_origin_mismatches_v6": dfz_roa_origin_mismatches_v6,
        "dfz_roa_prefix_not_found_v4": dfz_roa_prefix_not_found_v4,
        "dfz_roa_prefix_not_found_v6": dfz_roa_prefix_not_found_v6,
        "irr_prefixes_v4": irr_prefixes_v4,
        "irr_prefixes_v6": irr_prefixes_v6,
        "irr_dfz_origin_matches_v4": irr_dfz_origin_matches_v4,
        "irr_dfz_origin_matches_v6": irr_dfz_origin_matches_v6,
        "irr_dfz_origin_mismatches_v4": irr_dfz_origin_mismatches_v4,
        "irr_dfz_origin_mismatches_v6": irr_dfz_origin_mismatches_v6,
        "irr_dfz_prefix_not_found_v4": irr_dfz_prefix_not_found_v4,
        "irr_dfz_prefix_not_found_v6": irr_dfz_prefix_not_found_v6,
        "irr_roa_origin_matches_v4": irr_roa_origin_matches_v4,
        "irr_roa_origin_matches_v6": irr_roa_origin_matches_v6,
        "irr_roa_origin_mismatches_v4": irr_roa_origin_mismatches_v4,
        "irr_roa_origin_mismatches_v6": irr_roa_origin_mismatches_v6,
        "irr_roa_prefix_not_found_v4": irr_roa_prefix_not_found_v4,
        "irr_roa_prefix_not_found_v6": irr_roa_prefix_not_found_v6,
        "roa_prefixes_v4": roa_prefixes_v4,
        "roa_prefixes_v6": roa_prefixes_v6,
        "roa_dfz_origin_matches_v4": roa_dfz_origin_matches_v4,
        "roa_dfz_origin_matches_v6": roa_dfz_origin_matches_v6,
        "roa_dfz_origin_mismatches_v4": roa_dfz_origin_mismatches_v4,
        "roa_dfz_origin_mismatches_v6": roa_dfz_origin_mismatches_v6,
        "roa_dfz_prefix_not_found_v4": roa_dfz_prefix_not_found_v4,
        "roa_dfz_prefix_not_found_v6": roa_dfz_prefix_not_found_v6,
        "roa_irr_origin_matches_v4": roa_irr_origin_matches_v4,
        "roa_irr_origin_matches_v6": roa_irr_origin_matches_v6,
        "roa_irr_origin_mismatches_v4": roa_irr_origin_mismatches_v4,
        "roa_irr_origin_mismatches_v6": roa_irr_origin_mismatches_v6,
        "roa_irr_prefix_not_found_v4": roa_irr_prefix_not_found_v4,
        "roa_irr_prefix_not_found_v6": roa_irr_prefix_not_found_v6,
    }
    write_json(
        stats,
        stats_file,
    )

    return stats


def load_stats(filename: str) -> tuple[int, ...]:
    logging.info(f"Loading results stats from {filename}")

    with open(filename, "r") as f:
        data = json.load(f)

    return tuple(data.values())


def print_results(
    filename: str,
) -> None:

    (
        dfz_irr_origin_matches_v4,
        dfz_irr_origin_matches_v6,
        dfz_irr_origin_mismatches_v4,
        dfz_irr_origin_mismatches_v6,
        dfz_irr_prefix_not_found_v4,
        dfz_irr_prefix_not_found_v6,
        dfz_prefixes_v4,
        dfz_prefixes_v6,
        dfz_roa_origin_matches_v4,
        dfz_roa_origin_matches_v6,
        dfz_roa_origin_mismatches_v4,
        dfz_roa_origin_mismatches_v6,
        dfz_roa_prefix_not_found_v4,
        dfz_roa_prefix_not_found_v6,
        irr_dfz_origin_matches_v4,
        irr_dfz_origin_matches_v6,
        irr_dfz_origin_mismatches_v4,
        irr_dfz_origin_mismatches_v6,
        irr_dfz_prefix_not_found_v4,
        irr_dfz_prefix_not_found_v6,
        irr_prefixes_v4,
        irr_prefixes_v6,
        irr_roa_origin_matches_v4,
        irr_roa_origin_matches_v6,
        irr_roa_origin_mismatches_v4,
        irr_roa_origin_mismatches_v6,
        irr_roa_prefix_not_found_v4,
        irr_roa_prefix_not_found_v6,
        roa_dfz_origin_matches_v4,
        roa_dfz_origin_matches_v6,
        roa_dfz_origin_mismatches_v4,
        roa_dfz_origin_mismatches_v6,
        roa_dfz_prefix_not_found_v4,
        roa_dfz_prefix_not_found_v6,
        roa_irr_origin_matches_v4,
        roa_irr_origin_matches_v6,
        roa_irr_origin_mismatches_v4,
        roa_irr_origin_mismatches_v6,
        roa_irr_prefix_not_found_v4,
        roa_irr_prefix_not_found_v6,
        roa_prefixes_v4,
        roa_prefixes_v6,
    ) = load_stats(filename)

    logging.info(
        f"Total DFZ->IRR origin matches: {dfz_irr_origin_matches_v4 + dfz_irr_origin_matches_v6:,}"
    )
    logging.info(
        f"\tIPv4 DFZ->IRR origin matches: {dfz_irr_origin_matches_v4:,} ({(dfz_irr_origin_matches_v4 / dfz_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 DFZ->IRR origin matches: {dfz_irr_origin_matches_v6:,} ({(dfz_irr_origin_matches_v6 / dfz_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total DFZ->IRR origin mismatches: {dfz_irr_origin_mismatches_v4 + dfz_irr_origin_mismatches_v6:,}"
    )
    logging.info(
        f"\tIPv4 DFZ->IRR origin mismatches: {dfz_irr_origin_mismatches_v4:,} ({(dfz_irr_origin_mismatches_v4 / dfz_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 DFZ->IRR origin mismatches: {dfz_irr_origin_mismatches_v6:,} ({(dfz_irr_origin_mismatches_v6 / dfz_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total DFZ prefixes not found in IRR: {dfz_irr_prefix_not_found_v4 + dfz_irr_prefix_not_found_v6:,}"
    )
    logging.info(
        f"\tIPv4 DFZ prefixes not found in IRR: {dfz_irr_prefix_not_found_v4:,} ({(dfz_irr_prefix_not_found_v4 / dfz_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 DFZ prefixes not found in IRR: {dfz_irr_prefix_not_found_v6:,} ({(dfz_irr_prefix_not_found_v6 / dfz_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total DFZ->ROA origin matches: {dfz_roa_origin_matches_v4 + dfz_roa_origin_matches_v6:,}"
    )
    logging.info(
        f"\tIPv4 DFZ->ROA origin matches: {dfz_roa_origin_matches_v4:,} ({(dfz_roa_origin_matches_v4 / dfz_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 DFZ->ROA origin matches: {dfz_roa_origin_matches_v6:,} ({(dfz_roa_origin_matches_v6 / dfz_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total DFZ->ROA origin mismatches: {dfz_roa_origin_mismatches_v4 + dfz_roa_origin_mismatches_v6:,}"
    )
    logging.info(
        f"\tIPv4 DFZ->ROA origin mismatches: {dfz_roa_origin_mismatches_v4:,} ({(dfz_roa_origin_mismatches_v4 / dfz_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 DFZ->ROA origin mismatches: {dfz_roa_origin_mismatches_v6:,} ({(dfz_roa_origin_mismatches_v6 / dfz_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total DFZ prefixes not found in ROA: {dfz_roa_prefix_not_found_v4 + dfz_roa_prefix_not_found_v6:,}"
    )
    logging.info(
        f"\tIPv4 DFZ prefixes not found in ROA: {dfz_roa_prefix_not_found_v4:,} ({(dfz_roa_prefix_not_found_v4 / dfz_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 DFZ prefixes not found in ROA: {dfz_roa_prefix_not_found_v6:,} ({(dfz_roa_prefix_not_found_v6 / dfz_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total IRR->DFZ origin matches: {irr_dfz_origin_matches_v4 + irr_dfz_origin_matches_v6:,}"
    )
    logging.info(
        f"\tIPv4 IRR->DFZ origin matches: {irr_dfz_origin_matches_v4:,} ({(irr_dfz_origin_matches_v4 / irr_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 IRR->DFZ origin matches: {irr_dfz_origin_matches_v6:,} ({(irr_dfz_origin_matches_v6 / irr_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total IRR->DFZ origin mismatches: {irr_dfz_origin_mismatches_v4 + irr_dfz_origin_mismatches_v6:,}"
    )
    logging.info(
        f"\tIPv4 IRR->DFZ origin mismatches: {irr_dfz_origin_mismatches_v4:,} ({(irr_dfz_origin_mismatches_v4 / irr_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 IRR->DFZ origin mismatches: {irr_dfz_origin_mismatches_v6:,} ({(irr_dfz_origin_mismatches_v6 / irr_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total IRR prefixes not found in DFZ: {irr_dfz_prefix_not_found_v4 + irr_dfz_prefix_not_found_v6:,}"
    )
    logging.info(
        f"\tIPv4 IRR prefixes not found in DFZ: {irr_dfz_prefix_not_found_v4:,} ({(irr_dfz_prefix_not_found_v4 / irr_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 IRR prefixes not found in DFZ: {irr_dfz_prefix_not_found_v6:,} ({(irr_dfz_prefix_not_found_v6 / irr_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total IRR->ROA origin matches: {irr_roa_origin_matches_v4 + irr_roa_origin_matches_v6:,}"
    )
    logging.info(
        f"\tIPv4 IRR->ROA origin matches: {irr_roa_origin_matches_v4:,} ({(irr_roa_origin_matches_v4 / irr_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 IRR->ROA origin matches: {irr_roa_origin_matches_v6:,} ({(irr_roa_origin_matches_v6 / irr_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total IRR->ROA origin mismatches: {irr_roa_origin_mismatches_v4 + irr_roa_origin_mismatches_v6:,}"
    )
    logging.info(
        f"\tIPv4 IRR->ROA origin mismatches: {irr_roa_origin_mismatches_v4:,} ({(irr_roa_origin_mismatches_v4 / irr_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 IRR->ROA origin mismatches: {irr_roa_origin_mismatches_v6:,} ({(irr_roa_origin_mismatches_v6 / irr_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total IRR prefixes not found in ROA: {irr_roa_prefix_not_found_v4 + irr_roa_prefix_not_found_v6:,}"
    )
    logging.info(
        f"\tIPv4 IRR prefixes not found in ROA: {irr_roa_prefix_not_found_v4:,} ({(irr_roa_prefix_not_found_v4 / irr_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 IRR prefixes not found in ROA: {irr_roa_prefix_not_found_v6:,} ({(irr_roa_prefix_not_found_v6 / irr_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total ROA->DFZ origin matches: {roa_dfz_origin_matches_v4 + roa_dfz_origin_matches_v6:,}"
    )
    logging.info(
        f"\tIPv4 ROA->DFZ origin matches: {roa_dfz_origin_matches_v4:,} ({(roa_dfz_origin_matches_v4 / roa_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 ROA->DFZ origin matches: {roa_dfz_origin_matches_v6:,} ({(roa_dfz_origin_matches_v6 / roa_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total ROA->DFZ origin mismatches: {roa_dfz_origin_mismatches_v4 + roa_dfz_origin_mismatches_v6:,}"
    )
    logging.info(
        f"\tIPv4 ROA->DFZ origin mismatches: {roa_dfz_origin_mismatches_v4:,} ({(roa_dfz_origin_mismatches_v4 / roa_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 ROA->DFZ origin mismatches: {roa_dfz_origin_mismatches_v6:,} ({(roa_dfz_origin_mismatches_v6 / roa_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total ROA prefixes not found in DFZ: {roa_dfz_prefix_not_found_v4 + roa_dfz_prefix_not_found_v6:,}"
    )
    logging.info(
        f"\tIPv4 ROA prefixes not found in DFZ: {roa_dfz_prefix_not_found_v4:,} ({(roa_dfz_prefix_not_found_v4 / roa_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 ROA prefixes not found in DFZ: {roa_dfz_prefix_not_found_v6:,} ({(roa_dfz_prefix_not_found_v6 / roa_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total ROA->IRR origin matches: {roa_irr_origin_matches_v4 + roa_irr_origin_matches_v6:,}"
    )
    logging.info(
        f"\tIPv4 ROA->IRR origin matches: {roa_irr_origin_matches_v4:,} ({(roa_irr_origin_matches_v4 / roa_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 ROA->IRR origin matches: {roa_irr_origin_matches_v6:,} ({(roa_irr_origin_matches_v6 / roa_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total ROA->IRR origin mismatches: {roa_irr_origin_mismatches_v4 + roa_irr_origin_mismatches_v6:,}"
    )
    logging.info(
        f"\tIPv4 ROA->IRR origin mismatches: {roa_irr_origin_mismatches_v4:,} ({(roa_irr_origin_mismatches_v4 / roa_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 ROA->IRR origin mismatches: {roa_irr_origin_mismatches_v6:,} ({(roa_irr_origin_mismatches_v6 / roa_prefixes_v6) * 100:.2f}%)"
    )

    logging.info(
        f"Total ROA prefixes not found in IRR: {roa_irr_prefix_not_found_v4 + roa_irr_prefix_not_found_v6:,}"
    )
    logging.info(
        f"\tIPv4 ROA prefixes not found in IRR: {roa_irr_prefix_not_found_v4:,} ({(roa_irr_prefix_not_found_v4 / roa_prefixes_v4) * 100:.2f}%)"
    )
    logging.info(
        f"\tIPv6 ROA prefixes not found in IRR: {roa_irr_prefix_not_found_v6:,} ({(roa_irr_prefix_not_found_v6 / roa_prefixes_v6) * 100:.2f}%)"
    )
