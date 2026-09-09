import ipaddress
import logging
import math
from radix import radix  # type: ignore
from .data import load_tree_from_json, write_json, load_json


class AllocatedResources:
    """
    Class to check if a resource (ASN or prefix) is allocated.
    """

    assigned_asns: set[int]
    allocated_tree: radix.Radix

    @staticmethod
    def load_allocated_resources(nro_asns: str, nro_prefixes: str) -> None:
        """
        Load the allocated resources from the JSON files.
        """

        AllocatedResources.assigned_asns = set(load_json(nro_asns))
        AllocatedResources.allocated_tree = load_tree_from_json(nro_prefixes)

    @staticmethod
    def parse_allocated_resources(
        filename: str, nro_asns: str, nro_prefixes: str
    ) -> tuple[set[int], radix.Radix]:

        logging.info(f"Parsing NRO allocations file {filename}")

        AllocatedResources.assigned_asns = set()
        AllocatedResources.allocated_tree = radix.Radix()

        for line in open(filename).readlines():
            values = line.split("|")

            # Org
            if values[0] in ["2", "nro", "iana"]:
                continue

            # Country code
            if values[1] in ["*", "nro"]:
                continue

            # Resource type
            if values[2] not in ["asn", "ipv4", "ipv6"]:
                continue

            # Status
            if values[6] != "assigned":
                continue

            match values[2]:
                case "asn":
                    base_asn = int(values[3])
                    asn_range = int(values[4])

                    for asn in range(base_asn, base_asn + asn_range):
                        if asn in AllocatedResources.assigned_asns:
                            raise ValueError(
                                f"ASN found more than once: {asn}"
                            )
                        AllocatedResources.assigned_asns.add(asn)

                case "ipv4" | "ipv6":
                    raw_prefix = values[3]

                    if "." in raw_prefix:
                        """
                        The size of the IPv4 allocations are not always a power of 2.
                        E.g. prefix 91.123.57.0 with a subnet size of 1792 IPs.
                        We need to round down to the next power of 2 and then calculate the prefix length.
                        """

                        subnet_size = int(values[4])
                        next_power_of_2 = 2 ** math.floor(
                            math.log2(subnet_size)
                        )
                        prefix_length = 32 - int(math.log2(next_power_of_2))
                        prefix = ipaddress.ip_network(
                            f"{raw_prefix}/{prefix_length}", strict=False
                        )

                    else:
                        prefix = ipaddress.ip_network(
                            f"{raw_prefix}/{values[4]}", strict=False
                        )

                    # radix.Radix has no __contains__, so `in` would fall
                    # back to a full O(n) scan of the tree on every line;
                    # search_exact() uses the C-accelerated trie lookup.
                    if (
                        AllocatedResources.allocated_tree.search_exact(  # type: ignore
                            str(prefix)
                        )
                        is not None
                    ):
                        raise ValueError(
                            f"Allocated prefix found more than once: {prefix}\n"
                            f"(line: {line})"
                        )

                    AllocatedResources.allocated_tree.add(str(prefix))  # type: ignore

                case _:
                    raise ValueError(f"Unknown resource type: {values[2]}")

        logging.info(
            f"Loaded {len(AllocatedResources.assigned_asns)} allocated ASNs"
        )

        logging.info(
            f"Loaded {len(AllocatedResources.allocated_tree.nodes()):,} "  # type: ignore
            "allocated prefixes"
        )

        write_json(
            list(AllocatedResources.assigned_asns),
            nro_asns,
        )

        write_json(
            {node.prefix: None for node in AllocatedResources.allocated_tree.nodes()},  # type: ignore
            nro_prefixes,
        )

        return (
            AllocatedResources.assigned_asns,
            AllocatedResources.allocated_tree,
        )

    @staticmethod
    def is_allocated_asn(asn: int) -> bool:
        return asn in AllocatedResources.assigned_asns

    @staticmethod
    def is_allocated_prefix(prefix: str) -> bool:
        """
        Check if a prefix is part of the allocated space
        """
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            raise ValueError(f"Invalid prefix: {prefix}")

        return (
            AllocatedResources.allocated_tree.search_best(network) is not None  # type: ignore
        )

    @staticmethod
    def _rebuild_without(
        tree: radix.Radix, to_remove: set[str]
    ) -> radix.Radix:
        """
        Return a new tree with every node from `tree` copied over,
        except those whose prefix is in `to_remove`.

        Bulk `tree.delete()` calls have shown intermittent corruption at
        this dataset's scale (deleting one prefix occasionally also drops
        an unrelated, still-wanted prefix elsewhere in the tree, or
        `delete()` spuriously raises KeyError for a prefix that is still
        present). Rebuilding via `add()`, which has not shown this issue,
        sidesteps the buggy removal/compaction code path entirely.
        """
        new_tree = radix.Radix()
        for node in tree.nodes():  # type: ignore
            if node.prefix in to_remove:  # type: ignore
                continue
            new_node = new_tree.add(node.prefix)  # type: ignore
            new_node.data.update(node.data)  # type: ignore
        return new_tree

    @staticmethod
    def remove_unallocated_asns(tree: radix.Radix) -> radix.Radix:
        """
        Remove unallocated ASNs from the tree.

        Returns a new tree with the affected prefixes removed; `tree`
        itself is left untouched.
        """
        to_delete: set[str] = set()
        for node in tree.nodes():  # type: ignore
            for asn in list(node.data["origins"]):  # type: ignore
                if asn not in AllocatedResources.assigned_asns:
                    origins: set[int] = node.data["origins"]
                    origins.remove(asn)  # type: ignore
            if len(node.data["origins"]) == 0:  # type: ignore
                logging.debug(
                    f"Removing prefix with no origin ASNs: {node.prefix}"  # type: ignore
                )
                to_delete.add(node.prefix)  # type: ignore

        return AllocatedResources._rebuild_without(tree, to_delete)

    @staticmethod
    def remove_unallocated_prefixes(tree: radix.Radix) -> radix.Radix:
        """
        Remove unallocated prefixes from the tree.

        Returns a new tree with the affected prefixes removed; `tree`
        itself is left untouched.
        """
        to_delete: set[str] = set()
        for node in tree.nodes():  # type: ignore
            if (
                AllocatedResources.allocated_tree.search_best(node.prefix)  # type: ignore
                is None
            ):
                logging.debug(
                    f"Removed unallocated prefix: {node.prefix}"  # type: ignore
                )
                to_delete.add(node.prefix)  # type: ignore

        return AllocatedResources._rebuild_without(tree, to_delete)

    @staticmethod
    def drop() -> None:
        AllocatedResources.assigned_asns = set()
        AllocatedResources.allocated_tree = radix.Radix()
