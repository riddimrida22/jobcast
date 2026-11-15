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

# key -> translation. Missing keys fall back to the "en" entry, then the default passed at
# the call site. Keys with inline HTML/apostrophes live here (English too) to avoid fragile
# escaping in templates; simpler strings can still pass an English default inline.
TRANSLATIONS = {
    "en": {
        "intro.skip": "Skip &rsaquo;",
        "intro.next": "Next &rsaquo;",
        "intro.go": "See where my job lands &rsaquo;",
        "intro.say": "Hi, I'm Jobo. Two minutes, and you'll see what's really coming.",
        "intro.1.ey": "Before we score your job",
        "intro.1.h": 'AI isn\'t just a <span class="hot">chatbot</span> anymore',
        "intro.1.p": "You've probably typed questions into one. That's the surface. Today's AI also reads documents, writes code, analyzes images, and makes decisions &mdash; and <b>robots are starting to give it hands</b>, in warehouses, kitchens, and on job sites.",
        "intro.2.ey": "What changed",
        "intro.2.h": 'And it\'s getting better, <span class="hot">fast</span>',
        "intro.2.p": "A few years ago, AI could barely finish a sentence. Now it passes professional exams, writes working software, and does in seconds what took people hours. <b>Each year it takes on more of what used to need a person.</b>",
        "intro.3.ey": "We've been here before",
        "intro.3.h": 'Horses &rarr; <span class="hot">cars</span>',
        "intro.3.p": "In 1900, cities ran on horses &mdash; <b>more than 100,000 in New York alone</b>, plus the stable hands, farriers, and carriage makers who served them. Within about 20 years, cars replaced nearly all of it. Those jobs <b>went extinct</b> &mdash; but new ones appeared, and the people who saw it coming moved first.",
        "intro.4.ey": "Your turn",
        "intro.4.h": 'AI and robots are the <span class="hot">new cars</span>',
        "intro.4.chip1": "Translators &middot; going",
        "intro.4.chip2": "Data entry &middot; going",
        "intro.4.chip3": "Electricians &middot; safer",
        "intro.4.chip4": "Nurses &middot; safer",
        "intro.4.p": "This time it's hitting <b>knowledge work and physical work</b> &mdash; faster than the horse-to-car shift. Some jobs will go extinct. Most will change. The real question isn't just <b>if</b> &mdash; it's <b>when</b>, and what to do about it.",
        "intro.msg1": "HELLO",
        "intro.msg2": "FASTER",
        "intro.msg3": "SORRY",
        "intro.msg4": "GO!",
        # Result page: reveal, near-extinction, share, referral
        "rv.badge.safe": "Good news",
        "rv.badge.storm": "Act early",
        "rv.badge.mixed": "Mixed",
        "rv.msg.safe": "Most of your work still needs a person. AI reshapes this role more than it replaces it.",
        "rv.msg.storm": "A big share of this role is exposed to AI and robots, and its timeline runs shorter than most. No need to panic, but the people who move early keep the most options. Start with your fastest safe move.",
        "rv.msg.mixed": "Parts of this role are exposed, parts are safe. Where you focus next is what matters.",
        "rv.cta.breakdown": "See my breakdown",
        "rv.cta.now": "See what to do now ›",
        "rv.cta.full": "See the full breakdown",
        "rv.extinct.lab": "Near extinction",
        "rv.extinct.sorry": "SORRY",
        "share.btn": "Share my result",
        "share.reveal": "Share my score and challenge a friend",
        "share.copied": "Link copied to clipboard.",
        "ref.title": "Refer 5 friends who subscribe, get 50% off",
        "ref.desc": "Get your personal link. When 5 people you refer subscribe to Monitor, we email you a one-time 50% off code.",
        "ref.go": "Get my link",
        "ref.copy": "Copy",
        "ref.of": "of",
        "ref.subscribed": "referred friends have subscribed.",
        "ref.rewarded": "Reward earned - check your email for your 50% off code.",
        "ref.err": "Please enter a valid email.",
    },
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
        # Intro explainer (Jobo)
        "intro.skip": "Omitir &rsaquo;",
        "intro.next": "Siguiente &rsaquo;",
        "intro.go": "Ver dónde queda mi trabajo &rsaquo;",
        "intro.say": "Hola, soy Jobo. Dos minutos y verás lo que de verdad se viene.",
        "intro.1.ey": "Antes de calcular tu puntuación",
        "intro.1.h": 'La IA ya no es solo un <span class="hot">chatbot</span>',
        "intro.1.p": "Seguramente le has escrito preguntas. Eso es solo la superficie. La IA de hoy también lee documentos, escribe código, analiza imágenes y toma decisiones, y <b>los robots empiezan a darle manos</b>, en almacenes, cocinas y obras.",
        "intro.2.ey": "Qué cambió",
        "intro.2.h": 'Y mejora <span class="hot">rápido</span>',
        "intro.2.p": "Hace unos años, la IA apenas terminaba una frase. Ahora aprueba exámenes profesionales, escribe software que funciona y hace en segundos lo que a una persona le tomaba horas. <b>Cada año asume más de lo que antes necesitaba a alguien.</b>",
        "intro.3.ey": "Ya hemos vivido esto",
        "intro.3.h": 'Caballos &rarr; <span class="hot">autos</span>',
        "intro.3.p": "En 1900, las ciudades funcionaban con caballos: <b>más de 100,000 solo en Nueva York</b>, además de los mozos de cuadra, herradores y fabricantes de carruajes que los atendían. En unos 20 años, los autos reemplazaron casi todo. Esos empleos <b>se extinguieron</b>, pero surgieron otros, y quienes lo vieron venir se movieron primero.",
        "intro.4.ey": "Te toca a ti",
        "intro.4.h": 'La IA y los robots son los <span class="hot">nuevos autos</span>',
        "intro.4.chip1": "Traductores &middot; se van",
        "intro.4.chip2": "Captura de datos &middot; se va",
        "intro.4.chip3": "Electricistas &middot; más seguros",
        "intro.4.chip4": "Enfermeros &middot; más seguros",
        "intro.4.p": "Esta vez afecta al <b>trabajo intelectual y al trabajo físico</b>, más rápido que el cambio de caballos a autos. Algunos empleos se extinguirán. La mayoría cambiará. La verdadera pregunta no es solo <b>si</b>, sino <b>cuándo</b>, y qué hacer al respecto.",
        "intro.msg1": "HOLA",
        "intro.msg2": "RÁPIDO",
        "intro.msg3": "PERDÓN",
        "intro.msg4": "¡YA!",
        # Result page: reveal, near-extinction, share, referral
        "rv.badge.safe": "Buenas noticias",
        "rv.badge.storm": "Actúa pronto",
        "rv.badge.mixed": "Mixto",
        "rv.msg.safe": "La mayor parte de tu trabajo todavía necesita a una persona. La IA transforma este rol más de lo que lo reemplaza.",
        "rv.msg.storm": "Una buena parte de este rol está expuesta a la IA y los robots, y su plazo es más corto que el de la mayoría. No te alarmes, pero quienes se mueven pronto conservan más opciones. Empieza por tu paso seguro más rápido.",
        "rv.msg.mixed": "Partes de este rol están expuestas, otras están a salvo. Lo que importa es en qué te enfoques ahora.",
        "rv.cta.breakdown": "Ver mi análisis",
        "rv.cta.now": "Ver qué hacer ahora ›",
        "rv.cta.full": "Ver el análisis completo",
        "rv.extinct.lab": "Casi extinto",
        "rv.extinct.sorry": "PERDÓN",
        "share.btn": "Comparte mi resultado",
        "share.reveal": "Comparte mi puntuación y reta a un amigo",
        "share.copied": "Enlace copiado al portapapeles.",
        "ref.title": "Refiere a 5 amigos que se suscriban y obtén 50% de descuento",
        "ref.desc": "Obtén tu enlace personal. Cuando 5 personas que refieras se suscriban a Monitor, te enviaremos por correo un código único de 50% de descuento.",
        "ref.go": "Obtener mi enlace",
        "ref.copy": "Copiar",
        "ref.of": "de",
        "ref.subscribed": "amigos referidos se han suscrito.",
        "ref.rewarded": "¡Recompensa ganada! Revisa tu correo para tu código de 50% de descuento.",
        "ref.err": "Ingresa un correo válido.",
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
    en = TRANSLATIONS.get("en", {})

    def t(key, default=""):
        val = table.get(key)
        if val is None:
            val = en.get(key, default)
        return Markup(val)

    return t
