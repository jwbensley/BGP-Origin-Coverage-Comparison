import ipaddress
import json
import logging

import radix  # type: ignore

from .data import write_json


class Roa:
    @staticmethod
    def parse_roa_origins(
        filename: str,
        json_output: str,
        prefix_lengths: tuple[int, int, int, int],
    ) -> radix.Radix:
        """
        Load the ROA data from a JSON file and return a radix.Radix tree.
        """
        logging.info(f"Loading ROA data from {filename}")

        with open(filename, "r") as f:
            data = json.load(f)
        roa_tree = radix.Radix()
        for roa in data.get("roas", []):
            prefix = (
                ipaddress.IPv4Network(roa["prefix"])
                if "." in roa["prefix"]
                else ipaddress.IPv6Network(roa["prefix"])
            )
            if isinstance(prefix, ipaddress.IPv4Network):
                if (
                    prefix.prefixlen < prefix_lengths[0]
                    or prefix.prefixlen > prefix_lengths[1]
                ):
                    logging.debug(
                        f"Skipping IPv4 ROA prefix with length < {prefix_lengths[0]} "
                        f"or > {prefix_lengths[1]}: {prefix}"
                    )
                    logging.debug(f"ROA data: {roa}")
                    continue
            else:
                if (
                    prefix.prefixlen < prefix_lengths[2]
                    or prefix.prefixlen > prefix_lengths[3]
                ):
                    logging.debug(
                        f"Skipping IPv6 ROA prefix with length < {prefix_lengths[2]} "
                        f"or > {prefix_lengths[3]}: {prefix}"
                    )
                    logging.debug(f"ROA data: {roa}")
                    continue
            max_length = int(roa["maxLength"])

            if max_length < prefix.prefixlen:
                logging.debug(
                    f"Skipping ROA prefix with max_length < prefix length: {prefix}, max_length: {max_length}"
                )
                logging.debug(f"ROA data: {roa}")
                continue

            asn = int(roa["asn"])
            node = roa_tree.add(str(prefix))  # type: ignore
            node.data["max_length"] = max_length  # type: ignore
            node.data.setdefault("origins", set()).add(asn)  # type: ignore

        logging.info(f"Loaded {len(roa_tree.nodes()):,} ROAs from {filename}")

        write_json(
            {
                node.prefix: {  # type: ignore
                    "origins": list(node.data["origins"]),  # type: ignore
                    "max_length": int(node.data["max_length"]),  # type: ignore
                }
                for node in roa_tree.nodes()  # type: ignore
            },
            json_output,
        )

        return roa_tree
