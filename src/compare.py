#!/usr/bin/env -S uv run

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
import os

from app.allocated_resources import AllocatedResources
from app.data import (
    compare_origins,
    load_tree_from_json,
    print_results,
    write_json,
)
from app.download import Download
from app.irr_parser import IrrParser
from app.mrt import MrtParser
from app.roa import Roa
from app.settings import Settings


def __setup_logging(level: int) -> None:
    if level == logging.DEBUG:
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(levelname)s - %(filename)s:%(funcName)s():%(lineno)d - %(message)s",
        )
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )


def parse_args() -> None:
    parser = argparse.ArgumentParser(
        description="Compare the origin AS of prefixes in the DFZ against the IRR and RPKI data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--data-dir",
        "-D",
        type=str,
        default=Settings.get_data_dir(),
        help="Directory to store downloaded data",
    )
    parser.add_argument(
        "--nro-stats",
        "-n",
        type=str,
        default=Settings.get_nro_allocations().get_url(),
        help="URL of the NRO delegated stats file to download",
    )
    parser.add_argument(
        "--rib-url",
        "-r",
        type=str,
        default=Settings.get_rib_dump().get_url(),
        help="URL of the MRT RIB dump file to download",
    )
    parser.add_argument(
        "--rpki-url",
        "-R",
        type=str,
        default=Settings.get_rpki_export().get_url(),
        help="URL of the RPKI export file to download",
    )
    parser.add_argument(
        "--overwrite",
        "-w",
        action="store_true",
        default=Settings.get_overwrite_files(),
        help="Overwrite existing downloaded files",
    )
    parsing = parser.add_argument_group("Parsing Options")
    parsing.add_argument(
        "--load-input",
        "-i",
        action=(
            "store_true" if not Settings.get_load_input() else "store_false"
        ),
        default=Settings.get_load_input(),
        help="Toggle loading existing parsed DFZ/IRR/RPKI data instead of downloading and parsing the files",
    )
    parsing.add_argument(
        "--load-output",
        "-o",
        action=(
            "store_true" if not Settings.get_load_output() else "store_false"
        ),
        default=Settings.get_load_output(),
        help="Toggle loading existing comparison results instead of running the comparison",
    )

    args = parser.parse_args()

    Settings.set_data_dir(args.data_dir)
    Settings.set_nro_allocations(args.nro_stats)
    Settings.set_rib_dump(args.rib_url)
    Settings.set_rpki_export(args.rpki_url)
    if args.debug:
        Settings.set_log_level(logging.DEBUG)
    Settings.set_overwrite_files(args.overwrite)
    Settings.set_load_input(args.load_input)
    Settings.set_load_output(args.load_output)

    __setup_logging(Settings.get_log_level())

    os.makedirs(Settings.get_data_dir(), exist_ok=True)


def main() -> None:
    parse_args()

    if Settings.get_load_output():
        print_results(Settings.get_stats_file())
        return

    if Settings.get_load_input():
        AllocatedResources.load_allocated_resources(
            Settings.get_nro_asns(),
            Settings.get_nro_prefixes(),
        )
        dfz_origins = load_tree_from_json(Settings.get_dfz_origins())
        irr_origins = load_tree_from_json(Settings.get_irr_origins())
        roa_origins = load_tree_from_json(Settings.get_rpki_origins())

    else:
        # Download the NRO delegated stats file to get the list of allocated ASNs and prefixes
        Download.get(
            Settings.get_nro_allocations().get_filename(),
            Settings.get_nro_allocations().get_url(),
            overwrite=Settings.get_overwrite_files(),
        )

        # Download the route/route6 data from the various RIRs.
        # Download each file using a different thread to speed up the process.
        with ThreadPoolExecutor(
            max_workers=len(Settings.get_irr_files())
        ) as executor:
            futures = [
                executor.submit(
                    Download.get,
                    file.get_filename(),
                    file.get_url(),
                    overwrite=Settings.get_overwrite_files(),
                )
                for file in Settings.get_irr_files()
            ]
            for future in futures:
                future.result()

        # Download an MRT RIB dump file with a full table feed
        Download.get(
            Settings.get_rib_dump().get_filename(),
            Settings.get_rib_dump().get_url(),
            overwrite=Settings.get_overwrite_files(),
        )

        # Download ROA data from an RPKI JSON feed
        Download.get(
            Settings.get_rpki_export().get_filename(),
            Settings.get_rpki_export().get_url(),
            overwrite=Settings.get_overwrite_files(),
        )

        # Parse the downloaded files and extract the origin ASNs from each source per prefix.
        AllocatedResources.parse_allocated_resources(
            Settings.get_nro_allocations().get_filename(),
            Settings.get_nro_asns(),
            Settings.get_nro_prefixes(),
        )
        dfz_origins = MrtParser.parse_mrt_rib(
            Settings.get_rib_dump().get_filename(),
            Settings.get_dfz_origins(),
            Settings.get_prefix_lengths(),
        )
        irr_origins = IrrParser.parse_files(
            Settings.get_irr_files(),
            Settings.get_irr_origins(),
            Settings.get_prefix_lengths(),
        )
        roa_origins = Roa.parse_roa_origins(
            Settings.get_rpki_export().get_filename(),
            Settings.get_rpki_origins(),
            Settings.get_prefix_lengths(),
        )

    AllocatedResources.drop()

    compare_origins(
        dfz_origins,
        irr_origins,
        roa_origins,
        comparison_file=Settings.get_comparison_file(),
        stats_file=Settings.get_stats_file(),
    )

    print_results(Settings.get_stats_file())
    logging.info("Finished.")


if __name__ == "__main__":
    main()
