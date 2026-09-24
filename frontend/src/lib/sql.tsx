import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { PostgreSQL, sql as sqlLanguage } from '@codemirror/lang-sql';
import { bracketMatching, indentOnInput, syntaxHighlighting, syntaxTree } from '@codemirror/language';
import { EditorState, RangeSetBuilder } from '@codemirror/state';
import { Decoration, type DecorationSet, EditorView, ViewPlugin, type ViewUpdate, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, placeholder as cmPlaceholder } from '@codemirror/view';
import { highlightCode, tagHighlighter, tags } from '@lezer/highlight';
import { type ReactNode, useEffect, useRef, useState } from 'react';

/**
 * SQL, shown as SQL everywhere in the explorer, with CodeMirror 6 and its SQL grammar (Postgres
 * dialect). One highlighter serves both uses, so a query is coloured the same everywhere:
 *
 * - `SqlBlock`, read-only: the grammar parses the text and `highlightCode` turns it into
 *   classed spans inside an editor-like frame (a "SQL · Postgres" header, line numbers, copy).
 *   No editor instance per block, so a page with forty queries stays light.
 * - `SqlEditor`, editable: a CodeMirror editor (line numbers, undo, bracket matching, indent
 *   on Tab) in the same frame, with the same classes.
 *
 * The colours are DESIGN.md's `--syn-*` tokens, which colour SQL and nothing else.
 */

/** The grammar's tags → the classes styles.css colours (`sq-*`). */
const HIGHLIGHT = tagHighlighter([
  { tag: [tags.keyword, tags.typeName, tags.bool, tags.null], class: 'sq-kw' },
  { tag: [tags.string], class: 'sq-str' },
  { tag: [tags.special(tags.string)], class: 'sq-id' },
  { tag: [tags.number], class: 'sq-num' },
  { tag: [tags.lineComment, tags.blockComment], class: 'sq-com' },
  { tag: [tags.standard(tags.name), tags.special(tags.name)], class: 'sq-fn' },
  { tag: [tags.operator, tags.punctuation, tags.paren, tags.brace, tags.squareBracket], class: 'sq-op' },
  { tag: [tags.name], class: 'sq-name' },
]);

export type Span = { text: string; cls: string };

/** The text as lines of classed spans; joining every span's text (and the line breaks) gives the
 *  input back. A name followed by "(" is a function call, as an editor would colour it. */
export function highlightLines(sql: string): Span[][] {
  const tree = PostgreSQL.language.parser.parse(sql);
  const lines: Span[][] = [[]];
  highlightCode(
    sql,
    tree,
    HIGHLIGHT,
    (text, cls) => lines[lines.length - 1].push({ text, cls }),
    () => lines.push([]),
  );
  const flat = lines.flat();
  for (let i = 0; i < flat.length; i++) {
    const s = flat[i];
    const next = flat.slice(i + 1).find((x) => x.text.trim() !== '');
    if (isCall(s.text, s.cls === 'sq-name' ? 'name' : s.cls === 'sq-kw' ? 'keyword' : null, next?.text.trimStart()[0])) s.cls = 'sq-fn';
  }
  return lines;
}

/** A function call, as an editor colours it: a name, or a keyword that is not structural
 *  (`count`, `lower`, `substring` are keywords in the Postgres dialect), followed by "(". The
 *  one rule both the read-only blocks and the editor use. */
export function isCall(text: string, kind: 'name' | 'keyword' | null, nextChar: string | undefined): boolean {
  if (nextChar !== '(' || kind == null) return false;
  return kind === 'name' || !STRUCTURAL.has(text.toLowerCase());
}

/** The editor's half of `isCall`: marks each call in the visible ranges with the function class. */
const callMarks = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = marks(view);
    }
    update(u: ViewUpdate) {
      if (u.docChanged || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) this.decorations = marks(u.view);
    }
  },
  { decorations: (v) => v.decorations },
);
const FN_MARK = Decoration.mark({ class: 'sq-fn cm-call' });

function marks(view: EditorView): DecorationSet {
  const b = new RangeSetBuilder<Decoration>();
  const doc = view.state.doc;
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(view.state).iterate({
      from,
      to,
      enter: (node) => {
        const kind = node.name === 'Identifier' ? 'name' : node.name === 'Keyword' ? 'keyword' : null;
        if (!kind) return;
        const after = doc.sliceString(node.to, Math.min(doc.length, node.to + 40)).trimStart()[0];
        if (isCall(doc.sliceString(node.from, node.to), kind, after)) b.add(node.from, node.to, FN_MARK);
      },
    });
  }
  return b.finish();
}

/** Keywords that open a parenthesis without being a function call (`IN (…)`, `AS (…)`). */
const STRUCTURAL = new Set(
  'in as exists values over using on and or not all any some from join where filter within when then else is select with recursive materialized lateral into table by partition order group having union intersect except returning'.split(' '),
);

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="sql-copy"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        });
      }}
    >
      {done ? 'copied' : 'copy'}
    </button>
  );
}

function Head({ label, text }: { label?: ReactNode; text: string }) {
  return (
    <div className="sql-head">
      <span className="sql-lang">SQL · Postgres</span>
      {label && <span className="sql-label">{label}</span>}
      <Copy text={text} />
    </div>
  );
}

/** Read-only SQL in an editor frame. `label` names where it came from (e.g. "agent · pass_through"). */
export function SqlBlock({ sql, label, maxHeight, band = false }: { sql: string; label?: ReactNode; maxHeight?: number; band?: boolean }) {
  const text = sql.replace(/\s+$/, '');
  const lines = highlightLines(text);
  return (
    <div className={`sql ${band ? 'band' : ''}`}>
      <Head label={label} text={text} />
      <div className="sql-body" style={maxHeight ? { maxHeight } : undefined}>
        <div className="sql-gutter" aria-hidden="true">
          {lines.map((_, i) => (
            <span key={i}>{i + 1}</span>
          ))}
        </div>
        <pre className="sql-code">
          <code>
            {lines.map((line, i) => (
              <span key={i}>
                {line.map((s, j) => (s.cls ? <span key={j} className={s.cls}>{s.text}</span> : s.text))}
                {i < lines.length - 1 ? '\n' : ''}
              </span>
            ))}
          </code>
        </pre>
      </div>
    </div>
  );
}

const editorTheme = EditorView.theme({
  '&': { fontSize: 'var(--t-1)', backgroundColor: 'transparent', color: 'var(--ink)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'var(--mono)', lineHeight: '1.5' },
  '.cm-content': { padding: 'var(--s3) 0', caretColor: 'var(--ink)' },
  '.cm-line': { padding: '0 var(--s3)' },
  '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--faint)', borderRight: '1px solid var(--line)' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 var(--s2) 0 var(--s3)' },
  '.cm-activeLine': { backgroundColor: 'var(--band)' },
  '.cm-activeLineGutter': { backgroundColor: 'var(--band)', color: 'var(--ink-2)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--ink)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': { backgroundColor: 'var(--accent-soft)' },
  '.cm-matchingBracket': { backgroundColor: 'var(--accent-soft)', outline: '1px solid var(--line-3)' },
  '.cm-placeholder': { color: 'var(--faint)' },
});

/** Editable SQL: a CodeMirror editor in the same frame. `value` stays the source of truth: an edit
 *  calls `onChange`, and a new `value` from outside (a load into the editor) replaces the text. */
export function SqlEditor({ value, onChange, rows = 12, placeholder, label, ariaLabel }: { value: string; onChange: (v: string) => void; rows?: number; placeholder?: string; label?: ReactNode; ariaLabel?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const change = useRef(onChange);
  change.current = onChange;
  useEffect(() => {
    if (!host.current) return;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          highlightActiveLine(),
          highlightActiveLineGutter(),
          history(),
          bracketMatching(),
          indentOnInput(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          sqlLanguage({ dialect: PostgreSQL }),
          syntaxHighlighting(HIGHLIGHT),
          callMarks,
          editorTheme,
          EditorView.contentAttributes.of({ 'aria-label': ariaLabel ?? 'SQL', spellcheck: 'false', autocapitalize: 'off', autocorrect: 'off' }),
          ...(placeholder ? [cmPlaceholder(placeholder)] : []),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) change.current(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = v;
    return () => v.destroy();
    // the editor is built once; `value` changes are pushed in below
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
  }, [value]);
  return (
    <div className="sql editing">
      <Head label={label} text={value} />
      <div className="sql-cm" ref={host} style={{ height: `calc(${Math.max(rows, 3)} * 1.5em + 2 * var(--s3))` }} />
    </div>
  );
}
