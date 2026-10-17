import { marked } from "marked";

// Answers quote text from KEPs and PRs, so rendered HTML is filtered through an allowlist: only these tags,
// only href on links (http/https), every link opens in a new tab.
const ALLOWED = new Set([
  "P", "BR", "STRONG", "EM", "CODE", "PRE", "A", "UL", "OL", "LI", "H1", "H2", "H3", "H4", "BLOCKQUOTE", "HR",
  "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DEL",
]); // prettier-ignore

function clean(node: Element) {
  for (const child of Array.from(node.children)) {
    if (!ALLOWED.has(child.tagName)) {
      child.replaceWith(document.createTextNode(child.textContent ?? ""));
      continue;
    }
    for (const attr of Array.from(child.attributes)) {
      const keep = child.tagName === "A" && attr.name === "href" && /^https?:\/\//i.test(attr.value);
      if (!keep) child.removeAttribute(attr.name);
    }
    if (child.tagName === "A") {
      child.setAttribute("target", "_blank");
      child.setAttribute("rel", "noopener noreferrer");
    }
    clean(child);
  }
}

export function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false, gfm: true, breaks: false }) as string;
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const root = doc.body.firstElementChild as Element;
  clean(root);
  return root.innerHTML;
}
