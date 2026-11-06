import type { ReactNode } from "react";

// A small Markdown renderer for ADVESTIQ reports. It builds React elements (never raw HTML),
// so report text cannot inject markup. Supports headings, paragraphs, lists (one nested level),
// tables, quotes, code blocks, rules, **bold**, `code` and [links](https://...).

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
const LIST_ITEM = /^\s*([-*]|\d+\.)\s+/;

function inline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE)) {
    const start = match.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    const token = match[0];
    const key = `${keyBase}-${index++}`;
    if (token.startsWith("**")) nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    else nodes.push(<a key={key} href={match[2]} target="_blank" rel="noreferrer">{token.slice(1, token.indexOf("]("))}</a>);
    last = start + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function list(items: string[], key: number) {
  const top: { text: string; children: string[] }[] = [];
  for (const raw of items) {
    const indent = raw.length - raw.trimStart().length;
    const text = raw.trimStart().replace(LIST_ITEM, "");
    if (indent >= 2 && top.length) top[top.length - 1].children.push(text);
    else top.push({ text, children: [] });
  }
  const children = top.map((item, i) => (
    <li key={i}>
      {inline(item.text, `${key}-${i}`)}
      {item.children.length ? <ul>{item.children.map((child, j) => <li key={j}>{inline(child, `${key}-${i}-${j}`)}</li>)}</ul> : null}
    </li>
  ));
  return /^\s*\d+\./.test(items[0]) ? <ol key={key}>{children}</ol> : <ul key={key}>{children}</ul>;
}

function table(rows: string[], key: number) {
  const cells = rows.map((row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim()));
  const body = cells.filter((row, i) => !(i === 1 && row.every((cell) => /^:?-{2,}:?$/.test(cell))));
  const [head, ...rest] = body;
  return (
    <div className="markdown-table" key={key}>
      <table>
        <thead><tr>{head.map((cell, j) => <th key={j}>{inline(cell, `${key}-h${j}`)}</th>)}</tr></thead>
        <tbody>{rest.map((row, r) => <tr key={r}>{row.map((cell, j) => <td key={j}>{inline(cell, `${key}-${r}-${j}`)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export function MarkdownView({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push(<pre key={key++}>{body.join("\n")}</pre>);
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = inline(heading[2], `h${key}`);
      blocks.push(level === 1 ? <h2 key={key++}>{content}</h2> : level === 2 ? <h3 key={key++}>{content}</h3> : <h4 key={key++}>{content}</h4>);
      i++;
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { blocks.push(<hr key={key++} />); i++; continue; }
    if (line.trimStart().startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trimStart().startsWith("|")) rows.push(lines[i++]);
      blocks.push(table(rows, key++));
      continue;
    }
    if (line.startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(<blockquote key={key++}>{inline(quote.join(" "), `q${key}`)}</blockquote>);
      continue;
    }
    if (LIST_ITEM.test(line)) {
      const items: string[] = [];
      while (i < lines.length && LIST_ITEM.test(lines[i])) items.push(lines[i++]);
      blocks.push(list(items, key++));
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|>|```|\s*\|)/.test(lines[i]) && !LIST_ITEM.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    blocks.push(<p key={key++}>{inline(paragraph.join(" "), `p${key}`)}</p>);
  }
  return <div className="markdown-view">{blocks}</div>;
}
