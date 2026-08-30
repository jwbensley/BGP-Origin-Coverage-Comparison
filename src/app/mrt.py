import bz2
import gzip
import ipaddress
import logging
import multiprocessing
import os
import struct
import tempfile

import mrtparse  # type: ignore
from radix import radix  # type: ignore

from .data import write_json


class MrtParser:
    @staticmethod
    def _open_mrt_file(filename: str):
        """
        Open an MRT file for reading, transparently decompressing it if it
        is gzip or bzip2 compressed (detected via magic bytes, not just
        the file extension).
        """
        with open(filename, "rb") as f:
            magic = f.read(4)

        if magic[:2] == b"\x1f\x8b":
            logging.debug(f"Detected gzip compression for {filename}")
            return gzip.open(filename, "rb")
        elif magic[:3] == b"BZh":
            logging.debug(f"Detected bzip2 compression for {filename}")
            return bz2.open(filename, "rb")
        else:
            return open(filename, "rb")

    @staticmethod
    def _split_mrt_file(filename: str, n_chunks: int) -> list[str]:
        """
        Split an MRT RIB file into `n_chunks` temporary files, splitting on
        record boundaries (never mid-record).

        The input file may be gzip or bzip2 compressed; it is transparently
        decompressed while reading. The output chunk files are always
        written uncompressed.

        The first entry (assumed to be the peer index table) is skipped, as
        it is not needed to parse the subsequent RIB entries.

        Returns:
            A list of paths to the temporary chunk files.
        """
        logging.info(f"Splitting {filename} into {n_chunks} chunks")

        # MRT common header: timestamp(4) + type(2) + subtype(2) + length(4)
        header_fmt = ">IHHI"
        header_size = struct.calcsize(header_fmt)

        record_bufs: list[bytes] = []

        with MrtParser._open_mrt_file(filename) as f:
            first = True
            while True:
                header = f.read(header_size)
                if len(header) < header_size:
                    break

                _, _, _, length = struct.unpack(header_fmt, header)
                body = f.read(length)
                if len(body) < length:
                    logging.error(f"Truncated MRT record in {filename}")
                    break

                if first:
                    # Skip the first entry (assumed to be the peer index table)
                    first = False
                    continue

                record_bufs.append(header + body)

        total_records = len(record_bufs)
        if total_records == 0:
            raise ValueError(f"No records found in MRT file {filename}")

        n_chunks = max(1, min(n_chunks, total_records))
        chunk_size = -(-total_records // n_chunks)  # ceil division

        chunk_files: list[str] = []
        for i in range(0, total_records, chunk_size):
            chunk_bufs = record_bufs[i : i + chunk_size]
            fd, path = tempfile.mkstemp(prefix="mrt_chunk_", suffix=".mrt")
            with os.fdopen(fd, "wb") as f:
                for buf in chunk_bufs:
                    f.write(buf)
            chunk_files.append(path)
            logging.debug(
                f"Wrote {len(chunk_bufs)} records to chunk file {path}"
            )

        logging.info(
            f"Split {total_records:,} records into {len(chunk_files)} chunk files"
        )
        return chunk_files

    @staticmethod
    def _parse_mrt_chunk(
        filename: str, prefix_lengths: tuple[int, int, int, int]
    ) -> dict[str, set[int]]:
        """
        Parse a single MRT chunk file (containing only RIB entries, no peer
        index table) and return a dict mapping prefix -> set of origin ASNs.
        """
        logging.info(f"Parsing MRT chunk file {filename}")

        origins_by_prefix: dict[str, set[int]] = {}
        mrt_entries = mrtparse.Reader(filename)
        parsed_entries = 0

        try:
            for mrt_e in mrt_entries:
                parsed_entries += 1
                prefix, origins = MrtParser._parse_mrt_entry(
                    mrt_e, prefix_lengths
                )
                if prefix is None or origins is None:
                    continue
                origins_by_prefix.setdefault(str(prefix), set()).update(
                    origins
                )

        except KeyError:
            logging.error(
                f"Skipped unparsable entry in MRT chunk after {parsed_entries} "
                f"entries in file {filename}"
            )
        except EOFError:
            logging.error(
                f"Reached unexpected EOF after {parsed_entries} entries "
                f"in MRT chunk file {filename}"
            )

        logging.info(
            f"Parsed {parsed_entries:,} entries from chunk {filename}"
        )
        return origins_by_prefix

    @staticmethod
    def _parse_mrt_entry(
        mrt_entry: mrtparse.Reader,
        prefix_lengths: tuple[int, int, int, int],
    ) -> tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network | None, set[int] | None
    ]:
        """
        Extract the prefix and it's origin ASNs from an MRT entry.
        For invalid entries (e.g. an iBGP route) return (None, None).
        """

        prefix = f"{mrt_entry.data['prefix']}/{mrt_entry.data['length']}"  # type: ignore

        if prefix == "0.0.0.0/0" or prefix == "::/0":
            logging.debug(f"Skipping default route: {prefix}")
            logging.debug(f"{mrt_entry.data}")  # type: ignore
            return None, None

        try:
            ip_net = ipaddress.ip_network(prefix)
            if isinstance(ip_net, ipaddress.IPv4Network):
                if (
                    ip_net.prefixlen < prefix_lengths[0]
                    or ip_net.prefixlen > prefix_lengths[1]
                ):
                    logging.debug(
                        f"Skipping MRT IPv4 prefix with length < {prefix_lengths[0]} "
                        f"or > {prefix_lengths[1]}: {prefix}"
                    )
                    logging.debug(f"{mrt_entry.data}")  # type: ignore
                    return None, None
            else:
                if (
                    ip_net.prefixlen < prefix_lengths[2]
                    or ip_net.prefixlen > prefix_lengths[3]
                ):
                    logging.debug(
                        f"Skipping MRT IPv6 prefix with length < {prefix_lengths[2]} "
                        f"or > {prefix_lengths[3]}: {prefix}"
                    )
                    logging.debug(f"{mrt_entry.data}")  # type: ignore
                    return None, None
        except ValueError as e:
            logging.error(f"Unable to parse as prefix: {mrt_entry.data}")  # type: ignore
            raise e

        origins: set[int] = set()
        for rib_entry in mrt_entry.data["rib_entries"]:  # type: ignore
            """
            Extract the AS-path from the RIB entry. If there is none,
                it's an iBGP route, which we skip.
            """

            as_path: list[str] = []

            try:
                for path_atr in rib_entry["path_attributes"]:
                    if path_atr["type"] == {2: "AS_PATH"}:
                        # length == 0 means iBGP route
                        if path_atr["length"] != 0:
                            as_path = path_atr["value"][0]["value"]
                        break
            except IndexError as e:
                logging.error(
                    f"Couldn't get AS-path for prefix {prefix} from RIB entry "
                    f"{rib_entry}"
                )
                raise e

            if not as_path:
                logging.warning(f"Skipping iBGP route: {mrt_entry.data}")  # type: ignore
                return None, None

            """
            Extract the next-hop from the RIB entry. If there is none,
            it's an iBGP route, which we skip.
            """
            _nh = ""
            if mrt_entry.data["subtype"] == {2: "RIB_IPV4_UNICAST"}:  # type: ignore
                try:
                    _nh = [
                        path_atr["value"]
                        for path_atr in rib_entry["path_attributes"]
                        if path_atr["type"] == {3: "NEXT_HOP"}
                    ][0]
                except IndexError as e:
                    logging.error(
                        f"Couldn't get next-hop for prefix {prefix} from RIB entry "
                        f"{rib_entry}"
                    )
                    raise e
            elif mrt_entry.data["subtype"] == {4: "RIB_IPV6_UNICAST"}:
                try:
                    _nhs: list[str] = [
                        path_atr["value"]["next_hop"]
                        for path_atr in rib_entry["path_attributes"]
                        if path_atr["type"] == {14: "MP_REACH_NLRI"}
                    ][0]
                except IndexError as e:
                    logging.error(
                        f"Couldn't get next-hop for prefix {prefix} from RIB entry "
                        f"{rib_entry}"
                    )
                    raise e
                for next_hop in _nhs[:]:
                    if next_hop.lower().startswith("fe80:"):
                        _nhs.remove(next_hop)
                _nh = _nhs[0]
            else:
                raise ValueError(
                    f"Unknown subtype in RIB entry {mrt_entry.data}"  # type: ignore
                )

            if _nh == "0.0.0.0/0" or _nh == "::/0":
                logging.warning(f"Skipping iBGP route: {mrt_entry.data}")  # type: ignore
                return None, None

            if not _nh:
                raise ValueError(f"No next hop in RIB entry {mrt_entry.data}")  # type: ignore

            origin = int(as_path[-1].lower().lstrip("as"))
            origins.add(origin)

        return ipaddress.ip_network(prefix), origins

    @staticmethod
    def parse_mrt_rib(
        filename: str,
        json_output: str,
        prefix_lengths: tuple[int, int, int, int],
    ) -> radix.Radix:
        """
        Parse an MRT RIB file and return a radix.Radix tree.

        The file is split into per-record chunks and each chunk is parsed
        in a separate process to speed up parsing on multi-core systems.
        """
        logging.info(f"Parsing MRT RIB file {filename}")

        n_cpus = os.cpu_count()
        if n_cpus:
            n_cpus -= 1
        else:
            n_cpus = 1
        n_chunks = n_cpus

        chunk_files = MrtParser._split_mrt_file(filename, n_chunks)
        if not chunk_files:
            raise ValueError(f"No records found in MRT file {filename}")

        dfz_tree = radix.Radix()

        try:
            with multiprocessing.Pool(processes=len(chunk_files)) as pool:
                chunk_results = pool.starmap(
                    MrtParser._parse_mrt_chunk,
                    [
                        (chunk_file, prefix_lengths)
                        for chunk_file in chunk_files
                    ],
                )
        finally:
            for chunk_file in chunk_files:
                try:
                    os.unlink(chunk_file)
                    logging.debug(f"Deleted temporary chunk file {chunk_file}")
                except OSError:
                    pass

        logging.info(f"Merging {len(chunk_results)} chunk results")
        merged_origins: dict[str, set[int]] = {}
        for chunk_result in chunk_results:
            for prefix, origins in chunk_result.items():
                merged_origins.setdefault(prefix, set()).update(origins)

        for prefix, origins in merged_origins.items():
            node = dfz_tree.add(prefix)  # type: ignore
            node.data.setdefault("origins", set()).update(origins)  # type: ignore

        logging.info(f"Loaded {len(dfz_tree.nodes()):,} prefixes from MRT RIB")  # type: ignore

        write_json(
            {node.prefix: list(node.data["origins"]) for node in dfz_tree.nodes()},  # type: ignore
            json_output,
        )

        return dfz_tree
