import gzip
import os
from enum import Enum


class IrrParsers(Enum):
    STANDARD = "STANDARD"
    NICBR = "NICBR"


class IrrFile:
    filename: str
    parser: IrrParsers
    url: str

    def __init__(
        self,
        filename: str,
        parser: IrrParsers,
        url: str,
    ) -> None:
        self.filename = filename
        self.parser = parser
        self.url = url

    def get_filename(self) -> str:
        return self.filename

    def get_contents(self) -> str:
        fn = self.get_filename()
        if os.path.splitext(fn)[-1] == ".gz":
            contents = gzip.open(
                fn, "rt", encoding="utf-8", errors="replace"
            ).read()
        else:
            contents = open(
                fn, "rt", encoding="utf-8", errors="replace"
            ).read()
        return contents

    def get_parser(self) -> IrrParsers:
        return self.parser

    def get_url(self) -> str:
        return self.url

    def set_filename(self, filename: str) -> None:
        self.filename = filename
