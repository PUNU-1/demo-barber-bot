"""FAQ data: parsing and validation, hot reload, caching, rendering."""

import copy
import json
import os

import pytest

from config import PROJECT_ROOT
from services import i18n
from services.errors import KnowledgeError, KnowledgeUnavailable
from services.faq import CachedKnowledge, JsonKnowledge, StaticKnowledge, parse_knowledge
from tests.conftest import SHOP_DATA


def test_shipped_demo_data_is_valid():
    k = parse_knowledge(json.loads((PROJECT_ROOT / "data" / "faq.json").read_text(encoding="utf-8")))
    assert k.shop_name == "Demo Barber"
    assert [s.id for s in k.services] == ["haircut", "beard", "combo", "kids"]
    assert k.window(6) is None  # Sunday closed
    assert all(s.name("az") and s.name("ru") and s.name("en") for s in k.services)


@pytest.mark.parametrize(
    ("text", "is_payment_question"),
    [
        ("Do you accept cards?", True),
        ("Can I pay by card?", True),
        ("Можно оплатить картой?", True),
        ("Вы принимаете карты?", True),
        ("Kartla ödəmək olar?", True),
        ("Do you sell gift cards?", False),  # must not be answered with the payment FAQ
        ("Есть подарочные карты?", False),
    ],
)
def test_demo_payment_faq_is_not_fooled_by_gift_cards(text, is_payment_question):
    from services.intents import Topic, classify

    k = parse_knowledge(json.loads((PROJECT_ROOT / "data" / "faq.json").read_text(encoding="utf-8")))
    match = classify(text, k)
    matched_payment = match.topic is Topic.FAQ and "card" in match.faq.question.lower()
    assert matched_payment is is_payment_question


def broken(**changes):
    data = copy.deepcopy(SHOP_DATA)
    for path, value in changes.items():
        section, index, key = path.split("__")
        data[section][int(index)][key] = value
    return data


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (broken(hours__0__day="Funday"), "unknown day"),
        (broken(hours__0__open="25:00"), "invalid time"),
        (broken(hours__0__open="20:00", hours__0__close="10:00"), "must be before close"),
        (broken(hours__0__close=""), "fill both"),
        (broken(services__1__id="haircut"), "duplicate id"),
        (broken(services__0__id="Has Spaces"), "id must be"),
        (broken(services__0__duration_min="half an hour"), "duration_min"),
        (broken(services__0__price="free"), "price must be a number"),
    ],
)
def test_invalid_data_gives_a_clear_error(data, message):
    with pytest.raises(KnowledgeError, match=message):
        parse_knowledge(data)


def test_missing_shop_name_is_an_error():
    data = copy.deepcopy(SHOP_DATA)
    data["info"]["shop_name"] = ""
    with pytest.raises(KnowledgeError, match="shop_name"):
        parse_knowledge(data)


def test_sheet_style_values_are_accepted():
    data = copy.deepcopy(SHOP_DATA)
    data["hours"][0].update(open="10:00:00", close="20:00:00")  # Sheets may return seconds
    data["services"][0].update(price="12,50", duration_min=30.0)
    data["faq"][0]["keywords"] = ["card*", "cash"]
    k = parse_knowledge(data)
    assert str(k.services[0].price) == "12.50"
    assert i18n.fmt_price(k.services[0].price, "AZN") == "12.50 AZN"


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))  # make the change visible


async def test_json_knowledge_reloads_and_survives_bad_edits(tmp_path):
    path = tmp_path / "faq.json"
    _write(path, SHOP_DATA)
    source = JsonKnowledge(path)
    assert (await source.get()).shop_name == "Test Barber"

    edited = copy.deepcopy(SHOP_DATA)
    edited["info"]["shop_name"] = "Renamed Barber"
    _write(path, edited)
    assert (await source.get()).shop_name == "Renamed Barber"

    path.write_text("{ not json", encoding="utf-8")
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 2_000_000_000))
    assert (await source.get()).shop_name == "Renamed Barber"  # keeps the last good version


async def test_json_knowledge_accepts_a_byte_order_mark(tmp_path):
    path = tmp_path / "faq.json"
    path.write_text(json.dumps(SHOP_DATA, ensure_ascii=False), encoding="utf-8-sig")  # as Notepad may save it
    assert (await JsonKnowledge(path).get()).shop_name == "Test Barber"


async def test_json_knowledge_without_a_good_file_raises(tmp_path):
    with pytest.raises(KnowledgeUnavailable):
        await JsonKnowledge(tmp_path / "missing.json").get()


class FlakySource:
    def __init__(self, knowledge):
        self.knowledge = knowledge
        self.fail = False
        self.calls = 0

    async def get(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("Google is down")
        return self.knowledge


async def test_cache_serves_stale_data_when_the_source_fails(knowledge):
    now = [0.0]
    source = FlakySource(knowledge)
    cache = CachedKnowledge(source, ttl_seconds=60, clock=lambda: now[0])
    assert await cache.get() is knowledge
    assert await cache.get() is knowledge and source.calls == 1  # cached

    now[0] = 61
    source.fail = True
    assert await cache.get() is knowledge  # stale but available
    assert source.calls == 2


async def test_cache_raises_when_nothing_was_ever_loaded(knowledge):
    source = FlakySource(knowledge)
    source.fail = True
    with pytest.raises(KnowledgeUnavailable):
        await CachedKnowledge(source, ttl_seconds=60).get()


async def test_static_knowledge(knowledge):
    assert await StaticKnowledge(knowledge).get() is knowledge


def test_hours_are_grouped_per_language(knowledge):
    assert i18n.render_hours(knowledge, "en").splitlines()[1:] == [
        "Monday–Friday: 10:00–20:00",
        "Saturday: 10:00–18:00",
        "Sunday: closed",
    ]
    assert "Понедельник–пятница: 10:00–20:00" in i18n.render_hours(knowledge, "ru")
    assert "Bazar: istirahət günü" in i18n.render_hours(knowledge, "az")


def test_prices_are_rendered_with_escaping(knowledge):
    text = i18n.render_prices(knowledge, "en")
    assert "Men&#x27;s haircut: 15 AZN (30 min)" in text


@pytest.mark.parametrize(
    ("n", "lang", "expected"),
    [(14, "en", "14 days"), (1, "en", "1 day"), (14, "ru", "14 дней"), (21, "ru", "21 дня"), (11, "ru", "11 дней"),
     (3, "ru", "3 дней"), (14, "az", "14 gündə")],
)
def test_day_counts_are_pluralised(n, lang, expected):
    assert i18n.fmt_days(n, lang) == expected
