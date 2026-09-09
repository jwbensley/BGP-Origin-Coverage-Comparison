import logging
import orjson
from typing import Any

from radix import radix  # type: ignore

"""
Functions for loading, saving, parsing, comparing the origin data
"""


def write_json(data: Any, filename: str) -> None:
    with open(filename, "w") as f:
        f.write(
            orjson.dumps(
                data,
                option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
                default=str,
            ).decode("utf-8")
        )
    logging.info(f"Wrote data to {filename}")


def load_json(filename: str) -> Any:
    logging.info(f"Loading data from {filename}")
    with open(filename, "r") as f:
        data = orjson.loads(f.read())
    logging.info(f"Loaded {len(data):,} items from {filename}")
    return data


def load_stats(filename: str) -> tuple[int, ...]:
    logging.info(f"Loading results stats from {filename}")

    with open(filename, "r") as f:
        data = orjson.loads(f.read())

    return tuple(data.values())


def load_tree_from_json(filename: str) -> radix.Radix:
    """
    Load a radix.Radix tree from a JSON file.
    """
    logging.info(f"Loading tree from {filename}")

    with open(filename, "r") as f:
        data = orjson.loads(f.read())
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


def find_covering_origins(
    tree: radix.Radix, prefix: str, check_max_length: bool = True
) -> set[int]:
    """
    Search `tree` for every node that covers `prefix` i.e., every equal or
    less-specific ancestor of it - since a single, more specific query prefix
    (e.g. a /22) can be covered by several registered entries of different
    lengths (e.g. a /16 and a /20), each potentially declaring a different
    origin ASN.

    If `check_max_length` is True, only covering nodes whose "max_length" is
    long enough to actually authorize a prefix as specific as `prefix` are
    kept (a node registered as /16 with a max_length of /24 covers queries
    up to /24, but not /25 and beyond). If False, every covering node counts
    regardless of its "max_length".
    """
    query_length = int(prefix.rsplit("/", 1)[1])
    asns: set[int] = set()

    for node in tree.search_covering(prefix):  # type: ignore
        if not check_max_length or query_length <= node.data["max_length"]:  # type: ignore
            asns.update(node.data["origins"])  # type: ignore

    return asns


def origins_from_nodes(nodes: list[Any]) -> set[int]:
    """
    Union of origin ASNs across a list of radix tree nodes.
    """
    asns: set[int] = set()
    for node in nodes:
        asns.update(node.data["origins"])  # type: ignore
    return asns


def covered_nodes(
    tree: radix.Radix,
    prefix: str,
    min_prefixlen: int,
) -> list[Any]:
    """
    Nodes in `tree` that are covered by `prefix` based on prefix length.
    min_prefixlen can be used to get more specific nodes, instead of equal to OR more specific.
    """
    nodes: list[Any] = tree.search_covered(prefix)  # type: ignore
    nodes = [n for n in nodes if n.prefixlen >= min_prefixlen]  # type: ignore
    return list(nodes)


def assert_no_overlap(
    matches: dict[str, list[int]], mismatches: dict[str, list[int]]
) -> None:
    """
    Assert no prefix has the same ASN recorded as both a match and a mismatch.
    """
    for prefix in set(matches) | set(mismatches):
        overlap = set(matches.get(prefix, [])) & set(
            mismatches.get(prefix, [])
        )
        assert (
            not overlap
        ), f"ASN(s) {overlap} recorded as both a match and a mismatch for {prefix}"


def split_v4_v6_counts(entries: dict[str, list[int]]) -> tuple[int, int]:
    """
    Split the total number of ASN entries across all prefixes into (v4, v6) counts.
    """
    v4 = sum(
        len(asns) for prefix, asns in entries.items() if ":" not in prefix
    )
    return v4, sum(len(asns) for asns in entries.values()) - v4


def split_v4_v6_prefixes(prefixes: set[str]) -> tuple[int, int]:
    """
    Split a set of prefixes into (v4, v6) counts.
    """
    v4 = sum(1 for prefix in prefixes if ":" not in prefix)
    return v4, len(prefixes) - v4


def compare_origins(
    dfz_origins: radix.Radix,
    irr_origins: radix.Radix,
    roa_origins: radix.Radix,
    comparison_file: str,
    stats_file: str,
) -> dict[str, int]:
    """
    We need to do a three-way check between DFZ, IRR, and ROA data.
    """
    logging.info(f"Comparing origins between DFZ<>IRR<>RPKI data")

    dfz_prefixes_v4 = len([n for n in dfz_origins.nodes() if ":" not in str(n.prefix)])  # type: ignore
    dfz_prefixes_v6 = len([n for n in dfz_origins.nodes() if ":" in str(n.prefix)])  # type: ignore
    irr_prefixes_v4 = len([n for n in irr_origins.nodes() if ":" not in str(n.prefix)])  # type: ignore
    irr_prefixes_v6 = len([n for n in irr_origins.nodes() if ":" in str(n.prefix)])  # type: ignore
    roa_prefixes_v4 = len([n for n in roa_origins.nodes() if ":" not in str(n.prefix)])  # type: ignore
    roa_prefixes_v6 = len([n for n in roa_origins.nodes() if ":" in str(n.prefix)])  # type: ignore

    dfz_irr_origin_matches: dict[str, list[int]] = {}
    dfz_irr_origin_mismatches: dict[str, list[int]] = {}
    dfz_irr_prefix_not_found: set[str] = set()
    dfz_roa_origin_matches: dict[str, list[int]] = {}
    dfz_roa_origin_mismatches: dict[str, list[int]] = {}
    dfz_roa_prefix_not_found: set[str] = set()
    irr_dfz_origin_matches: dict[str, list[int]] = {}
    irr_dfz_origin_mismatches: dict[str, list[int]] = {}
    irr_dfz_prefix_not_found: set[str] = set()
    irr_roa_origin_matches: dict[str, list[int]] = {}
    irr_roa_origin_mismatches: dict[str, list[int]] = {}
    irr_roa_prefix_not_found: set[str] = set()
    roa_dfz_origin_matches: dict[str, list[int]] = {}
    roa_dfz_origin_mismatches: dict[str, list[int]] = {}
    roa_dfz_prefix_not_found: set[str] = set()
    roa_irr_origin_matches: dict[str, list[int]] = {}
    roa_irr_origin_mismatches: dict[str, list[int]] = {}
    roa_irr_prefix_not_found: set[str] = set()

    """
      Phase 1: First, this function compares every prefix in the DFZ to the IRR and ROA data.
      DFZ vs IRR:
      * For each DFZ prefix:
        * It gets all prefixes in the IRR data which cover the DFZ prefix based on prefix length and the IRR prefixes max_length attribute
          (a DFZ prefix may be covered by an IRR prefix based on prefix length, but if the DFZ prefix is more specific, it must fit within the max_length attribute of the IRR prefix).
        * It builds a set of origin ASNs from all the covering IRR prefixes found.
        * It compares each origin ASN of the prefix in the DFZ with each origin ASN in the set of IRR data origins.
          * If an ASN from the DFZ prefix is found in the IRR set, the DFZ origin ASN is added to dfz_irr_origin_matches[DFZ prefix].
          * If an ASN from the DFZ prefix is not found in the IRR set, the DFZ origin ASN is added to dfz_irr_origin_mismatches[DFZ prefix].
        * If no IRR prefix covers the DFZ prefix at all, the DFZ prefix is recorded in dfz_irr_prefix_not_found.
      DFZ vs ROA:
      * For each DFZ prefix:
        * It gets all prefixes in the ROA data which cover the DFZ prefix based on prefix length and the ROA prefixes max_length attribute
          (a DFZ prefix may be covered by a ROA prefix based on prefix length, but if the DFZ prefix is more specific, it must fit within the max_length attribute of the ROA prefix).
        * It builds a set of origin ASNs from all the covering prefixes found in the ROA data.
        * It compares each origin ASN of the prefix in the DFZ with each origin ASN in the set of ROA data origins.
          * If an ASN from the DFZ prefix is found in the ROA set, the DFZ origin ASN is added to dfz_roa_origin_matches[DFZ prefix].
          * If an ASN from the DFZ prefix is not found in the ROA set, the DFZ origin ASN is added to dfz_roa_origin_mismatches[DFZ prefix].
        * If no ROA prefix covers the DFZ prefix at all, the DFZ prefix is recorded in dfz_roa_prefix_not_found.
      At the end of phase 1:
        * Loop over all prefixes in dfz_irr_origin_matches, and assert that no ASNs in dfz_irr_origin_matches[prefix] are in dfz_irr_origin_mismatches[prefix], and vice versa.
        * Loop over all prefixes in dfz_roa_origin_matches, and assert that no ASNs in dfz_roa_origin_matches[prefix] are in dfz_roa_origin_mismatches[prefix], and vice versa.
    """
    logging.info(
        f"Phase 1: Comparing every prefix in the DFZ to the IRR and ROA data"
    )
    for dfz_node in dfz_origins.nodes():  # type: ignore
        prefix = str(dfz_node.prefix)  # type: ignore
        dfz_asns: set[int] = set(dfz_node.data["origins"])  # type: ignore

        # DFZ vs IRR
        irr_covering_asns = find_covering_origins(irr_origins, prefix)
        if not irr_covering_asns:
            dfz_irr_prefix_not_found.add(prefix)
        else:
            for asn in dfz_asns:
                bucket = (
                    dfz_irr_origin_matches
                    if asn in irr_covering_asns
                    else dfz_irr_origin_mismatches
                )
                bucket.setdefault(prefix, []).append(asn)

        # DFZ vs ROA
        roa_covering_asns = find_covering_origins(roa_origins, prefix)
        if not roa_covering_asns:
            dfz_roa_prefix_not_found.add(prefix)
        else:
            for asn in dfz_asns:
                bucket = (
                    dfz_roa_origin_matches
                    if asn in roa_covering_asns
                    else dfz_roa_origin_mismatches
                )
                bucket.setdefault(prefix, []).append(asn)

    assert_no_overlap(dfz_irr_origin_matches, dfz_irr_origin_mismatches)
    assert_no_overlap(dfz_roa_origin_matches, dfz_roa_origin_mismatches)

    """
      Phase 2: Next this function compares every prefix in the IRR data, to the DFZ and ROA data.
  
      IRR vs DFZ:
      * Create empty skip-IRR-prefixes list.
      * A route(6) object in the IRR data can match equal length or more specific prefixes in the DFZ data
        (up to /24 for route objects and up to /48 for routes6 objects, because of how route(6) objects are converted to prefix filter entries).
      * However, a more specific route(6) object may exist in the IRR data than the IRR prefix currently being checked, with a different origin.
      * Therefore, loop over each IRR prefix:
        * Skip the IRR prefix if it is in the list of skip-IRR-prefixes, if not, create a sub-set of IRR prefixes
          using the current IRR prefix and additionally all more specific IRR prefixes based on prefix length only (no max_length attribute check here).
        * From this sub-set of IRR prefixes, build a set of unique origin ASNs from all the prefixes in the IRR-sub-set.
        * Then create a DFZ sub-set of all DFZ prefixes equal to or more specific than the IRR prefix currently being checked
          (based on prefix length only, no max_length attribute check here).
        * If the DFZ-sub-set of prefixes built for the IRR prefix is empty (no DFZ-sub-set prefixes exists at or below the IRR prefix), the IRR prefix is recorded in irr_dfz_prefix_not_found,
          move on to the next IRR prefix, and skip the rest of the IRR vs DFZ steps below for this IRR prefix.
        * From the sub-set of DFZ prefixes, build a set of unique origin ASNs from all the prefixes in the DFZ-sub-set.
        * Compare the two sets of unique origin ASNs from the IRR-sub-set and the DFZ-sub-set.
          * If an ASN from the IRR-sub-set is found in the DFZ-sub-set origin set, the IRR origin ASN is added to irr_dfz_origin_matches[IRR prefix].
          * If an ASN from the IRR-sub-set is not found in the DFZ-sub-set origin set, the IRR origin ASN is added to irr_dfz_origin_mismatches[IRR prefix].
        * To avoid double counting, we need to record the prefixes in the IRR prefix sub-set in skip-IRR-prefixes, and skip them as we continue the IRR-vs-DFZ loop over each IRR prefix.
      IRR vs ROA:
      * To match IRR route(6) objects (IRR prefixes) to ROA data, we need to do two separate matching steps.
      * First, match covering ROAs.
      * No skip list here.
      * For each IRR prefix:
        * Get all covering (equal length or shorter) ROA prefixes based on prefix length and based on the max_length attribute of the ROA prefixes
          (even though a ROA prefix length may be short/less specific than the IRR prefix length, it might not cover the IRR prefix if the ROA prefix has a max_length
          that is shorter than the IRR prefix length).
        * If no covering ROA prefixes are found for the current IRR prefix, the IRR prefix is recorded in irr_roa_prefix_not_found, and the rest of the steps below
          for this first phase of IRR vs ROA are skipped for this IRR prefix.
        * Build a set of origin ASNs from all the covering ROA prefixes found.
        * Compare each origin ASN of the current IRR prefix with each origin ASN in the set of ROA origins.
          * If an ASN from the IRR prefix is found in the ROA origin set, the IRR origin ASN is added to irr_roa_origin_matches[IRR prefix].
          * If an ASN from the IRR prefix is not found in the ROA origin set, the IRR origin ASN is added to irr_roa_origin_mismatches[IRR prefix].
      * Second, match more specific ROAs.
      * This step is needed because a route object (IRR prefix) for a /22, is converted into a prefix filter which matches /22-/24, and can be used to announce 4x /24s into the DFZ.
      * This may be implemented in the RPKI as 2x /23 ROAs each with max length /24.
      * Create empty skip-IRR-prefixes list.
      * For each IRR prefix:
        * Create a sub-set of all ROA prefixes more specific than the IRR prefix currently being checked, based on prefix length only
          (no max_length attribute check here because IRR prefixes don't have a max_length).
        * If the sub-set of ROA prefixes is empty (no ROA prefix exists below the current IRR prefix), the IRR prefix is recorded in irr_roa_prefix_not_found,
          and the rest of the steps for IRR vs ROA for this prefix are skipped.
        * Create a set of unique origin ASNs from all the prefixes in the ROA-sub-set.
        * Compare the IRR prefix origin ASNs against the set of unique origin ASNs from the ROA-sub-set.
          * If an ASN from the IRR prefix origins is found in the ROA-sub-set origin set, the IRR origin ASN is added to irr_roa_origin_matches[IRR prefix].
          * If an ASN from the IRR prefix origins is not found in the ROA-sub-set origin set, the IRR origin ASN is added to irr_roa_origin_mismatches[IRR prefix].
      At the end of phase 2:
        * Loop over all prefixes in irr_dfz_origin_matches, and assert that no ASNs in irr_dfz_origin_matches[prefix] are in irr_dfz_origin_mismatches[prefix], and vice versa.
        * Loop over all prefixes in irr_roa_origin_matches, and assert that no ASNs in irr_roa_origin_matches[prefix] are in irr_roa_origin_mismatches[prefix], and vice versa.
    """
    logging.info(
        f"Phase 2: Comparing every prefix in the IRR data to the DFZ and ROA data"
    )

    # IRR vs DFZ:
    # irr_dfz_skip: set[str] = set()
    for irr_node in irr_origins.nodes():  # type: ignore
        prefix = str(irr_node.prefix)  # type: ignore
        # if prefix in irr_dfz_skip:
        #    continue

        irr_subset_nodes = covered_nodes(irr_origins, prefix, min_prefixlen=irr_node.prefixlen)  # type: ignore
        irr_subset_asns = origins_from_nodes(irr_subset_nodes)

        dfz_subset_nodes = covered_nodes(dfz_origins, prefix, min_prefixlen=irr_node.prefixlen)  # type: ignore
        if not dfz_subset_nodes:
            irr_dfz_prefix_not_found.add(prefix)
        else:
            dfz_subset_asns = origins_from_nodes(dfz_subset_nodes)
            for asn in irr_subset_asns:
                bucket = (
                    irr_dfz_origin_matches
                    if asn in dfz_subset_asns
                    else irr_dfz_origin_mismatches
                )
                bucket.setdefault(prefix, []).append(asn)

        # irr_dfz_skip.update(str(n.prefix) for n in irr_subset_nodes)  # type: ignore

    # IRR vs ROA:
    # irr_roa_step_1_found = 0
    # irr_roa_step_1_not_found = 0
    # irr_roa_step_2_found = 0
    # irr_roa_step_2_not_found = 0
    for irr_node in irr_origins.nodes():  # type: ignore
        prefix = str(irr_node.prefix)  # type: ignore
        step_1_not_found = False
        step_2_not_found = False

        # Step 1: match against covering ROA prefixes.
        roa_covering_asns = find_covering_origins(roa_origins, prefix)
        if roa_covering_asns:
            # irr_roa_step_1_found += 1
            irr_asns: set[int] = set(irr_node.data["origins"])  # type: ignore
            for asn in irr_asns:
                bucket = (
                    irr_roa_origin_matches
                    if asn in roa_covering_asns
                    else irr_roa_origin_mismatches
                )
                bucket.setdefault(prefix, []).append(asn)
        else:
            # irr_roa_step_1_not_found += 1
            step_1_not_found = True

            # # Step 2: match against more specific ROA prefixes
            # roa_subset_nodes = covered_nodes(roa_origins, prefix, min_prefixlen=irr_node.prefixlen + 1)  # type: ignore
            # if roa_subset_nodes:
            #     irr_roa_step_2_found += 1
            #     roa_subset_asns = origins_from_nodes(roa_subset_nodes)
            #     for asn in irr_node.data["origins"]:  # type: ignore
            #         bucket = (
            #             irr_roa_origin_matches
            #             if asn in roa_subset_asns
            #             else irr_roa_origin_mismatches
            #         )
            #         bucket.setdefault(prefix, []).append(asn)  # type: ignore

            # else:
            #     irr_roa_step_2_not_found += 1
            #     step_2_not_found = True
            step_2_not_found = True

        if step_1_not_found and step_2_not_found:
            irr_roa_prefix_not_found.add(prefix)

    # logging.info(
    #     f"IRR vs ROA: Step 1 found {irr_roa_step_1_found:,}, not found {irr_roa_step_1_not_found:,}"
    # )
    # logging.info(
    #     f"IRR vs ROA: Step 2 found {irr_roa_step_2_found:,}, not found {irr_roa_step_2_not_found:,}"
    # )

    assert_no_overlap(irr_dfz_origin_matches, irr_dfz_origin_mismatches)
    assert_no_overlap(irr_roa_origin_matches, irr_roa_origin_mismatches)

    """
    Phase 3: Finally this function compares every prefix in the ROA data to the DFZ and IRR data.

    ROA vs DFZ:
    * Create empty skip-ROA-prefixes list.
    * For each ROA prefix:
      * Skip if it is in the list of skip-ROA-prefixes, if not, create a sub-set of prefixes from the current loop prefix and
        additionally get all more specific ROA prefixes under that prefix in the ROA data, based on prefix length and the max_length attribute of the ROA prefixes
        (the more specific ROAs must fit within the max_length of the covering ROA prefix).
      * From this sub-set of ROA prefixes, build a set of unique origin ASNs from all the prefixes in the ROA-sub-set.
      * Get all equal to or more specific DFZ prefixes from the DFZ data based on prefix length and the max_length attribute of the current ROA prefix.
        * If no DFZ prefixes are found, add the ROA prefix to roa_dfz_prefix_not_found, skip the rest of the ROA vs DFZ steps below for this ROA prefix.
      * From the sub-set of DFZ prefixes, build a set of unique origin ASNs from all the prefixes in the DFZ-sub-set.
        * Compare the two sets of unique origin ASNs from the ROA-sub-set and the DFZ-sub-set.
          * If an ASN from the ROA-sub-set is found in the DFZ-sub-set origin set, the ROA origin ASN is added to roa_dfz_origin_matches[ROA prefix].
          * If an ASN from the ROA-sub-set is not found in the DFZ-sub-set origin set, the ROA origin ASN is added to roa_dfz_origin_mismatches[ROA prefix].
      * To avoid double counting, we need to record the prefixes in the ROA prefix sub-set in skip-ROA-prefixes, and skip them as we continue the ROA-vs-DFZ loop over each ROA prefix.
    ROA vs IRR:
    * To match ROA prefixes to IRR data, we need to do two separate matching steps.
    * First, match covering IRR prefixes.
    * No skip list here.
    * For each ROA prefix:
      * Get all covering (equal length or shorter) IRR prefixes based on prefix length only (no max_length attribute check here).
      * This is because IRR route objects are expanded to /24 or /48 when building prefix filters.
      * If no covering IRR prefixes are found for the current ROA prefix, skip the rest of the steps below for this ROA prefix.
      * Build a set of origin ASNs from all the covering IRR prefixes found.
      * Compare each origin ASN of the ROA prefix with each origin ASN in the set of IRR covering prefix origins.
        * If an ASN from the ROA prefix is found in the IRR origin set, the ROA origin ASN is added to roa_irr_origin_matches[ROA prefix].
        * If an ASN from the ROA prefix is not found in the IRR origin set, the ROA origin ASN is added to roa_irr_origin_mismatches[ROA prefix].
    * Second, match more specific IRR prefixes.
    * This step is needed because a ROA for a /22 with max_length up to /24, can be used to announce 4x /24s into the DFZ.
    * This may be implemented in the IRR as 4x /24 route objects though.
    * Create empty skip-ROA-prefixes list.
    * For each ROA prefix:
      * Create a sub-set of all IRR prefixes more specific than the ROA prefix currently being checked, based on prefix length only
        (no max_length attribute check here because IRR prefixes do not have a max_length attribute).
      * If the sub-set of IRR prefixes is empty (no IRR prefix exists below the current ROA prefix), the ROA prefix is recorded in roa_irr_prefix_not_found, and the rest of the steps for ROA vs IRR for this prefix are skipped.
      * Create a set of unique origin ASNs from all the prefixes in the IRR-sub-set.
      * Compare the ROA prefix origins to the set of unique origin ASNs from the IRR-sub-set.
        * If an ASN from the ROA prefix origins is found in the IRR-sub-set origin set, the ROA origin ASN is added to roa_irr_origin_matches[ROA prefix].
        * If an ASN from the ROA prefix origins is not found in the IRR-sub-set origin set, the ROA origin ASN is added to roa_irr_origin_mismatches[ROA prefix].
    At the end of phase 3:
      * Loop over all prefixes in roa_dfz_origin_matches, and assert that no ASNs in roa_dfz_origin_matches[prefix] are in roa_dfz_origin_mismatches[prefix], and vice versa.
      * Loop over all prefixes in roa_irr_origin_matches, and assert that no ASNs in roa_irr_origin_matches[prefix] are in roa_irr_origin_mismatches[prefix], and vice versa.
    """
    logging.info(
        f"Phase 3: Comparing every prefix in the ROA data to the DFZ and IRR data"
    )
    # ROA vs DFZ
    # roa_dfz_skip: set[str] = set()
    for roa_node in roa_origins.nodes():  # type: ignore
        prefix = str(roa_node.prefix)  # type: ignore
        # if prefix in roa_dfz_skip:
        #    continue

        roa_subset_nodes = [
            n
            for n in covered_nodes(
                roa_origins, prefix, min_prefixlen=roa_node.prefixlen  # type: ignore
            )
            if n.prefixlen <= roa_node.data["max_length"]  # type: ignore
        ]
        roa_subset_asns = origins_from_nodes(roa_subset_nodes)

        dfz_subset_nodes = [
            n
            for n in covered_nodes(
                dfz_origins, prefix, min_prefixlen=roa_node.prefixlen  # type: ignore
            )
            if n.prefixlen <= roa_node.data["max_length"]  # type: ignore
        ]

        if not dfz_subset_nodes:
            roa_dfz_prefix_not_found.add(prefix)
        else:
            dfz_subset_asns = origins_from_nodes(dfz_subset_nodes)
            for asn in roa_subset_asns:
                bucket = (
                    roa_dfz_origin_matches
                    if asn in dfz_subset_asns
                    else roa_dfz_origin_mismatches
                )
                bucket.setdefault(prefix, []).append(asn)

        # roa_dfz_skip.update(str(n.prefix) for n in roa_subset_nodes)  # type: ignore

    # ROA vs IRR:
    # roa_irr_step_1_found = 0
    # roa_irr_step_1_not_found = 0
    # roa_irr_step_2_found = 0
    # roa_irr_step_2_not_found = 0
    for roa_node in roa_origins.nodes():  # type: ignore
        prefix = str(roa_node.prefix)  # type: ignore
        step_1_not_found = False
        step_2_not_found = False

        # Step 1: match against covering IRR prefixes
        irr_covering_asns = find_covering_origins(
            irr_origins, prefix, check_max_length=False
        )
        if irr_covering_asns:
            # roa_irr_step_1_found += 1
            roa_asns: set[int] = set(roa_node.data["origins"])  # type: ignore
            for asn in roa_asns:
                bucket = (
                    roa_irr_origin_matches
                    if asn in irr_covering_asns
                    else roa_irr_origin_mismatches
                )
                bucket.setdefault(prefix, []).append(asn)
        else:
            # roa_irr_step_1_not_found += 1
            step_1_not_found = True

            # # Step 2: match against more specific IRR prefixes
            # irr_subset_nodes = covered_nodes(irr_origins, prefix, min_prefixlen=roa_node.prefixlen + 1)  # type: ignore
            # if irr_subset_nodes:
            #     roa_irr_step_2_found += 1
            #     irr_subset_asns = origins_from_nodes(irr_subset_nodes)
            #     for asn in roa_node.data["origins"]:  # type: ignore
            #         bucket = (
            #             roa_irr_origin_matches
            #             if asn in irr_subset_asns
            #             else roa_irr_origin_mismatches
            #         )
            #         bucket.setdefault(prefix, []).append(asn)  # type: ignore

            # else:
            #     roa_irr_step_2_not_found += 1
            #     step_2_not_found = True
            step_2_not_found = True

        if step_1_not_found and step_2_not_found:
            roa_irr_prefix_not_found.add(prefix)

    # logging.info(
    #     f"ROA vs IRR: Step 1 found {roa_irr_step_1_found:,}, not found {roa_irr_step_1_not_found:,}"
    # )
    # logging.info(
    #     f"ROA vs IRR: Step 2 found {roa_irr_step_2_found:,}, not found {roa_irr_step_2_not_found:,}"
    # )

    assert_no_overlap(roa_dfz_origin_matches, roa_dfz_origin_mismatches)
    assert_no_overlap(roa_irr_origin_matches, roa_irr_origin_mismatches)

    dfz_irr_origin_matches_v4, dfz_irr_origin_matches_v6 = split_v4_v6_counts(
        dfz_irr_origin_matches
    )
    dfz_irr_origin_mismatches_v4, dfz_irr_origin_mismatches_v6 = (
        split_v4_v6_counts(dfz_irr_origin_mismatches)
    )
    dfz_irr_prefix_not_found_v4, dfz_irr_prefix_not_found_v6 = (
        split_v4_v6_prefixes(dfz_irr_prefix_not_found)
    )
    dfz_roa_origin_matches_v4, dfz_roa_origin_matches_v6 = split_v4_v6_counts(
        dfz_roa_origin_matches
    )
    dfz_roa_origin_mismatches_v4, dfz_roa_origin_mismatches_v6 = (
        split_v4_v6_counts(dfz_roa_origin_mismatches)
    )
    dfz_roa_prefix_not_found_v4, dfz_roa_prefix_not_found_v6 = (
        split_v4_v6_prefixes(dfz_roa_prefix_not_found)
    )
    irr_dfz_origin_matches_v4, irr_dfz_origin_matches_v6 = split_v4_v6_counts(
        irr_dfz_origin_matches
    )
    irr_dfz_origin_mismatches_v4, irr_dfz_origin_mismatches_v6 = (
        split_v4_v6_counts(irr_dfz_origin_mismatches)
    )
    irr_dfz_prefix_not_found_v4, irr_dfz_prefix_not_found_v6 = (
        split_v4_v6_prefixes(irr_dfz_prefix_not_found)
    )
    irr_roa_origin_matches_v4, irr_roa_origin_matches_v6 = split_v4_v6_counts(
        irr_roa_origin_matches
    )
    irr_roa_origin_mismatches_v4, irr_roa_origin_mismatches_v6 = (
        split_v4_v6_counts(irr_roa_origin_mismatches)
    )
    irr_roa_prefix_not_found_v4, irr_roa_prefix_not_found_v6 = (
        split_v4_v6_prefixes(irr_roa_prefix_not_found)
    )
    roa_dfz_origin_matches_v4, roa_dfz_origin_matches_v6 = split_v4_v6_counts(
        roa_dfz_origin_matches
    )
    roa_dfz_origin_mismatches_v4, roa_dfz_origin_mismatches_v6 = (
        split_v4_v6_counts(roa_dfz_origin_mismatches)
    )
    roa_dfz_prefix_not_found_v4, roa_dfz_prefix_not_found_v6 = (
        split_v4_v6_prefixes(roa_dfz_prefix_not_found)
    )
    roa_irr_origin_matches_v4, roa_irr_origin_matches_v6 = split_v4_v6_counts(
        roa_irr_origin_matches
    )
    roa_irr_origin_mismatches_v4, roa_irr_origin_mismatches_v6 = (
        split_v4_v6_counts(roa_irr_origin_mismatches)
    )
    roa_irr_prefix_not_found_v4, roa_irr_prefix_not_found_v6 = (
        split_v4_v6_prefixes(roa_irr_prefix_not_found)
    )

    write_json(
        {
            "dfz_irr_origin_matches": dfz_irr_origin_matches,
            "dfz_irr_origin_mismatches": dfz_irr_origin_mismatches,
            "dfz_irr_prefix_not_found": sorted(dfz_irr_prefix_not_found),
            "dfz_roa_origin_matches": dfz_roa_origin_matches,
            "dfz_roa_origin_mismatches": dfz_roa_origin_mismatches,
            "dfz_roa_prefix_not_found": sorted(dfz_roa_prefix_not_found),
            "irr_dfz_origin_matches": irr_dfz_origin_matches,
            "irr_dfz_origin_mismatches": irr_dfz_origin_mismatches,
            "irr_dfz_prefix_not_found": sorted(irr_dfz_prefix_not_found),
            "irr_roa_origin_matches": irr_roa_origin_matches,
            "irr_roa_origin_mismatches": irr_roa_origin_mismatches,
            "irr_roa_prefix_not_found": sorted(irr_roa_prefix_not_found),
            "roa_dfz_origin_matches": roa_dfz_origin_matches,
            "roa_dfz_origin_mismatches": roa_dfz_origin_mismatches,
            "roa_dfz_prefix_not_found": sorted(roa_dfz_prefix_not_found),
            "roa_irr_origin_matches": roa_irr_origin_matches,
            "roa_irr_origin_mismatches": roa_irr_origin_mismatches,
            "roa_irr_prefix_not_found": sorted(roa_irr_prefix_not_found),
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
