#!/usr/bin/env python3.13
"""observe-diyet.py - `agent observe` çıktısının token anatomisi ve azaltma seçenekleri (o200k_base).

Girdi: kayıtlı observe-*.json dosyaları (DATA_DIR). Sayfa yeniden çekilmez.
Çıktı: stdout'a anatomi ve seçenek tabloları (markdown). Yazılı bir şey değiştirmez.

Kullanım:
  /Users/nadir/01dev/_venvs/tiktoken/bin/python3.13 -I .claude/docs/olcum/observe-diyet.py
"""

import json
import os
import re
import sys
from collections import Counter

import tiktoken

DATA_DIR = "/Users/nadir/01dev/cdpilot-olcum-ham/json-bicim-2026-11-11"
SITES = ["hn", "enwiki", "mdn", "trwiki", "jawiki"]
ENC = tiktoken.get_encoding("o200k_base")

# src/cdpilot.py:15963-15967 (AGENT_INTERACTIVE_ROLES) aynen
INTERACTIVE = {
    'button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox',
    'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'spinbutton',
    'slider', 'switch', 'tab', 'treeitem', 'searchbox', 'gridcell',
}
# Eylemlenebilir olup listede olmayan rol (MDN'de görüldü): açılır üçgen
EXTRA_ACTIONABLE = {'DisclosureTriangle'}
# Yön bulmaya yarayan, kısa adlı işaret roller
LANDMARK = {'heading', 'region', 'navigation'}
TEXT_ROLES = {'StaticText', 'paragraph', 'heading'}
NAME_CAP = 80


def tok(s):
    return len(ENC.encode(s))


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(',', ':'))


def load(site):
    with open(os.path.join(DATA_DIR, f"observe-{site}.json"), encoding="utf-8") as f:
        return json.load(f)


def pack(base, actions, text=None):
    d = {'url': base['url'], 'title': base['title'], 'actions': actions,
         'text': base['text'] if text is None else text}
    d['token_estimate'] = base['token_estimate']  # alan var; değer 4-5 hane, maliyet sabit
    return d


def total(base, actions, text=None):
    return tok(dump(pack(base, actions, text)))


# --- anatomi -----------------------------------------------------------------

def anatomy(base):
    acts = base['actions']
    whole = total(base, acts)
    f = Counter()
    for a in acts:
        for k in ('ref', 'role', 'name'):
            f[k] += tok(dump({k: a[k]})) - 2  # {} çıkar
    entries = sum(tok(dump(a)) for a in acts)
    struct = entries - sum(f.values())
    top = {k: tok(dump({k: v})) - 2 for k, v in base.items() if k != 'actions'}
    top['actions_sarmal'] = whole - entries - sum(top.values())  # "actions":[ ] ve virgüller
    return whole, f, struct, top


def by_role(base):
    r = Counter()
    n = Counter()
    for a in base['actions']:
        r[a['role']] += tok(dump(a)) + 1
        n[a['role']] += 1
    return r, n


def classify(role):
    if role in INTERACTIVE or role in EXTRA_ACTIONABLE:
        return 'actionable'
    if role in LANDMARK:
        return 'landmark'
    return 'non-actionable'


# --- seçenekler --------------------------------------------------------------

def opt_A(base, keep_landmark=False):
    """Eylemlenebilir rol süzgeci (yalnız çıktı; actions_map tam kalır)."""
    keep = INTERACTIVE | EXTRA_ACTIONABLE | (LANDMARK if keep_landmark else set())
    return [a for a in base['actions'] if a['role'] in keep]


def text_from_dropped(base, kept):
    """A'nın düşürdüğü metin rollerinden `text` alanı: src'deki 2000 karakter sınırı."""
    kept_refs = {a['ref'] for a in kept}
    parts = [a['name'].strip() for a in base['actions']
             if a['ref'] not in kept_refs and a['role'] in TEXT_ROLES and a['name'].strip()]
    t = ' '.join(parts)
    return (base['text'] + ' ' + t)[:2000]


def opt_B(acts, cap=NAME_CAP):
    """Ad kırpma: cap-1 karakter + '…' (yalnız çıktı)."""
    out = []
    for a in acts:
        n = a['name']
        if len(n) > cap:
            n = n[:cap - 1].rstrip() + '…'
        out.append({**a, 'name': n})
    return out


def _norm(s):
    return re.sub(r'\s+', '', s.replace('\xa0', ' '))


def container_flags(acts, cover=0.9, look=24):
    """Eylemlenemez bir girdinin adı, sonraki girdilerin adlarının art arda dizilişiyse (>=%90) kap sayılır.
    Gerçek uygulama AX childIds kullanır; bu sıra tabanlı sezgi alt sınırdır."""
    drop = set()
    for i, a in enumerate(acts):
        if classify(a['role']) == 'actionable':
            continue
        nm = _norm(a['name'])
        if len(nm) < 3:
            continue
        pos, covered = 0, 0
        for b in acts[i + 1:i + 1 + look]:
            s = _norm(b['name'])
            if not s:
                continue
            k = nm.find(s, pos)
            if k >= 0:
                covered += len(s)
                pos = k + len(s)
                if covered >= cover * len(nm):
                    break
        if covered >= cover * len(nm):
            drop.add(i)
    return drop


def opt_C(acts):
    d = container_flags(acts)
    # ad, sayfadaki bir eylemlenebilir girdinin adıyla aynıysa (sıradan bağımsız) kopya sayılır
    act_names = {_norm(a['name']) for a in acts if classify(a['role']) == 'actionable' and a['name'].strip()}
    for i, a in enumerate(acts):
        if classify(a['role']) != 'actionable' and _norm(a['name']) in act_names:
            d.add(i)
    return [a for i, a in enumerate(acts) if i not in d]


def opt_D(base, acts, budget):
    """Jeton bütçesi: AX sırasıyla bütçe dolana dek; kalan için `more` imleci."""
    fixed = tok(dump({'url': base['url'], 'title': base['title'], 'actions': [], 'text': base['text'],
                      'token_estimate': base['token_estimate'], 'more': {'n': 9999, 'from': 9999}}))
    used, out = fixed, []
    for a in acts:
        c = tok(dump(a)) + 1
        if used + c > budget:
            break
        out.append(a)
        used += c
    return out, len(acts) - len(out)


def short_keys(acts):
    return [{'r': a['ref'], 'k': a['role'], 'n': a['name']} for a in acts]


def tuples(acts):
    return [[a['ref'], a['role'], a['name']] for a in acts]


def lines(acts):
    return [f"{a['ref']} {a['role']} {a['name']}" for a in acts]


def fmt_total(base, rows, text=None, more=None):
    d = pack(base, rows, text)
    if more is not None:
        d['more'] = more
    return tok(dump(d))


def dup_stats(acts):
    c = Counter((a['role'], a['name']) for a in acts)
    groups = sum(1 for v in c.values() if v > 1)
    extra = sum(v - 1 for v in c.values() if v > 1)
    return groups, extra


def main():
    res = {}
    print("## ANATOMİ (o200k, kompakt UTF-8, mevcut çıktı biçimi)\n")
    print("| Sayfa | Toplam tok | girdi | actions alanı | url+title | text | token_estimate alanı | ref | role | name | yapı (`{},:\"`) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in SITES:
        b = load(s)
        whole, f, struct, top = anatomy(b)
        n = len(b['actions'])
        res[s] = b
        print(f"| {s} | {whole} | {n} | {sum(f.values()) + struct} | {top['url'] + top['title']} | {top['text']} | "
              f"{top['token_estimate']} | {f['ref']} ({f['ref']*100//whole}%) | {f['role']} ({f['role']*100//whole}%) | "
              f"{f['name']} ({f['name']*100//whole}%) | {struct} ({struct*100//whole}%) |")

    print("\n## ROL BAZLI (girdi sayısı / token / toplam payı)\n")
    for s in SITES:
        b = res[s]
        whole = total(b, b['actions'])
        r, n = by_role(b)
        print(f"**{s}** (toplam {whole})")
        print("| Rol | Sınıf | Girdi | Token | Pay |")
        print("|---|---|---|---|---|")
        for role, t in r.most_common(8):
            print(f"| {role} | {classify(role)} | {n[role]} | {t} | {t*100/whole:.1f}% |")
        print()

    print("## EYLEMLENEMEZ PAY, KOPYA AD, UZUN AD\n")
    print("| Sayfa | Girdi | Eylemlenebilir | Eylemlenemez (landmark dahil) | tok | pay | Yalnız landmark | Kopya (rol+ad) grup/fazla girdi | Kopya fazla tok | Ad >80 kar. | Ad >80 tok payı | Aynı adlı link ref (en kalabalık) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for s in SITES:
        b = res[s]
        acts = b['actions']
        whole = total(b, acts)
        non = [a for a in acts if classify(a['role']) != 'actionable']
        non_tok = sum(tok(dump(a)) + 1 for a in non)
        lm = sum(1 for a in acts if classify(a['role']) == 'landmark')
        g, ex = dup_stats(acts)
        seen, dtok = set(), 0
        for a in acts:
            key = (a['role'], a['name'])
            if key in seen:
                dtok += tok(dump(a)) + 1
            seen.add(key)
        longs = [a for a in acts if len(a['name']) > NAME_CAP]
        ltok = sum(tok(dump({'name': a['name']})) - 2 for a in longs)
        links = Counter(a['name'] for a in acts if a['role'] == 'link')
        top = links.most_common(1)[0] if links else ('', 0)
        print(f"| {s} | {len(acts)} | {len(acts)-len(non)} | {len(non)} | {non_tok} | {non_tok*100/whole:.1f}% | {lm} | "
              f"{g}/{ex} | {dtok} | {len(longs)} | {ltok} ({ltok*100/whole:.1f}%) | {top[1]}× {top[0][:24]!r} |")

    print("\n## SEÇENEKLER (toplam çıktı tokeni; yüzde = azalma)\n")
    cols = ["taban", "A", "A+landmark", "A+metin", "B(80)", "C", "A+B", "A+C+B",
            "A+C+B+D(1500)", "A+C+B+D(3000)", "E1 kısa anahtar", "E2 dizi", "E3 satır", "ÖNERİ"]
    print("| Sayfa | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))
    for s in SITES:
        b = res[s]
        acts = b['actions']
        base_t = total(b, acts)
        A = opt_A(b)
        A2 = opt_A(b, True)
        Atxt = total(b, A, text_from_dropped(b, A))
        Bt = total(b, opt_B(acts))
        Ct = total(b, opt_C(acts))
        AB = opt_B(A)
        ABt = total(b, AB)
        ACB = opt_B(opt_C(A))
        ACBt = total(b, ACB)
        Dacts, rest = opt_D(b, ACB, 1500)
        Dt = fmt_total(b, Dacts, more={'n': rest, 'from': len(Dacts)})
        D3, rest3 = opt_D(b, ACB, 3000)
        D3t = fmt_total(b, D3, more={'n': rest3, 'from': len(D3)})
        E1 = fmt_total(b, short_keys(A))
        E2 = fmt_total(b, tuples(A))
        E3 = fmt_total(b, lines(A))
        # öneri: A+landmark + C + B(80) + satır biçimi yerine dizi (E2) değil, anahtar adı sabit kalsın → A2+C+B
        R = opt_B(opt_C(A2))
        Rt = total(b, R)
        row = [base_t, total(b, A), total(b, A2), Atxt, Bt, Ct, ABt, ACBt, Dt, D3t, E1, E2, E3, Rt]
        cells = [str(row[0])] + [f"{v} (-{(base_t - v) * 100 / base_t:.0f}%)" for v in row[1:]]
        print(f"| {s} | " + " | ".join(cells) + " |")

    print("\n## ÖNERİ R = A+landmark + C + B(80) + E2 + metin düzeltmesi\n")
    print("| Sayfa | taban | R | azalma |")
    print("|---|---|---|---|")
    for s in SITES:
        b = res[s]
        base_t = total(b, b['actions'])
        Rr = opt_B(opt_C(opt_A(b, True)))
        v = fmt_total(b, tuples(Rr), text_from_dropped(b, Rr))
        print(f"| {s} | {base_t} | {v} | -{(base_t - v) * 100 / base_t:.0f}% |")

    print("\n## SEÇENEK DETAYI (girdi sayısı)\n")
    print("| Sayfa | taban | A | A+landmark | C düşen (tüm liste) | C düşen (A+landmark sonrası eylemlenemez) | D bütçede kalan / `more` | B kırpılan ad |")
    print("|---|---|---|---|---|---|---|---|")
    for s in SITES:
        b = res[s]
        acts = b['actions']
        A = opt_A(b)
        A2 = opt_A(b, True)
        ACB = opt_B(opt_C(A))
        Dacts, rest = opt_D(b, ACB, 1500)
        cd = len(container_flags(acts))
        cd2 = len(container_flags(A2))
        trunc = sum(1 for a in acts if len(a['name']) > NAME_CAP)
        print(f"| {s} | {len(acts)} | {len(A)} | {len(A2)} | {cd} | {cd2} | {len(Dacts)}/{rest} | {trunc} |")

    print("\n## BAĞLAŞIM: kırpma sonrası çakışan (rol, ad) çiftleri (B güvenliği)\n")
    for s in SITES:
        b = res[s]
        before = {(a['role'], a['name']) for a in b['actions']}
        after = {(a['role'], a['name']) for a in opt_B(b['actions'])}
        print(f"- {s}: kırpmadan önce {len(before)} ayrı (rol, ad) çifti, sonra {len(after)}; birleşen çift {len(before) - len(after)}")

    print("\n## ANKRAJ ETKİSİ (A: yalnız-çıktı değil, kaynakta uygulanırsa)\n")
    print("| Sayfa | Ankrajlanamayacak girdi (rol düşer) | Kalan rol+ad gruplarında nth değişen |")
    print("|---|---|---|")
    for s in SITES:
        b = res[s]
        acts = b['actions']
        kept = opt_A(b, True)
        lost = len(acts) - len(kept)
        # nth rol+ad bazlıdır: tüm rol grubu düştüğü için kalan grupların nth'si değişmez
        shift = 0
        kc = Counter((a['role'], a['name']) for a in kept)
        ac = Counter((a['role'], a['name']) for a in acts)
        for k, v in kc.items():
            if v != ac[k]:
                shift += 1
        print(f"| {s} | {lost} | {shift} |")


if __name__ == '__main__':
    sys.exit(main())
