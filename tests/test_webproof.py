import asyncio

from warmpath.crust import CrustError
from warmpath.models import Person
from warmpath.webproof import mentions, web_cooccurrence


class FakeCrust:
    last_call_id = "c007"

    def __init__(self, results=None, fail=False):
        self.results, self.fail, self.queries = results or [], fail, []

    async def web_search(self, query, sources=None, site=None):
        self.queries.append(query)
        if self.fail:
            raise CrustError(429, "slow down", "/web/search/live")
        return {"results": self.results}


A, B = Person(name="Harsha Majety"), Person(name="Nandan Reddy")


def test_mentions_needs_full_names_close_together():
    assert mentions("Founded by Harsha Majety and Nandan Reddy", "Harsha Majety")
    assert mentions("Sriharsha S. Majety spoke", "Sriharsha Majety")
    assert not mentions("Harsha went home. Later, a Majety cousin...", "Harsha Majety")


def test_cofounders_page_counts_profile_sidebars_do_not():
    c = FakeCrust([
        {"title": "Swiggy founders Harsha Majety and Nandan Reddy", "url": "https://news.example/swiggy",
         "snippet": "The co-founders started in 2014"},
        {"title": "Harsha Majety | LinkedIn", "url": "https://www.linkedin.com/in/harsha",
         "snippet": "People also viewed: Nandan Reddy"},
        {"title": "Nandan Reddy", "url": "https://blog.example/x", "snippet": "Harsha is a friend"},
    ])
    f = asyncio.run(web_cooccurrence(c, A, B))
    assert f and f.value == 1 and f.contribution == 15.0 and "co-founded" in f.explanation
    assert f.evidence[0].url == "https://news.example/swiggy" and f.evidence[0].call_id == "c007"


def test_api_failure_or_single_word_name_gives_no_factor():
    assert asyncio.run(web_cooccurrence(FakeCrust(fail=True), A, B)) is None
    c = FakeCrust()
    assert asyncio.run(web_cooccurrence(c, Person(name="Harsha"), B)) is None and not c.queries
