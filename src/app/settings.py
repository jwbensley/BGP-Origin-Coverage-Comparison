import datetime
import logging
import multiprocessing
import os
from .web_file import WebFile
from .irr_file import IrrFile, IrrParsers


class Defaults:
    COMPARISON_FILE = "comparison.json"
    DFZ_ORIGINS = "dfz_origins.json"
    IRR_ORIGINS = "irr_origins.json"
    NRO_ALLOCATIONS = "nro-delegated-stats"
    NRO_ASNS = "nro-allocated-asns.json"
    NRO_PREFIXES = "nro-allocated-prefixes.json"
    RIB_DUMP = "rib_dump.gz"
    RPKI_EXPORT = "rpki.json"
    RPKI_ORIGINS = "rpki_origins.json"
    STATS_FILE = "stats.json"


class Settings:
    data_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data")
    )
    comparison_file = os.path.join(data_dir, Defaults.COMPARISON_FILE)
    dfz_origins = os.path.join(data_dir, Defaults.DFZ_ORIGINS)
    irr_files = [
        IrrFile(
            os.path.join(data_dir, "afrinic.db.gz"),
            IrrParsers.STANDARD,
            "https://ftp.afrinic.net/dbase/afrinic.db.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "apnic.db.route.gz"),
            IrrParsers.STANDARD,
            "https://ftp.apnic.net/apnic/whois/apnic.db.route.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "apnic.db.route6.gz"),
            IrrParsers.STANDARD,
            "https://ftp.apnic.net/apnic/whois/apnic.db.route6.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "arin.db.gz"),
            IrrParsers.STANDARD,
            "https://ftp.arin.net/pub/rr/arin.db.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "lacnic.db.gz"),
            IrrParsers.STANDARD,
            "https://irr.lacnic.net/lacnic.db.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "radb.db.gz"),
            IrrParsers.STANDARD,
            "ftp://ftp.radb.net/radb/dbase/radb.db.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "ripe.db.route.gz"),
            IrrParsers.STANDARD,
            "https://ftp.ripe.net/ripe/dbase/split/ripe.db.route.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "ripe.db.route6.gz"),
            IrrParsers.STANDARD,
            "https://ftp.ripe.net/ripe/dbase/split/ripe.db.route6.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "tc.db.gz"),
            IrrParsers.STANDARD,
            "https://ftp.bgp.net.br/tc.db.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "jpirr.db.gz"),
            IrrParsers.STANDARD,
            "https://ftp.nic.ad.jp/jpirr/jpirr.db.gz",
        ),
        IrrFile(
            os.path.join(data_dir, "nicbr-asn-blk-latest.txt"),
            IrrParsers.NICBR,
            "https://ftp.registro.br/pub/numeracao/origin/nicbr-asn-blk-latest.txt",
        ),
    ]
    irr_origins = os.path.join(data_dir, Defaults.IRR_ORIGINS)
    nro_asns = os.path.join(data_dir, Defaults.NRO_ASNS)
    nro_prefixes = os.path.join(data_dir, Defaults.NRO_PREFIXES)
    load_input = False
    load_output = False
    log_level = logging.INFO
    nro_allocations = WebFile(
        "https://ftp.ripe.net/pub/stats/ripencc/nro-stats/latest/nro-delegated-stats",
        os.path.join(data_dir, Defaults.NRO_ALLOCATIONS),
    )
    overwrite_files = False
    processes = multiprocessing.cpu_count() - 1
    plot_dir = os.path.join(os.path.dirname(__file__), "..", "..", "plots")
    yyyymmdd = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime(
        "%Y%m%d"
    )
    rib_dump = WebFile(
        f"https://data.ris.ripe.net/rrc25/{yyyymmdd[:4]}.{yyyymmdd[4:6]}/bview.{yyyymmdd}.0000.gz",
        os.path.join(data_dir, Defaults.RIB_DUMP),
    )
    rpki_export = WebFile(
        "https://rpki.cloudflare.com/rpki.json",
        os.path.join(data_dir, Defaults.RPKI_EXPORT),
    )
    rpki_origins = os.path.join(data_dir, Defaults.RPKI_ORIGINS)
    stats_file = os.path.join(data_dir, Defaults.STATS_FILE)
    v4_max_length = 24
    v4_min_length = 8
    v6_max_length = 48
    v6_min_length = 8

    @staticmethod
    def get_data_dir() -> str:
        return Settings.data_dir

    @staticmethod
    def get_dfz_origins() -> str:
        return Settings.dfz_origins

    @staticmethod
    def get_irr_files() -> list[IrrFile]:
        return Settings.irr_files

    @staticmethod
    def get_irr_origins() -> str:
        return Settings.irr_origins

    @staticmethod
    def get_load_input() -> bool:
        return Settings.load_input

    @staticmethod
    def get_load_output() -> bool:
        return Settings.load_output

    @staticmethod
    def get_log_level() -> int:
        return Settings.log_level

    @staticmethod
    def get_nro_allocations() -> WebFile:
        return Settings.nro_allocations

    @staticmethod
    def get_nro_asns() -> str:
        return Settings.nro_asns

    @staticmethod
    def get_nro_prefixes() -> str:
        return Settings.nro_prefixes

    @staticmethod
    def get_plot_dir() -> str:
        return Settings.plot_dir

    @staticmethod
    def get_processes() -> int:
        return Settings.processes

    @staticmethod
    def get_overwrite_files() -> bool:
        return Settings.overwrite_files

    @staticmethod
    def get_rib_dump() -> WebFile:
        return Settings.rib_dump

    @staticmethod
    def get_comparison_file() -> str:
        return Settings.comparison_file

    @staticmethod
    def get_rpki_export() -> WebFile:
        return Settings.rpki_export

    @staticmethod
    def get_rpki_origins() -> str:
        return Settings.rpki_origins

    @staticmethod
    def get_stats_file() -> str:
        return Settings.stats_file

    @staticmethod
    def get_prefix_lengths() -> tuple[int, int, int, int]:
        return (
            Settings.v4_min_length,
            Settings.v4_max_length,
            Settings.v6_min_length,
            Settings.v6_max_length,
        )

    @staticmethod
    def set_data_dir(data_dir: str) -> None:
        Settings.data_dir = data_dir
        Settings.dfz_origins = os.path.join(data_dir, Defaults.DFZ_ORIGINS)
        Settings.irr_origins = os.path.join(data_dir, Defaults.IRR_ORIGINS)
        Settings.nro_asns = os.path.join(data_dir, Defaults.NRO_ASNS)
        Settings.nro_prefixes = os.path.join(data_dir, Defaults.NRO_PREFIXES)
        Settings.comparison_file = os.path.join(
            data_dir, Defaults.COMPARISON_FILE
        )
        Settings.nro_allocations.set_filename(
            os.path.join(data_dir, Defaults.NRO_ALLOCATIONS)
        )
        Settings.rib_dump.set_filename(
            os.path.join(data_dir, Defaults.RIB_DUMP)
        )
        Settings.rpki_export.set_filename(
            os.path.join(data_dir, Defaults.RPKI_EXPORT)
        )
        Settings.rpki_origins = os.path.join(data_dir, Defaults.RPKI_ORIGINS)
        for irr_file in Settings.get_irr_files():
            irr_file.set_filename(
                os.path.join(data_dir, os.path.basename(irr_file.get_url()))
            )
        Settings.stats_file = os.path.join(data_dir, Defaults.STATS_FILE)

    @staticmethod
    def set_load_input(load_input: bool) -> None:
        Settings.load_input = load_input

    @staticmethod
    def set_load_output(load_output: bool) -> None:
        Settings.load_output = load_output

    @staticmethod
    def set_log_level(log_level: int) -> None:
        Settings.log_level = log_level

    @staticmethod
    def set_nro_allocations(url: str) -> None:
        Settings.nro_allocations.set_url(url)

    @staticmethod
    def set_overwrite_files(overwrite_files: bool) -> None:
        Settings.overwrite_files = overwrite_files

    @staticmethod
    def set_processes(processes: int) -> None:
        Settings.processes = processes

    @staticmethod
    def set_rib_dump(url: str) -> None:
        Settings.rib_dump.set_url(url)

    @staticmethod
    def set_rpki_export(url: str) -> None:
        Settings.rpki_export.set_url(url)
