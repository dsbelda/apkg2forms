#!/usr/bin/env python3
"""APKG (Anki) -> script de Google Apps Script que crea Formularios tipo test.

Solo librería estándar (tkinter para la interfaz). Sin argumentos abre la interfaz;
con un .apkg funciona por línea de comandos:  python apkg2forms.py mazo.apkg
"""
import argparse, collections, csv, json, os, random, re, sqlite3, tempfile, zipfile
from html import unescape
from urllib.parse import unquote
from pathlib import Path

OPT = re.compile(r'^\(?([A-Da-d])\s*[.)]\s*(.+)$')  # "A. x", "a) x", "b.x"
RESP = re.compile(r'respuesta(?:\s+correcta)?\s*:?\s*\(?([a-d])(?=\)|\.|:|\s*$|\s*\()', re.I | re.M)
BOLD = re.compile(r'(?is)<(b|strong)\b[^>]*>(.*?)</\1>')
IMG = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.I)
ZSTD = b'\x28\xb5\x2f\xfd'
CLOZ = re.compile(r'\{\{c(\d+)::(.*?)(?:::.*?)?\}\}', re.S)

GS = '''// Generado por apkg2forms.
// 1) Pega esto en https://script.google.com (Proyecto nuevo)  2) elige crearFormularios  3) Ejecutar.
// Si quedan formularios por crear, vuelve a ejecutarla (Google limita cada ejecución a 6 min).
const FORMS = __DATA__;

function crearFormularios() {
  const props = PropertiesService.getScriptProperties();
  let i = Number(props.getProperty('next') || 0);
  const t0 = Date.now();
  for (; i < FORMS.length && Date.now() - t0 < 240000; i++) {
    const f = FORMS[i];
    const form = FormApp.create(f.title).setIsQuiz(true);
    f.items.forEach(q => {
      const it = form.addMultipleChoiceItem().setTitle(q.q).setPoints(1);
      it.setChoices(q.c.map((c, k) => it.createChoice(c, k === q.a)));
      if (q.f) {
        const fb = FormApp.createFeedback().setText(q.f).build();
        it.setFeedbackForCorrect(fb).setFeedbackForIncorrect(fb);
      }
    });
    Logger.log(f.title + ' -> ' + form.getEditUrl());
    props.setProperty('next', String(i + 1));
  }
  if (i >= FORMS.length) { props.deleteProperty('next'); Logger.log('Terminado'); }
  else Logger.log('Quedan ' + (FORMS.length - i) + ' formularios: vuelve a ejecutar crearFormularios');
}
'''


def clean(h):
    s = re.sub(r'(?i)<br\s*/?>|</(?:div|p|li|ul|ol)>', '\n', h)
    s = re.sub(r'(?i)<img[^>]*>|\[sound:[^\]]*\]|<[^>]+>', '', s)
    s = unescape(s).replace('\xa0', ' ')
    return '\n'.join(l.strip() for l in s.split('\n') if l.strip())


def _unzstd(b):
    try:
        from compression import zstd  # Python 3.14+
        return zstd.decompress(b)
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompressobj().decompress(b)
    except ImportError:
        raise ValueError('Este .apkg usa el formato nuevo de Anki (zstd). Haz una de estas dos cosas:\n'
                         ' - Exportar de nuevo en Anki marcando "Compatible con versiones antiguas"\n'
                         ' - Instalar el módulo:  pip install zstandard')


def load(path):
    """-> [(nombre_mazo, [campos HTML])], una entrada por nota."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if 'collection.anki21b' in names:
            raw = _unzstd(z.read('collection.anki21b'))
        else:
            raw = z.read('collection.anki21' if 'collection.anki21' in names else 'collection.anki2')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'c.db')
        Path(p).write_bytes(raw)
        db = sqlite3.connect(p)
        try:
            decks = dict(db.execute('select id, name from decks'))
        except sqlite3.OperationalError:  # formato antiguo: JSON dentro de col
            decks = {int(k): v['name'] for k, v in json.loads(db.execute('select decks from col').fetchone()[0]).items()}
        rows = db.execute('select c.did, n.flds from notes n join cards c on c.nid = n.id group by n.id order by n.id').fetchall()
        db.close()
    return [(decks.get(did, 'Default').replace('\x1f', ' / '), flds.split('\x1f')) for did, flds in rows]


def _varint(b, i):
    n = s = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 127) << s
        s += 7
        if c < 128:
            return n, i


def media_map(z):
    """-> {nombre_original: nombre_en_el_zip}"""
    if 'media' not in z.namelist():
        return {}
    raw = z.read('media')
    if raw[:4] != ZSTD:  # formato antiguo: JSON {"0": "foto.jpg"}
        return {v: k for k, v in json.loads(raw).items()}
    b, i, out = _unzstd(raw), 0, {}  # protobuf: repetido { 1: nombre }
    while i < len(b):
        ln, i = _varint(b, i + 1)
        nl, j = _varint(b[i:i + ln], 1)
        out[b[i + j:i + j + nl].decode()] = str(len(out))
        i += ln
    return out


def extract_images(apkg, pairs, folder):
    """Copia las imágenes [(origen, destino)] a folder; devuelve cuántas se copiaron."""
    n = 0
    with zipfile.ZipFile(apkg) as z:
        mm = media_map(z)
        for src, dst in pairs:
            key = mm.get(unquote(unescape(src)))
            if key is None:
                continue
            data = z.read(key)
            if data[:4] == ZSTD:  # Anki guarda los archivos comprimidos
                data = _unzstd(data)
            Path(folder).mkdir(exist_ok=True)
            (Path(folder) / dst).write_bytes(data)
            n += 1
    return n


def split_opts(lines):
    """-> (líneas_previas, opciones) si hay una lista a,b,c... consecutiva; si no, None."""
    for i, l in enumerate(lines):
        m = OPT.match(l)
        if not (m and m[1].lower() == 'a'):
            continue
        opts = [m[2]]
        for l2 in lines[i + 1:]:
            m2 = OPT.match(l2)
            if m2 and ord(m2[1].lower()) - 97 == len(opts):
                opts.append(m2[2])
            else:
                break
        if len(opts) >= 2:
            return lines[:i], opts


def find_letter(raws, texts, opts):
    """Índice de la opción correcta mirando los campos posteriores a las opciones."""
    n, L = len(opts), (lambda s: ord(s.lower()) - 97)
    for t in texts:  # "Respuesta: C", "Respuesta b)"
        m = RESP.search(t)
        if m and L(m[1]) < n:
            return L(m[1])
    for t in texts:  # solo "c)"
        m = re.fullmatch(r'\(?([A-Da-d])\s*[.)]?', t.strip())
        if m and L(m[1]) < n:
            return L(m[1])
    bold = {L(m[1]) for r in raws for b in BOLD.findall(r) for l in clean(b[1]).split('\n')
            for m in [OPT.match(l)] if m and L(m[1]) < n}  # opción en negrita
    if len(bold) == 1:
        return bold.pop()
    for t in texts:  # el reverso repite una única opción
        ms = [m for m in map(OPT.match, t.split('\n')) if m]
        if len(ms) == 1 and L(ms[0][1]) < n:
            return L(ms[0][1])
    low = [o.casefold() for o in opts]  # el reverso es el texto de la opción
    hit = {low.index(l.casefold()) for t in texts for l in [t] + t.split('\n') if l.casefold() in low}
    if len(hit) == 1:
        return hit.pop()


def explain(texts, opts):
    """Texto de explicación: lo que queda de los campos tras quitar la respuesta y las opciones."""
    keep = [l for t in texts if not split_opts(t.split('\n')) for l in t.split('\n')
            if not RESP.search(l) and not re.fullmatch(r'\(?[A-Da-d]\s*[.)]?', l) and l not in opts
            and not (OPT.match(l) and OPT.match(l)[2] in opts)]
    return '\n'.join(keep)[:400]


def parse_note(deck, f, basic, st, bad):
    txt = [clean(x) for x in f]

    def skip(reason):
        st[reason] += 1
        bad.append((deck, reason, '', '', txt[0][:300], []))
        return []
    for k, t in enumerate(txt):
        found = split_opts(t.split('\n'))
        if not found:
            continue
        pre, opts = found
        q = '\n'.join(txt[:k] + pre).strip()
        if not q:
            break
        if len(set(opts)) != len(opts):
            return skip('opciones repetidas')
        idx = find_letter(f[k + 1:], txt[k + 1:], opts)
        if idx is None:
            return skip('sin respuesta detectable')
        st['test'] += 1
        it = dict(q=q, c=opts, a=idx, img=IMG.findall(''.join(f[:k + 1])))
        fb = explain(txt[k + 1:], opts)
        if fb:
            it['f'] = fb
        return [it]
    if not basic:
        return skip('tarjeta normal (omitida)')
    if CLOZ.search(txt[0]):
        out = []
        for n in sorted({m[0] for m in CLOZ.findall(txt[0])}):
            ans = []

            def sub(m):
                if m[1] == n:
                    ans.append(m[2])
                    return '_____'
                return m[2]
            out.append(dict(q=CLOZ.sub(sub, txt[0]), ans=', '.join(ans), img=IMG.findall(f[0])))
        return out
    a = '; '.join(txt[1].split('\n')) if len(txt) > 1 else ''
    if txt[0] and a and len(a) <= 200:
        return [dict(q=txt[0], ans=a, img=IMG.findall(f[0]))]
    return skip('respuesta vacía o demasiado larga')


def build(notes, n_opts=3, per_form=100, basic=True, seed=1):
    """-> (texto del .gs, Counter de estadísticas, nº de formularios, filas para el informe)."""
    rnd, st, raw, bad = random.Random(seed), collections.Counter(), [], []
    for deck, f in notes:
        raw += [(deck, it) for it in parse_note(deck, f, basic, st, bad)]
    by_deck = collections.defaultdict(dict)  # dict = conjunto con orden estable
    for deck, it in raw:
        if 'ans' in it:
            by_deck[deck][it['ans']] = 1
    everyone = list(dict.fromkeys(a for d in by_deck.values() for a in d))
    groups = collections.defaultdict(list)
    for deck, it in raw:
        if 'ans' in it:
            a = it['ans']
            d = [x for x in by_deck[deck] if x != a]
            rnd.shuffle(d)
            d = d[:n_opts]
            if len(d) < n_opts:
                d += [x for x in rnd.sample(everyone, min(len(everyone), 3 * n_opts)) if x != a and x not in d][:n_opts - len(d)]
            if not d:
                st['sin opciones falsas suficientes'] += 1
                bad.append((deck, 'sin opciones falsas suficientes', '', '', it['q'][:300], []))
                continue
            c = d + [a]
            rnd.shuffle(c)
            it = dict(q=it['q'], c=c, a=c.index(a), img=it['img'])
            st['normal/cloze'] += 1
        groups[deck].append(it)
    forms = []
    for deck, items in groups.items():
        chunks = [items[i:i + per_form] for i in range(0, len(items), per_form)]
        for i, ch in enumerate(chunks, 1):
            title = deck if len(chunks) == 1 else '%s (%d/%d)' % (deck, i, len(chunks))
            for j, it in enumerate(ch, 1):
                imgs = it.pop('img')
                if imgs:  # se marca la pregunta y se prepara el nombre con el que se extraerá cada imagen
                    it['q'] = '[IMAGEN] ' + it['q']
                    base = re.sub(r'[\\/:*?"<>|\n]+', '_', title)[:80] + ' - pregunta %d' % j
                    pairs = [(src, base + ('' if len(imgs) == 1 else ' (%d)' % k) + os.path.splitext(src)[1])
                             for k, src in enumerate(imgs, 1)]
                    st['con imagen'] += 1
                    bad.append((deck, 'incluida, pero tenía imagen', title, j, it['q'][:300], pairs))
            forms.append(dict(title=title, items=ch))
    return GS.replace('__DATA__', json.dumps(forms, ensure_ascii=True, separators=(',', ':'))), st, len(forms), bad


def write_report(path, bad):
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:  # utf-8-sig: Excel abre bien los acentos
        csv.writer(fh).writerows([('mazo', 'motivo', 'formulario', 'nº pregunta', 'pregunta', 'imagen (archivo)')]
                                    + [r[:5] + ('; '.join(t for _, t in r[5]),) for r in bad])


def summary(st, nforms):
    ok = ('test', 'normal/cloze', 'con imagen')
    skipped = sum(v for k, v in st.items() if k not in ok)
    lines = ['Preguntas: %d test + %d normales/cloze  ->  %d formularios' % (st['test'], st['normal/cloze'], nforms)]
    lines += ['Omitidas: %d' % skipped] + ['   %s: %d' % kv for kv in st.items() if kv[0] not in ok]
    if st['con imagen']:
        lines.append('Con imagen en la pregunta: %d (marcadas con [IMAGEN] en el formulario)' % st['con imagen'])
    return '\n'.join(lines)


def report(out, bad, apkg):
    """Escribe el informe junto al .gs; devuelve la línea para mostrar al usuario."""
    if not bad:
        return ''
    p = str(Path(out).with_suffix('.revisar.csv'))
    write_report(p, bad)
    msg = '\nInforme para revisar (%d filas): %s' % (len(bad), p)
    pairs = [x for r in bad for x in r[5]]
    if pairs:
        folder = str(Path(out).with_suffix('')) + '-imagenes'
        msg += '\nImágenes: %d de %d copiadas en %s' % (extract_images(apkg, pairs, folder), len(pairs), folder)
    return msg


HELP = '''
Siguientes pasos:
 1. Abre https://script.google.com -> Proyecto nuevo
 2. Borra el código de ejemplo y pega el contenido del .gs (la interfaz lo copia al portapapeles con "Copiar script")
 3. Arriba elige la función "crearFormularios" y pulsa Ejecutar (acepta los permisos)
 4. Los enlaces salen en el Registro de ejecución. Si quedan formularios, ejecútala otra vez.'''


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.title('APKG -> Google Forms')
    state = dict(path='', notes=[], names=[])
    top = tk.Frame(root); top.pack(fill='x', padx=8, pady=6)
    lbl = tk.Label(top, text='Ningún archivo', anchor='w'); lbl.pack(side='right', fill='x', expand=True, padx=8)
    lb = tk.Listbox(root, selectmode='extended', width=80, height=14, exportselection=False)
    lb.pack(fill='both', expand=True, padx=8)
    opt = tk.Frame(root); opt.pack(fill='x', padx=8, pady=6)
    n_opts, per_form, basic = tk.IntVar(value=3), tk.IntVar(value=100), tk.BooleanVar(value=True)
    tk.Label(opt, text='Opciones falsas:').pack(side='left')
    tk.Spinbox(opt, from_=1, to=5, width=3, textvariable=n_opts).pack(side='left', padx=4)
    tk.Label(opt, text='Preguntas por formulario:').pack(side='left', padx=(10, 0))
    tk.Spinbox(opt, from_=5, to=500, width=5, textvariable=per_form).pack(side='left', padx=4)
    tk.Checkbutton(opt, text='Incluir tarjetas normales y cloze', variable=basic).pack(side='left', padx=10)
    log = tk.Text(root, height=10, width=80); log.pack(fill='x', padx=8, pady=(0, 6))

    def say(s):
        log.delete('1.0', 'end'); log.insert('end', s)

    def abrir():
        p = filedialog.askopenfilename(filetypes=[('Anki', '*.apkg'), ('Todos', '*.*')])
        if not p:
            return
        try:
            notes = load(p)
        except Exception as e:
            return messagebox.showerror('Error', str(e))
        cnt = collections.Counter(d for d, _ in notes)
        state.update(path=p, notes=notes, names=sorted(cnt))
        lbl.config(text=os.path.basename(p))
        lb.delete(0, 'end')
        for n in state['names']:
            lb.insert('end', '%s  (%d)' % (n, cnt[n]))
        lb.select_set(0, 'end')
        say('%d notas en %d mazos. Elige los mazos y pulsa Generar.' % (len(notes), len(cnt)))

    def generar(guardar):
        sel = {state['names'][i] for i in lb.curselection()}
        if not sel:
            return messagebox.showinfo('Nada que hacer', 'Abre un .apkg y elige mazos.')
        gs, st, nf, bad = build([x for x in state['notes'] if x[0] in sel], n_opts.get(), per_form.get(), basic.get())
        if not nf:
            return say(summary(st, nf))
        root.clipboard_clear(); root.clipboard_append(gs)
        if not guardar:
            nota = '\n\nCopiado al portapapeles (no se ha guardado nada).'
            if bad:
                nota += '\nUsa "Guardar script" si quieres el informe .csv y las imágenes extraídas.'
            return say(summary(st, nf) + nota + HELP)
        out = filedialog.asksaveasfilename(defaultextension='.gs', initialfile=Path(state['path']).stem + '.gs')
        if not out:
            return
        Path(out).write_text(gs, encoding='utf-8')
        say(summary(st, nf) + '\n\nGuardado en ' + out + ' y copiado al portapapeles' + report(out, bad, state['path']) + HELP)

    tk.Button(top, text='Abrir .apkg…', command=abrir).pack(side='left')
    tk.Button(opt, text='Guardar script…', command=lambda: generar(True)).pack(side='right')
    tk.Button(opt, text='Copiar script', command=lambda: generar(False)).pack(side='right', padx=6)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('apkg', nargs='?', help='sin él se abre la interfaz')
    ap.add_argument('-o', help='fichero .gs de salida')
    ap.add_argument('-n', type=int, default=3, help='opciones falsas en tarjetas normales/cloze')
    ap.add_argument('-p', type=int, default=100, help='preguntas por formulario')
    ap.add_argument('--solo-test', action='store_true', help='omitir tarjetas normales y cloze')
    a = ap.parse_args()
    if not a.apkg:
        return gui()
    gs, st, nf, bad = build(load(a.apkg), a.n, a.p, not a.solo_test)
    out = a.o or str(Path(a.apkg).with_suffix('.gs'))
    Path(out).write_text(gs, encoding='utf-8')
    print(summary(st, nf) + '\nGuardado en ' + out + report(out, bad, a.apkg) + HELP)


if __name__ == '__main__':
    main()
