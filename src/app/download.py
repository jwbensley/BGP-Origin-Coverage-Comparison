import ftplib
import logging
import os
import requests
from typing import Optional
from urllib.parse import urlparse


class Download:
    @staticmethod
    def get(filename: str, url: str, overwrite: bool) -> Optional[str]:
        """
        Download a file from the given url,and save it as the given filename.
        """

        if os.path.exists(filename) and not overwrite:
            logging.info(f"Not overwriting existing file {filename}")
            return None

        logging.info(f"Downloading {url} to {filename}")

        if url.startswith("http://") or url.startswith("https://"):
            got = Download._get_http(filename, url)
        elif url.startswith("ftp://"):
            got = Download._get_ftp(filename, url)
        else:
            logging.error(f"Unsupported URL schema: {url}")
            return None

        logging.info(f"Downloaded to {filename}")
        return got

    @staticmethod
    def _get_ftp(filename: str, url: str) -> Optional[str]:
        parsed = urlparse(url)

        if not parsed.hostname:
            logging.error(f"Invalid URL, hostname is missing: {url}")
            return None

        try:
            ftp = ftplib.FTP(parsed.hostname)
            ftp.login()
            with open(filename, "wb") as f:
                ftp.retrbinary(f"RETR {parsed.path}", f.write)
            ftp.quit()
            return url
        except ftplib.all_errors as e:
            logging.error(f"FTP error: {e}")
            return None

    @staticmethod
    def _get_http(filename: str, url: str) -> Optional[str]:
        try:
            """
            The default Accept-Encoding is gzip, which causes the server
            to respond with a Content-Length which is not the full file
            size. Replace this so we can later compare the file size:
            """
            headers = {
                "Accept-Encoding": "*",
                "User-Agent": "BGP Research - jwbensley@netldn.slack.com",
            }

            resp = requests.get(url, headers=headers, stream=True)
        except requests.exceptions.ConnectionError as e:
            logging.error(f"Couldn't connect to HTTP server: {e}")
            return None
        except requests.exceptions.MissingSchema as e:
            logging.error(f"Invalid URL, schema is missing: {e}")
            return None

        if resp.status_code != 200:
            if resp.status_code == 404:
                logging.error(f"Unable to download file, 404: {url}")
                return None
            logging.error(f"HTTP error: {resp.status_code}")
            logging.error(f"{resp.url}")
            logging.error(f"{resp.text}")
            logging.error(f"{resp.content.decode()}")
            return None

        local_size = 0
        file_len = int(resp.headers["Content-length"])

        if file_len == 0:
            logging.error(f"File length is zero!")
            logging.error(f"{resp.url}")
            logging.error(f"{resp.text}")
            logging.error(f"{resp.content.decode()}")
            return None

        # Don't download if the file size has not changed
        if local_size == file_len:
            logging.info(f"Not downloading, unchanged file size for {url}")
            return url

        rcvd = 0
        logging.info(
            f"{os.path.basename(url)}: File size is {file_len/1024/1024:.2f}MBs"
        )
        progress = 0.0

        with open(filename, "wb") as f:
            for chunk in resp.iter_content(chunk_size=4096):
                if resp.status_code != 200:
                    logging.error(f"HTTP error: {resp.status_code}")
                    logging.error(f"{resp.url}")
                    logging.error(f"{resp.text}")
                    logging.error(f"{resp.content.decode()}")
                    f.close()
                    os.unlink(filename)
                    return None

                rcvd += len(chunk)
                f.write(chunk)
                f.flush()

                if rcvd == file_len:
                    logging.info(
                        f"Downloaded {rcvd}/{file_len} "
                        f"({(rcvd/file_len)*100:.2f}%) "
                        f"{os.path.basename(filename)}"
                    )
                elif ((rcvd / file_len) * 100) // 10 > progress:
                    logging.info(
                        f"Downloaded {rcvd}/{file_len} "
                        f"({(rcvd/file_len)*100:.2f}%) "
                        f"{os.path.basename(filename)}"
                    )
                    progress = ((rcvd / file_len) * 100) // 10
        return url
