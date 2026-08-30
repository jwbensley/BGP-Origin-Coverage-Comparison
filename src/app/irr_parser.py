import ipaddress
import logging
import os
from typing import Optional

import radix  # type: ignore

from .data import write_json
from .irr_file import IrrFile, IrrParsers


class IrrParser:
    @staticmethod
    def _max_length(
        prefix: ipaddress.IPv4Network | ipaddress.IPv6Network,
    ) -> int:
        """
        A radix tree node can only be keyed on a single, exact prefix/length -
        it can't represent a range of lengths directly. To still allow a
        registered route/route6 object (e.g. 192.168.0.0/16) to match more
        specific prefixes seen in the DFZ, we record the longest prefix
        length it is allowed to cover as metadata on the node: up to /24 for
        IPv4 and /48 for IPv6, which are the conventional deaggregation
        limits.
        """
        return 24 if isinstance(prefix, ipaddress.IPv4Network) else 48

    @staticmethod
    def _parse_nicbr_data(
        file_data: str,
        prefix_tree: radix.Radix,
        prefix_lengths: tuple[int, int, int, int],
    ) -> None:
        """
        NICBR data is in the following format per line:

        ASN|OrgName|OrgID|prefixes

        The prefixes field may be repeated many times separated by vertical bars, each prefix maybe be v4 or v6:

        AS23456|A Company|11.222.333/0001-01|10.0.0.0/8|2001:db8::/32|192.168.0.0/24
        """

        prefix: Optional[ipaddress.IPv4Network | ipaddress.IPv6Network] = None
        origin: Optional[int] = None

        index = 0
        for line in file_data.splitlines():
            index += 1
            line = line.lstrip()
            fields = line.split("|")

            if len(fields) < 4:
                logging.debug(f"Skipping NICBR line without prefixes: {line}")
                continue

            origin = int(fields[0].lower().lstrip("as"))

            for raw_prefix in fields[3:]:
                try:
                    prefix = (
                        ipaddress.IPv4Network(raw_prefix)
                        if "." in raw_prefix
                        else ipaddress.IPv6Network(raw_prefix)
                    )
                    if isinstance(prefix, ipaddress.IPv4Network):
                        if (
                            prefix.prefixlen < prefix_lengths[0]
                            or prefix.prefixlen > prefix_lengths[1]
                        ):
                            logging.debug(
                                f"Skipping NICBR IPv4 route object with length < {prefix_lengths[0]} "
                                f"or > {prefix_lengths[1]}: {prefix}"
                            )
                            logging.debug(f"Line {index}: {line}")
                            continue
                    else:
                        if (
                            prefix.prefixlen < prefix_lengths[2]
                            or prefix.prefixlen > prefix_lengths[3]
                        ):
                            logging.debug(
                                f"Skipping NICBR IPv6 route object with length < {prefix_lengths[2]} "
                                f"or > {prefix_lengths[3]}: {prefix}"
                            )
                            logging.debug(f"Line {index}: {line}")
                            continue
                except ValueError as e:
                    logging.error(f"Invalid NICBR prefix in line: {line}")
                    raise e

                logging.debug(f"Found NICBR route: {prefix}, origin: {origin}")
                node = prefix_tree.add(str(prefix))  # type: ignore
                node.data.setdefault("origins", set()).add(origin)  # type: ignore
                node.data["max_length"] = IrrParser._max_length(prefix)  # type: ignore

    @staticmethod
    def _parse_standard_data(
        file_data: str,
        prefix_tree: radix.Radix,
        prefix_lengths: tuple[int, int, int, int],
    ) -> None:
        """
        Parse the IRR data and extract the origin AS for each prefix.
        """
        prefix: Optional[ipaddress.IPv4Network | ipaddress.IPv6Network] = None
        origin: Optional[int] = None

        index = 0
        for line in file_data.splitlines():
            index += 1

            # JPNIC route objects are sometimes encoded as *xxte: instead of route:
            if line.startswith("route:") or line.startswith("*xxte:"):
                if prefix:
                    logging.error(
                        f"Found route without origin on line {index}: {prefix}"
                    )

                # Strip leading zeros from IP (this is for ARIN route objects)
                try:
                    raw_prefix = line.lstrip("route:").lstrip("*xxte:").strip()
                    raw_prefix = (
                        ".".join(
                            str(int(octet))
                            for octet in raw_prefix.split("/")[0].split(".")
                        )
                        + "/"
                        + raw_prefix.split("/")[1]
                    )
                    prefix = ipaddress.IPv4Network(raw_prefix)
                    if (
                        prefix.prefixlen < prefix_lengths[0]
                        or prefix.prefixlen > prefix_lengths[1]
                    ):
                        logging.debug(
                            f"Skipping IPv4 route object with length < {prefix_lengths[0]} "
                            f"or > {prefix_lengths[1]}: {prefix}"
                        )
                        logging.debug(f"Line {index}: {line}")
                        continue
                except ValueError as e:
                    logging.error(
                        f"Invalid IPv4 prefix on line {index}: {line}"
                    )
                    raise e
                logging.debug(f"Found route: {prefix}")

            # JPNIC route6 objects are sometimes encoded as *xxte6: instead of route6:
            elif line.startswith("route6:") or line.startswith("*xxte6:"):
                if prefix:
                    logging.error(f"Found route6 without origin: {prefix}")

                try:
                    prefix = ipaddress.IPv6Network(
                        line.lstrip("route6:").lstrip("*xxte6:").strip()
                    )
                    if (
                        prefix.prefixlen < prefix_lengths[2]
                        or prefix.prefixlen > prefix_lengths[3]
                    ):
                        logging.debug(
                            f"Skipping IPv6 route object with length < {prefix_lengths[2]} "
                            f"or > {prefix_lengths[3]}: {prefix}"
                        )
                        logging.debug(f"Line {index}: {line}")
                        continue
                except ValueError as e:
                    logging.error(
                        f"Invalid IPv6 prefix on line {index}: {line}"
                    )
                    raise e
                logging.debug(f"Found route6: {prefix}")

            elif line.startswith("origin:"):
                if origin:
                    logging.error(
                        f"Found origin without route/route6: {origin}"
                    )

                # Split() here to remove comments after the ASN
                try:
                    origin = int(
                        line.lstrip("origin:").split()[0].lower().lstrip("as")
                    )
                except Exception as e:
                    logging.error(
                        f"Unable to parse origin from line {index}: {line!r}"
                    )
                    raise e
                logging.debug(f"Found origin: {origin}")

            if prefix is not None and origin is not None:
                logging.debug(f"Prefix: {prefix}, Origin: {origin}")
                node = prefix_tree.add(str(prefix))  # type: ignore
                node.data.setdefault("origins", set()).add(origin)  # type: ignore
                node.data["max_length"] = IrrParser._max_length(prefix)  # type: ignore
                prefix = None
                origin = None

    @staticmethod
    def parse_files(
        irr_files: list[IrrFile],
        json_output: str,
        prefix_lengths: tuple[int, int, int, int],
    ) -> radix.Radix:
        """
        Parse the IRR data files and extract the origin AS for each prefix.

        Returns:
            A radix.Radix tree, keyed on prefix, where each node's `data`
            dict contains an "origins" set of ASNs seen for that prefix.
        """

        prefix_tree = radix.Radix()

        for irr_file in irr_files:
            fn = irr_file.get_filename()

            if not os.path.exists(fn):
                raise ValueError(f"File {fn} is missing")
            logging.info(f"Parsing {fn}")

            # Parse NICBR differently, it has a different format than the other IRR files
            match irr_file.get_parser():
                case IrrParsers.STANDARD:
                    IrrParser._parse_standard_data(
                        irr_file.get_contents(), prefix_tree, prefix_lengths
                    )
                case IrrParsers.NICBR:
                    IrrParser._parse_nicbr_data(
                        irr_file.get_contents(), prefix_tree, prefix_lengths
                    )
                case _:
                    raise ValueError(
                        f"Unknown parser type: {irr_file.get_parser()}"
                    )

        logging.info(
            f"Loaded {len(prefix_tree.nodes()):,} prefixes from IRR data"
        )

        write_json(
            {
                node.prefix: {  # type: ignore
                    "origins": list(node.data["origins"]),  # type: ignore
                    "max_length": int(node.data["max_length"]),  # type: ignore
                }
                for node in prefix_tree.nodes()  # type: ignore
            },
            json_output,
        )

        return prefix_tree
