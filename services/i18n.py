"""Customer-facing texts in Azerbaijani, Russian and English, plus date/price formatting.

Texts are Telegram HTML. Anything dynamic (names, service names, addresses)
must be passed through ``html.escape`` before it goes into ``t()``.
Owner/admin messages are English only (see the README's "next steps").
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from html import escape

from services.models import DEFAULT_LANGUAGE, Knowledge

TEXTS: dict[str, dict[str, str]] = {
    # -- menu / general ---------------------------------------------------------------------------
    "welcome": {
        "en": "👋 Hi! I'm the assistant of <b>{shop}</b>.\nI can book you an appointment or answer questions "
              "about prices, opening hours and our address. Tap a button or just type your question.",
        "ru": "👋 Здравствуйте! Я ассистент <b>{shop}</b>.\nМогу записать вас на стрижку или ответить на вопросы "
              "о ценах, часах работы и адресе. Нажмите кнопку или просто напишите вопрос.",
        "az": "👋 Salam! Mən <b>{shop}</b> bərbərxanasının köməkçisiyəm.\nSizi növbəyə yaza və ya qiymətlər, "
              "iş saatları və ünvanımız barədə suallarınızı cavablandıra bilərəm. Düyməyə toxunun və ya "
              "sualınızı yazın.",
    },
    "menu_prompt": {
        "en": "What else can I do for you?",
        "ru": "Чем ещё могу помочь?",
        "az": "Başqa nə ilə kömək edə bilərəm?",
    },
    "help": {
        "en": "I can help with:\n• 📅 booking an appointment (/book)\n• 💈 prices and services\n"
              "• 🕒 opening hours\n• 📍 address and contacts\n• 🙋 connecting you with a staff member\n\n"
              "Write in English, Русский or Azərbaycanca and I'll answer in the same language.",
        "ru": "Я могу помочь:\n• 📅 записаться на приём (/book)\n• 💈 узнать цены и услуги\n"
              "• 🕒 узнать часы работы\n• 📍 узнать адрес и контакты\n• 🙋 связаться с сотрудником\n\n"
              "Пишите на русском, English или Azərbaycanca, я отвечу на том же языке.",
        "az": "Sizə kömək edə bilərəm:\n• 📅 növbəyə yazılmaq (/book)\n• 💈 qiymətlər və xidmətlər\n"
              "• 🕒 iş saatları\n• 📍 ünvan və əlaqə\n• 🙋 işçi ilə əlaqə saxlamaq\n\n"
              "Azərbaycanca, Русский və ya English yazın, eyni dildə cavab verəcəyəm.",
    },
    "ok": {"en": "OK 👌", "ru": "Хорошо 👌", "az": "Yaxşı 👌"},
    "greeting": {
        "en": "Hello! 😊 How can I help? I can tell you our prices, opening hours and address, "
              "or book you an appointment.",
        "ru": "Здравствуйте! 😊 Чем могу помочь? Подскажу цены, часы работы и адрес или запишу вас.",
        "az": "Salam! 😊 Necə kömək edə bilərəm? Qiymətləri, iş saatlarını və ünvanı deyə bilərəm, "
              "ya da sizi növbəyə yaza bilərəm.",
    },
    "thanks": {"en": "You're welcome! 😊", "ru": "Пожалуйста! 😊", "az": "Dəyməz! 😊"},
    "not_found": {
        "en": "Sorry, I don't have that information. I can connect you with a staff member.",
        "ru": "К сожалению, у меня нет этой информации. Могу связать вас с сотрудником.",
        "az": "Təəssüf ki, bu barədə məlumatım yoxdur. Sizi işçimizlə əlaqələndirə bilərəm.",
    },
    "refuse": {
        "en": "I can only help with {shop}: prices, opening hours, address and bookings.",
        "ru": "Я могу помочь только по вопросам {shop}: цены, часы работы, адрес и запись.",
        "az": "Mən yalnız {shop} ilə bağlı suallarda kömək edə bilərəm: qiymətlər, iş saatları, ünvan və növbə.",
    },
    "unknown_command": {
        "en": "I don't know that command. Try /start or /help.",
        "ru": "Не знаю такой команды. Попробуйте /start или /help.",
        "az": "Belə bir əmr tanımıram. /start və ya /help yazın.",
    },
    "whoami": {
        "en": "Your Telegram user ID: <code>{id}</code>",
        "ru": "Ваш Telegram ID: <code>{id}</code>",
        "az": "Telegram ID-niz: <code>{id}</code>",
    },
    # -- safety / errors --------------------------------------------------------------------------
    "rate_limited": {
        "en": "You're sending messages too fast. Please wait a moment and try again.",
        "ru": "Вы отправляете сообщения слишком часто. Подождите немного и попробуйте снова.",
        "az": "Çox tez-tez mesaj göndərirsiniz. Bir az gözləyin və yenidən cəhd edin.",
    },
    "too_long": {
        "en": "That message is too long. Please keep it under {limit} characters.",
        "ru": "Сообщение слишком длинное. Пожалуйста, уложитесь в {limit} символов.",
        "az": "Mesaj çox uzundur. Zəhmət olmasa, {limit} simvoldan qısa yazın.",
    },
    "text_only": {
        "en": "I can only read text messages. Please type your question.",
        "ru": "Я понимаю только текстовые сообщения. Напишите, пожалуйста, ваш вопрос.",
        "az": "Mən yalnız mətn mesajlarını başa düşürəm. Zəhmət olmasa, sualınızı yazın.",
    },
    "error_generic": {
        "en": "Sorry, something went wrong on our side. Please try again in a minute.",
        "ru": "Извините, у нас что-то пошло не так. Попробуйте ещё раз через минуту.",
        "az": "Bağışlayın, texniki xəta baş verdi. Bir dəqiqədən sonra yenidən cəhd edin.",
    },
    # -- buttons ----------------------------------------------------------------------------------
    "btn_book": {"en": "📅 Book", "ru": "📅 Записаться", "az": "📅 Növbəyə yazıl"},
    "btn_prices": {"en": "💈 Prices", "ru": "💈 Цены", "az": "💈 Qiymətlər"},
    "btn_hours": {"en": "🕒 Hours", "ru": "🕒 Часы работы", "az": "🕒 İş saatları"},
    "btn_address": {"en": "📍 Address", "ru": "📍 Адрес", "az": "📍 Ünvan"},
    "btn_human": {"en": "🙋 Talk to a human", "ru": "🙋 Связаться с сотрудником", "az": "🙋 İşçi ilə əlaqə"},
    "btn_menu": {"en": "🏠 Menu", "ru": "🏠 Меню", "az": "🏠 Menyu"},
    "btn_back": {"en": "⬅️ Back", "ru": "⬅️ Назад", "az": "⬅️ Geri"},
    "btn_cancel": {"en": "✖️ Cancel", "ru": "✖️ Отмена", "az": "✖️ Ləğv et"},
    "btn_confirm": {"en": "✅ Confirm", "ru": "✅ Подтвердить", "az": "✅ Təsdiqlə"},
    "btn_share_contact": {
        "en": "📱 Share my phone number",
        "ru": "📱 Отправить мой номер",
        "az": "📱 Nömrəmi göndər",
    },
    # -- booking flow -----------------------------------------------------------------------------
    "choose_service": {
        "en": "Which service would you like?",
        "ru": "Выберите услугу:",
        "az": "Xidməti seçin:",
    },
    "choose_date": {
        "en": "<b>{service}</b>\nPick a day:",
        "ru": "<b>{service}</b>\nВыберите день:",
        "az": "<b>{service}</b>\nGünü seçin:",
    },
    "choose_time": {
        "en": "<b>{service}</b> · {date}\nPick a time:",
        "ru": "<b>{service}</b> · {date}\nВыберите время:",
        "az": "<b>{service}</b> · {date}\nSaatı seçin:",
    },
    "no_days": {
        "en": "Sorry, there are no free slots in the next {days}. Please call us: {phone}",
        "ru": "К сожалению, в течение {days} нет свободного времени. Позвоните нам: {phone}",
        "az": "Təəssüf ki, yaxın {days} boş vaxt yoxdur. Bizə zəng edin: {phone}",
    },
    "no_slots_day": {
        "en": "That day is fully booked now. Please pick another day.",
        "ru": "На этот день свободного времени уже нет. Выберите другой день.",
        "az": "Seçdiyiniz gün üçün boş vaxt qalmayıb. Başqa gün seçin.",
    },
    "slot_taken": {
        "en": "Sorry, someone just took that time. Please pick another one.",
        "ru": "Извините, это время только что заняли. Выберите другое.",
        "az": "Bağışlayın, bu vaxtı indicə başqası tutdu. Başqa vaxt seçin.",
    },
    "slot_unavailable": {
        "en": "Sorry, that time is no longer available. Please pick another one.",
        "ru": "Извините, это время больше недоступно. Выберите другое.",
        "az": "Bağışlayın, bu vaxta artıq yazılmaq mümkün deyil. Başqa vaxt seçin.",
    },
    "ask_name": {
        "en": "🕒 {date}, {time}\n\nWhat name should I put the booking under?",
        "ru": "🕒 {date}, {time}\n\nНа какое имя записать?",
        "az": "🕒 {date}, {time}\n\nNövbəni hansı ada yazım?",
    },
    "invalid_name": {
        "en": "Please send just your name (2–50 letters).",
        "ru": "Пожалуйста, отправьте только имя (2–50 букв).",
        "az": "Zəhmət olmasa, yalnız adınızı göndərin (2–50 hərf).",
    },
    "ask_phone": {
        "en": "Thanks, {name}! Now your phone number: tap the button below or type it "
              "(for example +994 50 123 45 67).",
        "ru": "Спасибо, {name}! Теперь номер телефона: нажмите кнопку ниже или введите его "
              "(например, +994 50 123 45 67).",
        "az": "Təşəkkürlər, {name}! İndi telefon nömrənizi göndərin: aşağıdakı düyməyə toxunun və ya yazın "
              "(məsələn, +994 50 123 45 67).",
    },
    "invalid_phone": {
        "en": "That doesn't look like a phone number. Example: +994 50 123 45 67",
        "ru": "Это не похоже на номер телефона. Пример: +994 50 123 45 67",
        "az": "Bu telefon nömrəsinə oxşamır. Nümunə: +994 50 123 45 67",
    },
    "phone_saved": {
        "en": "📞 Phone saved: {phone}",
        "ru": "📞 Номер сохранён: {phone}",
        "az": "📞 Nömrə qeyd edildi: {phone}",
    },
    "summary": {
        "en": "Please check your booking:\n\n💈 {service} ({price})\n📅 {date}\n🕒 {start}–{end}\n"
              "👤 {name}\n📞 {phone}",
        "ru": "Проверьте, пожалуйста, запись:\n\n💈 {service} ({price})\n📅 {date}\n🕒 {start}–{end}\n"
              "👤 {name}\n📞 {phone}",
        "az": "Zəhmət olmasa, məlumatları yoxlayın:\n\n💈 {service} ({price})\n📅 {date}\n🕒 {start}–{end}\n"
              "👤 {name}\n📞 {phone}",
    },
    "booked": {
        "en": "✅ <b>You're booked!</b>\n\n💈 {service}\n📅 {date}, {start}–{end}\n👤 {name}\n"
              "🆔 Booking ID: <code>{id}</code>\n📍 {address}\n\nSee you soon! Need to change something? "
              "Just write here.",
        "ru": "✅ <b>Вы записаны!</b>\n\n💈 {service}\n📅 {date}, {start}–{end}\n👤 {name}\n"
              "🆔 Номер записи: <code>{id}</code>\n📍 {address}\n\nДо встречи! Если нужно что-то изменить, "
              "просто напишите сюда.",
        "az": "✅ <b>Növbəniz təsdiqləndi!</b>\n\n💈 {service}\n📅 {date}, {start}–{end}\n👤 {name}\n"
              "🆔 Növbə nömrəsi: <code>{id}</code>\n📍 {address}\n\nGörüşənədək! Nəyisə dəyişmək lazımdırsa, "
              "sadəcə bura yazın.",
    },
    "flow_cancelled": {
        "en": "OK, booking cancelled.",
        "ru": "Хорошо, запись отменена.",
        "az": "Yaxşı, növbə ləğv edildi.",
    },
    "session_expired": {
        "en": "This booking has expired. Let's start again.",
        "ru": "Время на оформление записи истекло. Давайте начнём заново.",
        "az": "Növbə sorğusunun vaxtı bitdi. Gəlin yenidən başlayaq.",
    },
    "cancelled_by_shop": {
        "en": "❗ Your booking <code>{id}</code> on {date} at {time} was cancelled by the barbershop. "
              "Sorry for the inconvenience. Write here to pick a new time.",
        "ru": "❗ Барбершоп отменил вашу запись <code>{id}</code> на {date}, {time}. "
              "Извините за неудобства. Напишите сюда, чтобы выбрать другое время.",
        "az": "❗ {date}, saat {time} üçün <code>{id}</code> nömrəli növbəniz bərbərxana tərəfindən ləğv edildi. "
              "Narahatlığa görə üzr istəyirik. Yeni vaxt seçmək üçün bura yazın.",
    },
    # -- human handoff ----------------------------------------------------------------------------
    "handoff_done": {
        "en": "🙋 I've let the team know. Someone will reply to you here soon.",
        "ru": "🙋 Ваш запрос передан сотруднику. Вам скоро ответят здесь.",
        "az": "🙋 Sorğunuz işçimizə ötürüldü. Tezliklə sizə burada cavab veriləcək.",
    },
    "handoff_unavailable": {
        "en": "Please call us at {phone} and a staff member will help you.",
        "ru": "Позвоните нам по номеру {phone}, сотрудник вам поможет.",
        "az": "Bizə {phone} nömrəsi ilə zəng edin, işçimiz sizə kömək edəcək.",
    },
    # -- FAQ renderers ----------------------------------------------------------------------------
    "prices_title": {"en": "💈 <b>Services and prices</b>", "ru": "💈 <b>Услуги и цены</b>",
                     "az": "💈 <b>Xidmətlər və qiymətlər</b>"},
    "hours_title": {"en": "🕒 <b>Opening hours</b>", "ru": "🕒 <b>Часы работы</b>", "az": "🕒 <b>İş saatları</b>"},
    "address_title": {"en": "📍 <b>Address</b>", "ru": "📍 <b>Адрес</b>", "az": "📍 <b>Ünvan</b>"},
    "minutes": {"en": "min", "ru": "мин", "az": "dəq"},
    "closed": {"en": "closed", "ru": "выходной", "az": "istirahət günü"},
    "today": {"en": "Today", "ru": "Сегодня", "az": "Bu gün"},
    "tomorrow": {"en": "Tomorrow", "ru": "Завтра", "az": "Sabah"},
}

_WEEKDAYS_SHORT = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "az": ["B.e.", "Ç.a.", "Çər.", "C.a.", "Cüm.", "Şən.", "Baz."],
}
_WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
    "az": ["bazar ertəsi", "çərşənbə axşamı", "çərşənbə", "cümə axşamı", "cümə", "şənbə", "bazar"],
}
_MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
           "октября", "ноября", "декабря"],
    "az": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avqust", "sentyabr", "oktyabr",
           "noyabr", "dekabr"],
}
_MONTHS_SHORT = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "ru": ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"],
    "az": ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avq", "sen", "okt", "noy", "dek"],
}


def t(key: str, lang: str, **values: object) -> str:
    variants = TEXTS[key]
    text = variants.get(lang) or variants[DEFAULT_LANGUAGE]
    return text.format(**values) if values else text


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def fmt_time(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def fmt_date(day: date, lang: str) -> str:
    """Long date: "Wednesday, 18 November" / "среда, 18 ноября" / "18 noyabr, çərşənbə"."""
    lang = lang if lang in _WEEKDAYS else DEFAULT_LANGUAGE
    weekday, month = _WEEKDAYS[lang][day.weekday()], _MONTHS[lang][day.month - 1]
    if lang == "az":
        return f"{day.day} {month}, {weekday}"
    return f"{weekday}, {day.day} {month}"


def fmt_day_button(day: date, today: date, lang: str) -> str:
    lang = lang if lang in _WEEKDAYS else DEFAULT_LANGUAGE
    delta = (day - today).days
    if delta == 0:
        return t("today", lang)
    if delta == 1:
        return t("tomorrow", lang)
    return f"{_WEEKDAYS_SHORT[lang][day.weekday()]} {day.day} {_MONTHS_SHORT[lang][day.month - 1]}"


def fmt_days(n: int, lang: str) -> str:
    """ "14 days" / "14 дней" (genitive, after "в течение") / "14 gündə"."""
    if lang == "ru":
        return f"{n} {'дня' if n % 10 == 1 and n % 100 != 11 else 'дней'}"
    if lang == "az":
        return f"{n} gündə"
    return f"{n} {'day' if n == 1 else 'days'}"


def fmt_price(price: Decimal, currency: str) -> str:
    amount = f"{price:.0f}" if price == price.to_integral_value() else f"{price:.2f}"
    return f"{amount} {currency}"


def render_prices(k: Knowledge, lang: str) -> str:
    lines = [t("prices_title", lang)]
    for s in k.services:
        lines.append(
            f"• {escape(s.name(lang))}: {escape(fmt_price(s.price, k.currency))} "
            f"({s.duration_min} {t('minutes', lang)})"
        )
    return "\n".join(lines)


def render_hours(k: Knowledge, lang: str) -> str:
    """Groups consecutive days with the same hours: "Monday–Friday: 10:00–20:00"."""
    lang = lang if lang in _WEEKDAYS else DEFAULT_LANGUAGE
    names = _WEEKDAYS[lang]
    groups: list[tuple[int, int, str]] = []
    for day in range(7):
        window = k.window(day)
        value = f"{window.opens:%H:%M}–{window.closes:%H:%M}" if window else t("closed", lang)
        if groups and groups[-1][2] == value and groups[-1][1] == day - 1:
            groups[-1] = (groups[-1][0], day, value)
        else:
            groups.append((day, day, value))
    lines = [t("hours_title", lang)]
    for first, last, value in groups:
        label = names[first] if first == last else f"{names[first]}–{names[last]}"
        lines.append(f"{_cap(label)}: {value}")
    return "\n".join(lines)


def render_address(k: Knowledge, lang: str) -> str:
    lines = [t("address_title", lang), escape(k.address), f"📞 {escape(k.phone)}"]
    if k.maps_url:
        lines.append(f"🗺 {escape(k.maps_url)}")
    return "\n".join(lines)
