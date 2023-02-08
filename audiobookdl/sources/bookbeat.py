from .source import Source
from audiobookdl import AudiobookFile
from typing import Any
import uuid
from audiobookdl.exceptions import UserNotAuthorized, MissingBookAccess
import base64
import re


def get_device_id() -> str:
    return (
        str(uuid.uuid3(uuid.NAMESPACE_DNS, "audiobook-dl"))
        + " "
        + base64.b64encode(b"Personal Computer").decode()
    )


class BookBeatSource(Source):
    match = [
        r"https?://(www.)?bookbeat.+",
    ]
    names = ["BookBeat"]
    _authentication_methods = [
        "login",
    ]

    saved_books: dict
    book_info: dict

    def _login(self, username: str, password: str):
        headers = {
            "accept": "application/hal+json",
            "bb-client": "BookBeatApp",
            "bb-device": get_device_id(),
        }
        self._session.headers = headers

        j = {"username": username, "password": password}

        r = self._session.post("https://api.bookbeat.com/api/login", json=j)
        if not r.status_code == 200:
            raise UserNotAuthorized

        tokens = r.json()
        self._session.headers.update({"authorization": "Bearer " + tokens["token"]})

        r = self._session.get(
            "https://api.bookbeat.com/api/my/books/saved?offset=0&limit=100"
        )
        if not r.status_code == 200:
            raise MissingBookAccess
        self.saved_books = r.json()

    def get_title(self) -> str:
        return self.book_info["metadata"]["title"]

    def get_files(self) -> list[AudiobookFile]:
        r = self._session.get(
            "https://api.bookbeat.com/api/downloadinfo/" + str(self.book_info["bookid"])
        )
        if not r.status_code == 200:
            raise MissingBookAccess
        dl_info = r.json()

        license_url = ""

        if "_embedded" in dl_info:
            if "downloads" in dl_info["_embedded"]:
                for dl in dl_info["_embedded"]["downloads"]:
                    if dl["format"] == "audioBook":
                        license_url = dl["_links"]["license"]["href"]
                        break

        if license_url:
            r = self._session.get(license_url)
            if not r.status_code == 200:
                raise MissingBookAccess
            lic = r.json()
            self.book_info["license"] = lic
            if "_links" in lic:
                return [
                    AudiobookFile(
                        url=lic["_links"]["download"]["href"],
                        headers=self._session.headers,
                        ext="mp4",
                    )
                ]

            raise MissingBookAccess

    def get_metadata(self) -> dict[str, Any]:
        try:
            contributors = next(
                iter(
                    [
                        e["contributors"]
                        for e in self.book_info["metadata"]["editions"]
                        if e["format"] == "audioBook"
                    ]
                ),
                None,
            )
            if not contributors:
                return {}
            metadata = {
                "authors": [
                    f"{a['firstname']} {a['lastname']}"
                    for a in contributors
                    if "author" in a["role"]
                ],
                "narrators": [
                    f"{n['firstname']} {n['lastname']}"
                    for n in contributors
                    if "narrator" in n["role"]
                ],
            }
            return metadata
        except:
            return {}

    def get_chapters(self) -> list[tuple[int, str]] | None:
        chapter_number = 1
        chapters = []
        for track in self.book_info["license"]["tracks"]:
            chapters.append((track["start"], f"Chapter {chapter_number}"))
            chapter_number += 1

        return chapters

    def get_cover(self) -> bytes | None:
        return self.get(self.book_info["metadata"]["cover"])

    def before(self):
        book_id_re = r"(\d+)$"
        wanted_id_match = re.search(book_id_re, self.url)
        if not wanted_id_match:
            raise ValueError(f"Couldn't get bookid from url {self.url}")
        wanted_id = wanted_id_match.group(1)
        for book in self.saved_books["_embedded"]["savedBooks"]:
            if str(book["bookid"]) == wanted_id:
                self.book_info = book
                self.book_info["metadata"] = self._session.get(
                    self.book_info["_links"]["book"]["href"]
                ).json()
                return
        raise MissingBookAccess