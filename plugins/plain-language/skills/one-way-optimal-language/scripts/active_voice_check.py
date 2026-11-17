#!/usr/bin/env python3
"""active_voice_check.py - flag every clause that is not in the active voice.

Standard library only. If spaCy and an English model are installed, the script
also runs a dependency-parse pass and merges its hits (use --no-spacy to skip).
It loads en_core_web_sm by default. --model NAME loads another model. On
evals/active-voice/all.txt (9 November 2026), en_core_web_sm left 194 of 196
active sentences clean and en_core_web_trf left 195 of 196, but trf ran about
7 times slower on a 2-core CPU. Both caught 262 of 262 passives.

Usage:
    python3 active_voice_check.py FILE [FILE ...] [--no-spacy] [--model NAME] [--quiet] [--strict]

--strict counts MENTION hits as blocking. Use it on a file that holds only the
revised text, where italics and quotation marks mark emphasis, not examples.

Hit codes (each hit needs a human decision; nothing passes silently):
    PASSIVE      be + past participle (includes modal, perfect, progressive,
                 infinitive, contracted, negated, and inverted-question forms)
    GET-PASSIVE  get + past participle ("get hurt")
    PSEUDO       remain / stay / seem / look / feel / appear + participle that
                 names an action ("remain protected")
    CAUSATIVE    have / get + object + participle ("have your blood tested")
    REDUCED      participle after a noun with the actor implied
                 ("the form signed by the patient", "patients given this drug")
    REDUCED?     lower-confidence reduced relative ("any sample collected
                 after noon goes ...")
    CONCEALED    need / want / require + -ing ("needs changing")
    ELLIPTICAL   participle with the subject and auxiliary dropped ("if
                 swallowed", "as directed", "once opened", "Not recommended")
    STATE?       participle that probably describes a condition, not an action
                 ("you feel tired"); keep it only if the event test fails
    MANDATED     a hit inside <!-- av:verbatim --> ... <!-- /av:verbatim -->,
                 text that law or a regulator requires word for word
    MENTION      a hit inside *italics*, `code`, quotation marks, or
                 <!-- av:mention --> ... <!-- /av:mention --> (worked "before"
                 examples, cited titles): a mention of words, not a use; check
                 that it really is an example

Fenced code blocks (``` ... ```) are skipped: program code is not prose.

Exit status: 1 if any PASSIVE, GET-PASSIVE, PSEUDO, CAUSATIVE, REDUCED,
REDUCED?, CONCEALED, or ELLIPTICAL hit appears outside MANDATED and MENTION text; else 0.
"""
import re
import sys

# ---------------------------------------------------------------- word lists
BE = {"am", "is", "are", "was", "were", "be", "been", "being", "'s", "'re", "'m"}
GET = {"get", "gets", "got", "gotten", "getting"}
HAVE = {"have", "has", "had", "having", "'ve"}
PSEUDO_COPULAS = {"remain", "remains", "remained", "remaining", "stay", "stays",
                  "stayed", "staying", "seem", "seems", "seemed", "look", "looks",
                  "looked", "feel", "feels", "felt", "appear", "appears",
                  "appeared", "become", "becomes", "became", "becoming"}
NEED = {"need", "needs", "needed", "want", "wants", "wanted", "require",
        "requires", "required", "deserve", "deserves"}
ADVERBS = {"not", "n't", "also", "only", "then", "often", "usually", "always",
           "never", "already", "still", "first", "later", "now", "just", "all",
           "both", "each", "soon", "again", "ever", "even", "sometimes", "well",
           "too", "either", "yet", "once", "twice", "further", "thus", "therefore",
           "however", "instead", "rather", "almost", "nearly", "seldom", "no",
           "longer", "being", "been", "be", "otherwise", "last", "best", "better",
           "much", "far", "long", "newly", "since", "aloud", "together", "apart", "late", "early",
           "later", "earlier", "yesterday", "today", "online", "overnight"}
DEGREE = {"very", "so", "too", "quite", "more", "most", "less", "least",
          "extremely", "really", "fairly", "somewhat", "a", "bit", "little"}
DETERMINERS = {"the", "a", "an", "your", "my", "his", "her", "its", "our",
               "their", "this", "that", "these", "those", "any", "each",
               "every", "some", "all", "no", "one", "two", "both"}
PRONOUN_SUBJECTS = {"i", "you", "we", "he", "she", "it", "they", "who",
                    "which", "that", "there"}
PREPOSITIONS = {"in", "on", "at", "after", "before", "for", "from", "with",
                "to", "under", "during", "by", "into", "through", "since",
                "until", "within", "over", "without", "per", "as", "outside",
                "inside", "near", "around", "about", "out", "off", "up", "down",
                "away", "aside", "here", "there", "today", "yesterday", "last",
                "earlier", "below", "above", "between", "against"}
FINITE = {"is", "are", "was", "were", "will", "must", "may", "might", "can",
          "should", "could", "would", "shall", "do", "does", "did", "has",
          "have", "had", "go", "goes", "went", "stay", "stays", "remain",
          "remains", "need", "needs", "show", "shows", "help", "helps", "cause",
          "causes", "come", "comes", "look", "looks", "seem", "seems",
          "become", "becomes", "take", "takes", "give", "gives", "get", "gets",
          "make", "makes", "keep", "keeps", "lead", "leads", "contain",
          "contains", "include", "includes", "mean", "means", "appear",
          "appears", "require", "requires", "work", "works", "belong",
          "belongs", "move", "moves", "count", "counts", "expire", "expires",
          "incur", "incurs", "apply", "applies", "cost", "costs", "affect",
          "affects", "change", "changes", "happen", "happens", "occur",
          "occurs", "last", "lasts", "carry", "carries", "pay", "pays",
          "follow", "follows", "qualify", "qualifies", "return", "returns",
          "arrive", "arrives", "receive", "receives", "stay", "end", "ends",
          "start", "starts", "cause", "help", "lower", "lowers", "raise",
          "raises", "reduce", "reduces", "increase", "increases", "differ",
          "differs", "depend", "depends", "matter", "matters", "show"}
# -ed words that are not participles
NOT_PARTICIPLE = {"need", "bed", "red", "shed_noun", "seed", "weed", "deed",
                  "feed", "heed", "speed", "breed", "bleed", "greed", "creed",
                  "steed", "proceed", "exceed", "succeed", "shred", "sled",
                  "hundred", "kindred", "sacred", "naked", "wicked", "rugged",
                  "ragged", "crooked", "jagged", "wretched", "embed", "imbed",
                  "infrared", "seabed", "sickbed", "hotbed", "bloodshed",
                  "watershed", "indeed", "biomed", "unmet"}
# irregular participles (including forms that match the base or past tense)
IRREGULAR = set("""
cut put set read hit shut hurt spread cost let quit split bet burst cast rid shed
thrust upset broadcast forecast input output offset reset recast beset preset wed
bid slit overcome run rerun outrun
done undone redone overdone outdone given forgiven taken retaken mistaken
undertaken overtaken partaken shaken forsaken made remade seen foreseen overseen
written rewritten overwritten underwritten known shown grown outgrown thrown
overthrown blown flown drawn withdrawn overdrawn sown sewn mown hewn sworn torn
worn born borne found told retold held upheld withheld beheld kept left built
rebuilt brought bought caught taught thought sought fought sent spent lent bent
meant dealt felt knelt slept swept wept crept leapt led misled fed overfed bred
fled sped lit met paid prepaid repaid overpaid underpaid laid mislaid said sold
resold driven hidden broken chosen frozen spoken stolen woken forgotten gotten
begotten begun drunk sung rung sunk shrunk stung strung swung hung flung slung
wrung spun won struck stuck understood misunderstood withstood beaten bitten
eaten fallen forbidden ridden overridden risen striven proven swollen bound
ground wound lost shot heard overheard burnt learnt spelt spilt spoilt dreamt
smelt dug clung sat spat lain slain gone
""".split())
# participle forms that cannot be simple past tense (safe reduced-relative cue)
PARTICIPLE_ONLY = set("""
done undone redone given forgiven taken retaken mistaken undertaken overtaken
shaken forsaken seen foreseen overseen written rewritten overwritten underwritten
known shown grown thrown overthrown blown flown drawn withdrawn sown sewn mown
sworn torn worn born borne driven hidden broken chosen frozen spoken stolen woken
forgotten gotten begun drunk sung rung sunk shrunk beaten bitten eaten fallen
forbidden ridden overridden risen proven swollen lain slain gone
""".split())
STATIVE = set("""
tired worried scared frightened confused interested married divorced widowed
engaged located based swollen bloated irritated crowded concerned excited pleased
satisfied surprised disappointed embarrassed exhausted dehydrated constipated
depressed stressed impaired disabled related inflamed overwhelmed relaxed annoyed
bored puzzled amazed alarmed ashamed nauseated experienced skilled complicated
unexpected unwanted untreated unvaccinated unsigned unused
""".split())
COMPLEMENT_VERBS = {"keep", "keeps", "kept", "keeping", "leave", "leaves",
                    "leaving", "want", "wants", "wanted", "need", "needs",
                    "find", "finds", "make", "makes", "made", "see", "sees",
                    "hear", "hears", "like", "likes", "prefer", "prefers"}
INDEFINITES = {"anything", "something", "everything", "nothing", "whatever"}
WH = {"what", "where", "how", "why", "when", "who", "whom", "whose", "which", "often", "long", "much", "many"}
ELLIPSIS_LEADS = {"if", "when", "whenever", "once", "unless", "until", "as",
                  "while", "although", "though", "where", "wherever", "than",
                  "except", "until"}
HOMOGRAPHS = {"shot", "cut", "set", "run", "cast", "bet", "hit", "spread", "burst",
              "split", "output", "input", "offset", "reset", "wound", "ground",
              "bound", "felt", "left", "lit", "bid", "quit", "upset", "forecast",
              "broadcast", "rid", "dug", "found", "read", "shed", "won", "lead",
              "hurt", "cost", "let", "put", "hung", "sat", "spat", "met"}
SUBORDINATORS = {"after", "before", "until", "since", "when", "if", "because",
                 "while", "as", "that", "once", "unless", "although", "though",
                 "where", "whether", "and", "or", "but", "who", "which"}
ING_NOT_VERB = {"nothing", "something", "anything", "everything", "morning",
                "evening", "thing", "string", "ring", "king", "spring", "ceiling",
                "sibling", "during", "bedding", "clothing", "bring", "sing",
                "swing", "sling", "sting", "wing", "being", "feeling", "meeting",
                "building", "training", "funding", "housing", "parking",
                "screening", "counseling", "nursing", "hearing", "bleeding",
                "swelling", "warning", "booking", "setting", "following",
                "including", "regarding", "pending", "according"}

# ---------------------------------------------------------------- tokenizing
CONTRACTIONS = {"won't": ["will", "n't"], "can't": ["can", "n't"],
                "cannot": ["can", "not"], "shan't": ["shall", "n't"],
                "ain't": ["is", "n't"]}
TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*|\d+(?:[.,]\d+)*|\S")


def tokenize(text):
    """Return tokens as (word_lowercase, start, end, original)."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("*", " ").replace("`", " ")
    out = []
    for m in TOKEN_RE.finditer(text):
        w, s, e = m.group(0), m.start(), m.end()
        lw = w.lower()
        if lw in CONTRACTIONS:
            for piece in CONTRACTIONS[lw]:
                out.append((piece, s, e, w))
            continue
        m2 = re.match(r"^(.*?)(n't|'s|'re|'ve|'ll|'d|'m)$", lw)
        if m2 and m2.group(1):
            out.append((m2.group(1), s, e, w))
            out.append((m2.group(2), s, e, w))
        else:
            out.append((lw, s, e, w))
    return out


def is_participle(w):
    if w in IRREGULAR:
        return True
    return len(w) > 3 and w.endswith("ed") and w not in NOT_PARTICIPLE


def is_word(w):
    return w[:1].isalpha() or w.startswith("'")


# ---------------------------------------------------------------- rules
def classify_participle(tokens, j, default):
    """Return default, or STATE? if the participle looks adjectival."""
    w = tokens[j][0]
    prev = tokens[j - 1][0] if j else ""
    if w in STATIVE or prev in DEGREE:
        # an explicit by-agent signals an event even for stative words
        nxt = tokens[j + 1][0] if j + 1 < len(tokens) else ""
        return default if nxt == "by" and w not in {"located", "based"} else "STATE?"
    return default


def clause_end(words, k):
    """True if token k ends a clause (a period counts only before a capital or the end)."""
    w = words[k]
    if w in {",", ";", ":", "?", "!", "(", ")", "and", "but", "or"}:
        return True
    if w == ".":
        return k + 1 >= len(words) or not words[k + 1][:1].islower()
    return False


def skip_adverbs(words, j):
    while j < len(words) and (words[j] in ADVERBS or
                              (words[j].endswith("ly") and len(words[j]) > 3)):
        j += 1
    return j


def find_hits(tokens):
    hits = []  # (code, index of the participle or cue word)
    words = [t[0] for t in tokens]
    n = len(words)

    def add_coordinated(j, code_default):
        # "is labeled and stored", "feel sleepy and confused"
        k = j + 1
        if k < n and words[k] in {"and", "or"}:
            k = skip_adverbs(words, k + 1)
            if k < n and is_participle(words[k]):
                hits.append((classify_participle(tokens, k, code_default), k))

    for i, w in enumerate(words):
        # be-passive, get-passive, pseudo-passive (auxiliary, then adverbs)
        if w in BE or w in GET or w in PSEUDO_COPULAS:
            j = skip_adverbs(words, i + 1)
            # inverted question: Be + subject (up to 5 words) + participle
            q_start = i == 0 or words[i - 1] in {"?", ".", "!", ":", ";", '"'}
            if not q_start and i >= 1 and words[i - 1] in WH:
                q_start = i == 1 or words[i - 2] in {"?", ".", "!", ":", ";", '"'}
            if j < n and not is_participle(words[j]) and w in BE and q_start:
                k = j
                while k < n and k - j < 5 and is_word(words[k]) and \
                        not is_participle(words[k]) and words[k] not in {"who", "that", "which", "whom"}:
                    k += 1
                if k < n and is_participle(words[k]):
                    j = k
            default = ("GET-PASSIVE" if w in GET else
                       "PSEUDO" if w in PSEUDO_COPULAS else "PASSIVE")
            if j < n and is_participle(words[j]) and words[j] != "been":
                if w == "'s":
                    nxt = words[j + 1] if j + 1 < n else ""
                    if nxt in DETERMINERS or nxt in {"you", "him", "them", "me", "us", "it"}:
                        continue  # "she's taken her medicine" = has taken
                    if is_word(nxt) and nxt not in PREPOSITIONS and nxt not in ADVERBS \
                            and nxt != "by" and not nxt.endswith("ly") and nxt not in {"and", "or"}:
                        continue  # possessive: "the patient's known wishes"
                code = default if w in GET else classify_participle(tokens, j, default)
                hits.append((code, j))
                add_coordinated(j, default)
                continue
            # copula + adjective + and/or + participle ("is dry and cracked")
            if j < n and is_word(words[j]) and w not in GET:
                add_coordinated(j, default)
        # causative: have/get + determiner phrase (1-3 words) + participle
        if w in HAVE or w in GET or w in COMPLEMENT_VERBS:
            j = i + 1
            question = (i == 0 or words[i - 1] in {".", "!", "?", ":", ";", '"'}) and "?" in words[i:]
            if w in HAVE and question:
                continue  # "Has the nurse checked your pulse?" = perfect tense
            if j < n and words[j] in DETERMINERS:
                k = j + 1
                while k < n and k - j <= 3 and is_word(words[k]) and \
                        not is_participle(words[k]) and words[k] not in PREPOSITIONS:
                    k += 1
                if k < n and k > j + 1 and is_participle(words[k]) and \
                        words[k] not in STATIVE and \
                        (words[k] not in HOMOGRAPHS or (k + 1 < n and words[k + 1] == "by")):
                    hits.append(("CAUSATIVE", k))
                    continue
        # concealed passive: need + -ing
        if w in NEED and i + 1 < n:
            nx = words[i + 1]
            if nx.endswith("ing") and len(nx) > 4 and nx not in ING_NOT_VERB:
                hits.append(("CONCEALED", i + 1))

    # elliptical passives: "if swallowed", "when taken with food", "as directed",
    # "once opened", sentence-initial "Not recommended ..."
    starts = {0}
    for k, wk in enumerate(words):
        if wk in {".", "?", "!", ":", ";", "(", "\u2014", '"'} or (wk == "," and k + 1 < n):
            starts.add(k + 1)
    for i, w in enumerate(words):
        lead = w in ELLIPSIS_LEADS
        if not (lead or i in starts):
            continue
        j = skip_adverbs(words, i + 1 if lead else i)
        if j < n and is_participle(words[j]) and (lead or j > i or words[j] not in HOMOGRAPHS):
            if any(j == h for _, h in hits):
                continue
            if words[j] in HOMOGRAPHS and not lead and (j + 1 >= n or words[j + 1] != "by"):
                continue  # "Then read the leaflet", "no online cost for ..."
            nxt = words[j + 1] if j + 1 < n else ""
            if not lead and nxt in DETERMINERS | {"you", "your", "it", "them"}:
                continue  # imperative or main verb with an object
            if is_word(nxt) and nxt not in PREPOSITIONS and nxt not in ADVERBS \
                    and nxt != "by" and not nxt.endswith("ly") and nxt not in {"and", "or"}:
                continue  # attributive: "numbered steps", "qualified translators"
            hits.append((classify_participle(tokens, j, "ELLIPTICAL"), j))

    # reduced relatives: a participle after a noun, with no auxiliary
    covered = {j for _, j in hits}
    for j, w in enumerate(words):
        if j in covered or j < 1 or not is_participle(w):
            continue
        back = words[max(0, j - 3):j]
        if any(b in BE or b in HAVE or b in GET or b in PSEUDO_COPULAS for b in back):
            continue
        prev = words[j - 1]
        if prev in {"not", "n't"} and j >= 2 and words[j - 2] not in BE | HAVE | GET | \
                {"will", "must", "may", "might", "can", "should", "could", "would",
                 "shall", "do", "does", "did", "to"} and is_word(words[j - 2]):
            prev = words[j - 2]
        if not is_word(prev) or prev in PRONOUN_SUBJECTS or prev in DETERMINERS \
                or prev in DEGREE or prev in {"to", "and", "or", "not", "n't"} \
                or prev in PREPOSITIONS or prev.endswith("ly") or prev in SUBORDINATORS:
            continue
        if prev in {"will", "must", "may", "might", "can", "should", "could",
                    "would", "shall", "do", "does", "did"}:
            continue
        if j >= 2 and words[j - 2] in {"that", "which", "who", "whom"} and prev[:1].isalpha():
            continue  # "research that Claude conducted": active relative clause
        nxt = words[j + 1] if j + 1 < n else ""

        def later_finite():
            for k in range(j + 2, min(n, j + 14)):
                if clause_end(words, k):
                    return False
                if words[k] in FINITE:
                    return True
            return False

        def object_np():
            # the noun phrase before the participle follows a verb or preposition,
            # so it cannot be the subject of a past-tense verb
            d = j - 1
            while d >= 0 and j - d <= 4 and words[d] not in DETERMINERS:
                d -= 1
            return d >= 1 and words[d] in DETERMINERS and words[d] != "that" \
                and is_word(words[d - 1]) and words[d - 1] not in SUBORDINATORS \
                and words[d - 1] not in PREPOSITIONS  # "that" may be a relative pronoun
        if is_word(nxt) and nxt not in PREPOSITIONS and nxt not in ADVERBS and \
                nxt not in DETERMINERS and nxt not in {"by", "and", "or", "you", "me",
                                                       "him", "her", "them", "us", "it"} \
                and not nxt.endswith("ly"):
            continue  # attributive: "forbidden forms", "written information"
        if w in PARTICIPLE_ONLY or prev in INDEFINITES:
            hits.append(("REDUCED", j))
        elif w in STATIVE:
            continue
        elif nxt == "by":
            if object_np() or later_finite():
                hits.append(("REDUCED", j))
        elif nxt in PREPOSITIONS or nxt in ADVERBS or nxt.endswith("ly") or nxt in {"late", "early"}:
            # a noun homograph ("no processing cost for ...") needs a later finite verb
            if (object_np() and w not in HOMOGRAPHS) or later_finite():
                hits.append(("REDUCED?", j))
        elif nxt in {".", ",", ";", ":", "?", "!", ")", ""} and w not in HOMOGRAPHS:
            # "with the cup provided." - the noun phrase is an object, not a subject
            d = j - 2
            while d >= 0 and d >= j - 3 and words[d] not in DETERMINERS:
                d -= 1
            if d >= 1 and words[d] in DETERMINERS and is_word(words[d - 1]) \
                    and words[d - 1] not in SUBORDINATORS:
                hits.append(("REDUCED?", j))
    return [(c, j) for c, j in hits if not attributive(words, j)]


def attributive(words, j):
    """A participle inside a hyphenated compound ("patient-signed") is an
    adjective, not a clause."""
    prev = words[j - 1] if j else ""
    nxt = words[j + 1] if j + 1 < len(words) else ""
    return prev == "-" or nxt == "-"


# ---------------------------------------------------------------- spans
def protected_spans(line):
    """Mentions: `code`, *italics* (single asterisks only; **bold** stays checked), quotations."""
    spans = []
    for m in re.finditer(r"`[^`]*`|(?<!\*)\*(?!\*)[^*\s][^*]*?(?<!\*)\*(?!\*)|“[^”]*”|\"[^\"]*\"", line):
        spans.append((m.start(), m.end()))
    return spans


def in_spans(pos, spans):
    return any(a <= pos < b for a, b in spans)


SPACY_NLP = None


def spacy_hits(doc):
    """Dependency-parse pass over a parsed line: passive subjects/auxiliaries and VBN modifiers."""
    out = []
    for t in doc:
        if t.dep_ in ("auxpass", "nsubjpass", "csubjpass"):
            out.append(("PASSIVE", t.head.idx))
        elif t.tag_ == "VBN" and t.dep_ in ("acl", "relcl", "advcl", "xcomp", "ccomp", "conj", "ROOT"):
            if not any(c.dep_ in ("aux",) and c.lower_ in HAVE for c in t.children):
                if t.dep_ == "acl":
                    out.append(("REDUCED", t.idx))
                elif any(c.dep_ in ("nsubj",) for c in t.children):
                    continue
                elif t.dep_ in ("xcomp", "ccomp") and t.head.lemma_ in ("have", "get"):
                    out.append(("CAUSATIVE", t.idx))
    return out


def check_text(text, use_spacy=True):
    """Yield (line_no, code, snippet) for every hit."""
    in_verbatim = False
    in_mention = False
    results = []
    lines = text.splitlines()
    parsed = {}
    if use_spacy and SPACY_NLP is not None:
        # One batched parse is far faster than one call per line.
        prose, code_block = [], False
        for i, line in enumerate(lines):
            if line.lstrip().startswith("```"):
                code_block = not code_block
            elif not code_block and line.strip():
                prose.append(i)
        docs = SPACY_NLP.pipe((lines[i].replace("’", "'") for i in prose), batch_size=256)
        parsed = dict(zip(prose, docs))
    in_code = False
    for ln, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue  # program code is not prose
        if "<!-- av:verbatim -->" in line:
            in_verbatim = True
        if "<!-- av:mention -->" in line:
            in_mention = True
        tokens = tokenize(line)
        spans = protected_spans(line)
        seen = set()
        raw = [(code, tokens[j][1]) for code, j in find_hits(tokens)]
        if ln - 1 in parsed:
            raw += spacy_hits(parsed[ln - 1])
        for code, pos in sorted(raw, key=lambda x: x[1]):
            if any(abs(pos - p) < 3 for p in seen):
                continue
            seen.add(pos)
            if in_verbatim:
                code = "MANDATED"
            elif in_mention or in_spans(pos, spans):
                code = "MENTION"
            snippet = line[max(0, pos - 45):pos + 30].strip()
            results.append((ln, code, snippet))
        if "<!-- /av:verbatim -->" in line:
            in_verbatim = False
        if "<!-- /av:mention -->" in line:
            in_mention = False
    return results


BLOCKING = {"PASSIVE", "GET-PASSIVE", "PSEUDO", "CAUSATIVE", "REDUCED",
            "REDUCED?", "CONCEALED", "ELLIPTICAL"}


def main(argv):
    global SPACY_NLP
    model = "en_core_web_sm"
    if "--model" in argv:
        i = argv.index("--model")
        if i + 1 >= len(argv):
            print("--model needs a model name", file=sys.stderr)
            return 2
        model = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    files = [a for a in argv if not a.startswith("--")]
    use_spacy = "--no-spacy" not in argv
    quiet = "--quiet" in argv
    strict = "--strict" in argv  # count MENTION hits as blocking
    if use_spacy:
        try:
            import spacy
            try:
                SPACY_NLP = spacy.load(model, exclude=["ner"])
            except OSError:
                print(f"spaCy model {model} is not installed; running the regex pass only", file=sys.stderr)
                SPACY_NLP = None
        except ImportError:
            SPACY_NLP = None
    blocking = 0
    for fn in files:
        with open(fn, encoding="utf-8") as fh:
            res = check_text(fh.read(), use_spacy)
        for ln, code, snip in res:
            counts = code in BLOCKING or (strict and code == "MENTION")
            if counts:
                blocking += 1
            if not quiet or counts:
                print(f"{fn}:{ln}: {code:<11} ...{snip}...")
    engine = f"regex + spaCy {model}" if SPACY_NLP is not None else "regex only"
    print(f"[{engine}] blocking hits: {blocking}", file=sys.stderr)
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
