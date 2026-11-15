"""Lightweight internationalization.

Locale is resolved per request from ?lang= -> jb_lang cookie -> Accept-Language -> English.
translator(lang) returns a `t(key, english_default)` used in templates. English stays in the
templates as the default, and translations overlay it, so untranslated keys fall back to
English automatically and the app is translated incrementally, surface by surface.

Translations are developer-authored (trusted), so t() returns Markup (not escaped) to allow
the small amount of inline HTML in a few strings.
"""

from markupsafe import Markup

# Display names shown in the language switcher.
LANGS = {"en": "English", "es": "Español", "fr": "Français", "ht": "Kreyòl"}
DEFAULT = "en"

# key -> translation. Missing keys fall back to the English default passed at the call site.
TRANSLATIONS = {
    "es": {
        # Header / nav
        "nav.home": "Inicio",
        "nav.info": "Más información",
        "nav.how": "Cómo funciona",
        # Home gate
        "gate.q": '¿La <span class="hot">IA</span> reemplazará tu trabajo?',
        "gate.sub": "Escribe tu trabajo y recibe tu puntuación al instante: de 0 a 100, con datos reales. O elige cómo empezar.",
        "lp.ph": "Escribe tu trabajo, p. ej. electricista, enfermero, contador",
        "lp.or": "o",
        "emp.ey": "Trabajas ahora",
        "emp.h": "Soy empleado",
        "emp.sub": "Mira qué tan expuesto está tu propio trabajo, o haz primero un recorrido rápido de cómo funciona.",
        "stu.ey": "Aún decides",
        "stu.h": "Soy estudiante",
        "stu.sub": "Encuentra carreras que pagan bien y son difíciles de automatizar, clasificadas con datos reales.",
    },
    # French and Haitian Creole are stubs for now; keys fall back to English until filled in.
    "fr": {
        "nav.home": "Accueil",
        "nav.info": "Plus d'informations",
        "nav.how": "Comment ça marche",
    },
    "ht": {
        "nav.home": "Akèy",
        "nav.info": "Plis enfòmasyon",
        "nav.how": "Kijan li mache",
    },
}


def resolve_locale(arg_lang=None, cookie_lang=None, accept_language=""):
    """Pick the locale from an explicit ?lang=, then the cookie, then Accept-Language."""
    for cand in (arg_lang, cookie_lang):
        if cand in LANGS:
            return cand
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LANGS:
            return code
    return DEFAULT


def translator(lang):
    table = TRANSLATIONS.get(lang, {})

    def t(key, default=""):
        return Markup(table.get(key, default))

    return t
