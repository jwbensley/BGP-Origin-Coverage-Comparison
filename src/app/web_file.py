class WebFile:
    """
    A file that is downloaded from the web and saved locally
    """

    url: str
    filename: str

    def __init__(self, url: str, filename: str) -> None:
        self.url = url
        self.filename = filename

    def get_filename(self) -> str:
        return self.filename

    def get_url(self) -> str:
        return self.url

    def set_filename(self, filename: str) -> None:
        self.filename = filename

    def set_url(self, url: str) -> None:
        self.url = url
