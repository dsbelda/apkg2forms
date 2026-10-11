"""python test_apkg2forms.py  -> falla con AssertionError si algo se rompe."""
import json, os, sqlite3, tempfile, zipfile
import apkg2forms as m

NOTES = [  # (campos, esperado: índice correcto o None)
    (['1. Pregunta<br>A. uno<br>B. dos<br>C. tres', 'x<br>A. uno<br><b>B. dos</b><br>C. tres'], 1),  # negrita
    (['Q<br>A) a1<br>B) b1', 'Respuesta: <B>B</B> (Página 4)'], 1),  # "Respuesta: B"
    (['Q', 'a) x<br>b) y<br>c) z', 'c)', 'La respuesta a la pregunta es larga'], 2),  # campo aparte
    (['Q<br>A. p<br>B. q', 'B. q'], 1),  # reverso repite la opción
    (['Q<br>A. p<br>B. q', 'Respuesta: La IA dice A'], None),  # sin respuesta detectable
    (['Q<img src="p.jpg"><br>A. u<br>B. v', 'Respuesta: A'], 0),  # con imagen
]
BASIC = [['Capital de Francia', 'París'], ['Capital de España', 'Madrid'], ['Capital de Italia', 'Roma'],
         ['Capital de Portugal', 'Lisboa'], ['{{c1::Python}} es un {{c2::lenguaje}}', '']]


def make_apkg(path):
    with tempfile.TemporaryDirectory() as d:
        db = sqlite3.connect(os.path.join(d, 'c.db'))
        db.execute('create table col(decks text)')
        db.execute('insert into col values (?)', (json.dumps({'7': {'name': 'Mazo::Sub'}}),))
        db.execute('create table notes(id integer, flds text)')
        db.execute('create table cards(nid integer, did integer)')
        for i, f in enumerate([n[0] for n in NOTES] + BASIC):
            db.execute('insert into notes values (?, ?)', (i, '\x1f'.join(f)))
            db.execute('insert into cards values (?, 7)', (i,))
        db.commit(); db.close()
        with zipfile.ZipFile(path, 'w') as z:
            z.write(os.path.join(d, 'c.db'), 'collection.anki2')
            z.writestr('media', json.dumps({'0': 'p.jpg'}))
            z.writestr('0', b'IMG')


with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, 't.apkg')
    make_apkg(p)
    gs, st, nf, bad = m.build(m.load(p))
    forms = json.loads(gs.split('const FORMS = ')[1].split(';\n\nfunction')[0])
    assert nf == 1 and forms[0]['title'] == 'Mazo::Sub', forms[0]['title']
    items = forms[0]['items']
    assert [i['a'] for i in items[:4]] == [1, 1, 2, 1], items[:4]
    assert st['test'] == 5 and st['sin respuesta detectable'] == 1 and st['normal/cloze'] == 6, st
    assert items[2]['f'] == 'La respuesta a la pregunta es larga' and 'f' not in items[0], items[:3]
    assert [b[1] for b in bad][0] == 'sin respuesta detectable', bad
    assert all(i['c'][i['a']] for i in items) and all(len(set(i['c'])) == len(i['c']) for i in items)
    assert items[-1]['c'][items[-1]['a']] == 'lenguaje' and '_____' in items[-1]['q']
    assert items[4]['q'].startswith('[IMAGEN] ') and st['con imagen'] == 1
    row = [b for b in bad if b[1] == 'incluida, pero tenía imagen'][0]
    assert row[5] == [('p.jpg', 'Mazo_Sub - pregunta 5.jpg')], row
    out = os.path.join(d, 'o.gs')
    assert '1 de 1' in m.report(out, bad, p)
    assert open(os.path.join(d, 'o-imagenes', 'Mazo_Sub - pregunta 5.jpg'), 'rb').read() == b'IMG'
    _, st2, _, _ = m.build(m.load(p), basic=False)
    assert st2['normal/cloze'] == 0

# --- PDF: texto de LaTeX con acentos sueltos, líneas partidas y "1.000" al principio de línea
SNIP = """GESTI´ON DE EMPRESAS
Convocatoria de febrero
1. Los juegos en los que el maxi-min coincide, se denominan
A. Juegos con m´ aximo absoluto
B. El ﬂujo neto de una inversi´ on se deﬁne por la diferencia entre
los cobros y los pagos de ese
moment
C. 1.000 u.m.
D. Ninguna
2. ¿Cu´ al es la entrop´ ıa de la moneda de Espa˜ na?
A. 1,0000 bits
B. 0,9710 bits
1.000 u.m. m´ as
C. Otra
"""
qs = m.parse_questions(m.fix_text(SNIP))
assert [len(q['opts']) for q in qs] == [4, 3], qs
assert qs[0]['opts'][0] == 'Juegos con máximo absoluto' and qs[0]['opts'][2] == '1.000 u.m.', qs[0]
assert qs[0]['opts'][1] == 'El flujo neto de una inversión se define por la diferencia entre los cobros y los pagos de ese moment'
assert qs[1]['stem'] == '¿Cuál es la entropía de la moneda de España?' and qs[1]['opts'][1] == '0,9710 bits 1.000 u.m. más', qs[1]
assert m.fix_text('Ingenier´ ıa Sup´ ongase') == 'Ingeniería Supóngase'
assert m.parse_key('CA', 2) == {1: 'C', 2: 'A'} and m.parse_key('1C 2-', 2) == {1: 'C', 2: '-'}
try:
    m.parse_key('CAB', 2)
    raise SystemExit('parse_key debía fallar')
except ValueError:
    pass
st3 = m.build(m.pdf_notes('X', qs, {}, {}))[1]
assert st3['sin clave'] == 2 and 'AVISO' in m.summary(st3, 1)
gs3 = m.build(m.pdf_notes('X', qs, {1: 'C'}, {1: ['pdf:1:Im1.png']}))[0]
f3 = json.loads(gs3.split('const FORMS = ')[1].split(';\n\nfunction')[0])[0]
assert f3['quiz'] and f3['items'][0]['a'] == 2 and f3['items'][1]['a'] == -1 and f3['items'][0]['q'].startswith('[IMAGEN] '), f3
assert not json.loads(m.build(m.pdf_notes('X', qs, {}, {}))[0].split('const FORMS = ')[1].split(';\n\nfunction')[0])[0]['quiz']
print('ok')
