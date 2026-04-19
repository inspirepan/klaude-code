from __future__ import annotations

import html
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from markdown_it import MarkdownIt

from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import TaskMetadata, TaskMetadataItem, Usage
from klaude_code.session.session import Session

_MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table").disable("emphasis")
_PREVIEW_LIMIT = 96
_SEARCH_LIMIT = 600

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@100..900&display=swap" rel="stylesheet">
  <style>
__CSS__
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="eyebrow">Session Export</div>
        <h1>__SIDEBAR_TITLE__</h1>
        <p class="sidebar-copy">Static HTML snapshot of the current conversation.</p>
      </div>
      <label class="search-field">
        <span>Search</span>
        <input id="entry-search" type="search" placeholder="Find messages, tools, prompts...">
      </label>
      <div class="filter-row" role="tablist" aria-label="Entry filters">
        <button class="filter-btn is-active" type="button" data-filter="all">All</button>
        <button class="filter-btn" type="button" data-filter="user">User</button>
        <button class="filter-btn" type="button" data-filter="assistant">Assistant</button>
        <button class="filter-btn" type="button" data-filter="tool">Tool</button>
        <button class="filter-btn" type="button" data-filter="meta">Meta</button>
      </div>
      <div class="sidebar-status" id="entry-status"></div>
      <nav class="entry-nav" id="entry-nav">
__SIDEBAR_ITEMS__
      </nav>
    </aside>
    <main class="content">
      <section class="hero-card">
__HEADER__
      </section>
__SYSTEM_PROMPT_SECTION__
__TOOLS_SECTION__
      <section class="entries" id="entries">
__ENTRY_ITEMS__
      </section>
    </main>
  </div>
  <script>
__JS__
  </script>
</body>
</html>
"""

_CSS = """
:root {
  color-scheme: light;

  /* Zinc-tinted neutrals */
  --bg: #fafafa;
  --surface: #fff;
  --well: rgba(9, 9, 11, 0.026);
  --hover: rgba(9, 9, 11, 0.04);

  /* Text hierarchy (no pure black) */
  --text: #18181b;
  --text-2: #52525b;
  --text-3: #a1a1aa;

  /* Single desaturated accent */
  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --accent-muted: rgba(37, 99, 235, 0.06);

  /* Semantic */
  --green: #16a34a;
  --red: #dc2626;
  --amber: #ca8a04;

  /* Outer ring replaces border (Schoger #1) */
  --ring: rgba(9, 9, 11, 0.07);
  --ring-strong: rgba(9, 9, 11, 0.13);
  /* Inset ring for edge definition on light surfaces (Schoger #3) */
  --ring-inset: rgba(9, 9, 11, 0.05);

  /* Zinc-tinted shadows (not pure black) */
  --shadow-xs: 0 1px 2px rgba(9, 9, 11, 0.05);
  --shadow-sm: 0 1px 3px rgba(9, 9, 11, 0.06), 0 1px 2px -1px rgba(9, 9, 11, 0.04);
  --shadow-md: 0 4px 8px -2px rgba(9, 9, 11, 0.06), 0 2px 4px -2px rgba(9, 9, 11, 0.04);

  /* Concentric radii (Schoger #2): outer > inner > sm > xs */
  --r-outer: 8px;
  --r-inner: 6px;
  --r-sm: 5px;
  --r-xs: 3px;

  /* Typography */
  --mono: "Geist Mono", ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
  --fs-xs: 10px;
  --fs-sm: 11px;
  --fs: 13px;
  --fs-lg: 18px;
}

/* ── Reset ── */

*,
*::before,
*::after {
  box-sizing: border-box;
}

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--mono);
  font-size: var(--fs);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

a { color: inherit; }
button, input, summary { font: inherit; }
[hidden] { display: none !important; }

/* ── Layout ── */

.app-shell {
  min-height: 100dvh;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
}

/* ── Sidebar ── */

.sidebar {
  position: sticky;
  top: 0;
  height: 100dvh;
  padding: 28px 16px 16px;
  background: var(--surface);
  box-shadow: inset -1px 0 0 var(--ring);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Eyebrow: monospace, uppercase, wide tracking, small, muted (Schoger #6) */
.eyebrow {
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: var(--fs-xs);
  font-weight: 500;
  margin-bottom: 8px;
}

.sidebar h1 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -0.01em;
  word-break: break-word;
  text-wrap: balance;
}

.sidebar-copy {
  margin: 6px 0 0;
  color: var(--text-3);
  font-size: var(--fs-sm);
  line-height: 1.7;
}

.search-field {
  display: grid;
  gap: 5px;
  font-size: var(--fs-sm);
  color: var(--text-3);
}

/* Sunken input: inset ring, no border */
.search-field input {
  width: 100%;
  padding: 7px 10px;
  border: 0;
  border-radius: var(--r-sm);
  background: var(--well);
  box-shadow: inset 0 0 0 1px var(--ring-inset);
  color: var(--text);
  font-family: var(--mono);
  font-size: var(--fs);
  transition: box-shadow 200ms ease;
}

.search-field input:focus {
  outline: none;
  box-shadow: inset 0 0 0 1px var(--accent), 0 0 0 3px var(--accent-muted);
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

/* Pill buttons with outer ring (no border) */
.filter-btn {
  border: 0;
  border-radius: 999px;
  background: transparent;
  box-shadow: 0 0 0 1px var(--ring);
  color: var(--text-3);
  padding: 4px 10px;
  font-size: var(--fs-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 200ms ease;
}

.filter-btn:hover {
  color: var(--text-2);
  background: var(--hover);
}

.filter-btn.is-active {
  color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
  background: var(--accent-muted);
}

.filter-btn:active {
  transform: scale(0.97);
}

.sidebar-status {
  color: var(--text-3);
  font-size: var(--fs-sm);
}

.entry-nav {
  overflow-y: auto;
  margin-right: -4px;
  padding-right: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  text-decoration: none;
  background: transparent;
  border-radius: var(--r-sm);
  padding: 7px 10px;
  display: grid;
  gap: 3px;
  transition: background 150ms ease;
}

.nav-item:hover {
  background: var(--hover);
}

.nav-item.is-active {
  background: var(--accent-muted);
}

.nav-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-3);
  font-size: var(--fs-xs);
}

.nav-index {
  color: var(--accent);
  font-weight: 500;
}

.nav-kind {
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 500;
}

.nav-preview {
  color: var(--text-2);
  font-size: var(--fs-sm);
  line-height: 1.5;
  word-break: break-word;
  text-wrap: pretty;
}

/* ── Main content ── */

.content {
  padding: 32px clamp(20px, 4vw, 48px) 48px;
  display: grid;
  gap: 16px;
}

.content > * {
  width: min(100%, 960px);
  margin: 0 auto;
}

/* Cards: ring + tinted shadow, no border (Schoger #1) */
.hero-card,
.panel,
.entry-card {
  background: var(--surface);
  border: 0;
  border-radius: var(--r-outer);
  box-shadow: 0 0 0 1px var(--ring), var(--shadow-sm);
}

/* ── Hero ── */

.hero-card {
  padding: 24px;
  display: grid;
  gap: 16px;
}

.hero-title-row {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 16px;
}

/* Large text: tight tracking (Schoger #5) */
.hero-title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.025em;
  word-break: break-word;
  text-wrap: balance;
}

.hero-subtitle {
  margin: 4px 0 0;
  color: var(--text-2);
  font-size: var(--fs);
}

.hero-badge {
  border: 0;
  border-radius: var(--r-xs);
  padding: 5px 10px;
  color: var(--accent);
  background: var(--accent-muted);
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.15);
  white-space: nowrap;
  font-size: var(--fs-sm);
  font-weight: 500;
  letter-spacing: 0.02em;
}

.meta-grid,
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 8px;
}

/* Well containers: sunken bg + inset ring (Schoger #3, #14) */
.meta-item,
.stats-item {
  background: var(--well);
  border: 0;
  border-radius: var(--r-inner);
  box-shadow: inset 0 0 0 1px var(--ring-inset);
  padding: 12px 14px;
}

/* Labels: eyebrow formula (Schoger #6) */
.meta-label,
.stats-label {
  display: block;
  margin-bottom: 5px;
  color: var(--text-3);
  font-size: var(--fs-xs);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.meta-value,
.stats-value {
  font-size: var(--fs);
  font-weight: 500;
  line-height: 1.5;
  word-break: break-word;
}

/* ── Panel (details/summary) ── */

.panel {
  overflow: hidden;
}

.panel > summary {
  list-style: none;
  cursor: pointer;
  padding: 14px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  transition: background 150ms ease;
}

.panel > summary:hover {
  background: var(--hover);
}

.panel > summary::-webkit-details-marker {
  display: none;
}

.panel[open] > summary {
  box-shadow: inset 0 -1px 0 var(--ring-inset);
}

.panel-title {
  font-size: var(--fs);
  font-weight: 600;
}

.panel-meta {
  color: var(--text-3);
  font-size: var(--fs-sm);
}

.panel-body {
  padding: 16px 20px 20px;
}

.system-prompt {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text);
  font-size: var(--fs);
  line-height: 1.65;
}

/* ── Tool list ── */

.tool-list {
  display: grid;
  gap: 8px;
}

.tool-item {
  border: 0;
  border-radius: var(--r-inner);
  background: var(--well);
  box-shadow: inset 0 0 0 1px var(--ring-inset);
  overflow: hidden;
}

.tool-item > summary {
  list-style: none;
  cursor: pointer;
  padding: 12px 14px;
  transition: background 150ms ease;
}

.tool-item > summary:hover {
  background: var(--hover);
}

.tool-item > summary::-webkit-details-marker {
  display: none;
}

.tool-item[open] > summary {
  box-shadow: inset 0 -1px 0 var(--ring-inset);
}

.tool-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.tool-name {
  color: var(--accent);
  font-weight: 500;
}

.tool-desc {
  margin: 3px 0 0;
  color: var(--text-3);
  font-size: var(--fs-sm);
  line-height: 1.6;
}

.tool-item-body {
  padding: 14px;
  display: grid;
  gap: 12px;
}

.tool-params {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs);
}

.tool-params th,
.tool-params td {
  text-align: left;
  vertical-align: top;
  padding: 8px 6px;
  border-top: 1px solid rgba(9, 9, 11, 0.06);
}

.tool-params th {
  color: var(--text-3);
  font-size: var(--fs-xs);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.tool-param-required,
.tool-param-optional {
  display: inline-flex;
  border-radius: var(--r-xs);
  padding: 1px 6px;
  font-size: var(--fs-xs);
  font-weight: 500;
  margin-left: 6px;
}

.tool-param-required {
  background: rgba(202, 138, 4, 0.08);
  color: var(--amber);
}

.tool-param-optional {
  background: var(--hover);
  color: var(--text-3);
}

/* ── Entries ── */

.entries {
  display: grid;
  gap: 14px;
}

.entry-card {
  padding: 20px 22px;
}

.entry-card.user { background: rgba(56, 152, 236, 0.06); }
.entry-card.assistant { background: rgba(202, 138, 4, 0.06); }
.entry-card.tool { background: rgba(22, 163, 74, 0.06); }
.entry-card.meta { background: var(--well); }

.entry-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.entry-badge,
.sub-badge {
  border-radius: var(--r-xs);
  padding: 3px 8px;
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.entry-badge { background: var(--accent-muted); color: var(--accent); }
.entry-card.assistant .entry-badge { background: rgba(202, 138, 4, 0.1); color: var(--amber); }
.entry-card.tool .entry-badge { background: var(--hover); color: var(--text-2); }
.entry-card.meta .entry-badge { background: var(--hover); color: var(--text-3); }

.entry-timestamp,
.entry-anchor,
.entry-note {
  color: var(--text-3);
  font-size: var(--fs-sm);
}

.entry-anchor {
  margin-left: auto;
  text-decoration: none;
  transition: color 150ms ease;
}

.entry-anchor:hover {
  color: var(--accent);
}

.entry-body {
  display: grid;
  gap: 12px;
}

/* ── Content blocks: well containers (inset ring, sunken bg) ── */

.markdown-block,
.segment,
.json-block,
.tool-output,
.empty-state {
  border: 0;
  border-radius: var(--r-inner);
  background: var(--well);
  box-shadow: inset 0 0 0 1px var(--ring-inset);
}

.markdown-block,
.segment-content,
.json-block,
.tool-output,
.empty-state {
  padding: 14px 16px;
}

.markdown-block > :first-child,
.segment-content > :first-child {
  margin-top: 0;
}

.markdown-block > :last-child,
.segment-content > :last-child {
  margin-bottom: 0;
}

/* text-pretty avoids orphans (Schoger #7) */
.markdown-block p {
  text-wrap: pretty;
  line-height: 1.7;
}

/* Inline code: subtle bg chip */
.markdown-block code {
  background: rgba(9, 9, 11, 0.045);
  padding: 1px 5px;
  border-radius: var(--r-xs);
  font-size: 0.93em;
}

.markdown-block pre,
.segment-content pre,
.json-block,
.tool-output,
.code-block,
.system-prompt {
  overflow: auto;
}

/* Code blocks: deeper well */
.markdown-block pre,
.segment-content pre,
.tool-output,
.json-block,
.code-block {
  margin: 0;
  padding: 14px 16px;
  border-radius: var(--r-sm);
  background: rgba(9, 9, 11, 0.032);
  border: 0;
  box-shadow: inset 0 0 0 1px var(--ring-inset);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--fs);
  line-height: 1.6;
}

/* Reset inline-code style inside <pre><code> */
.markdown-block pre code {
  background: transparent;
  padding: 0;
  border-radius: 0;
  font-size: inherit;
}

.segment {
  overflow: hidden;
}

.segment > summary {
  list-style: none;
  cursor: pointer;
  padding: 10px 16px;
  color: var(--text-2);
  transition: background 150ms ease;
}

.segment > summary:hover {
  background: var(--hover);
}

.segment > summary::-webkit-details-marker {
  display: none;
}

.segment[open] > summary {
  box-shadow: inset 0 -1px 0 var(--ring-inset);
}

.segment-title {
  color: var(--text);
  font-size: var(--fs);
  font-weight: 600;
}

.segment-meta {
  margin-top: 2px;
  color: var(--text-3);
  font-size: var(--fs-sm);
}

/* ── Callouts ── */

.callout-list {
  display: grid;
  gap: 8px;
}

.callout-item {
  border: 0;
  border-radius: var(--r-sm);
  padding: 10px 14px;
  background: var(--well);
  box-shadow: inset 0 0 0 1px var(--ring-inset);
}

.callout-title {
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 4px;
}

.callout-body {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

/* ── Status pill ── */

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: var(--r-xs);
  padding: 3px 8px;
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.status-pill.success { background: rgba(22, 163, 74, 0.07); color: var(--green); }
.status-pill.error { background: rgba(220, 38, 38, 0.07); color: var(--red); }
.status-pill.aborted { background: rgba(202, 138, 4, 0.07); color: var(--amber); }

/* ── Images ── */

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.image-card {
  border: 0;
  border-radius: var(--r-inner);
  overflow: hidden;
  background: var(--well);
  box-shadow: 0 0 0 1px var(--ring), var(--shadow-xs);
}

.image-card img {
  display: block;
  width: 100%;
  max-height: 240px;
  object-fit: cover;
  background: rgba(9, 9, 11, 0.04);
}

.image-meta {
  padding: 10px 12px;
  color: var(--text-3);
  font-size: var(--fs-sm);
  line-height: 1.5;
  word-break: break-word;
}

.muted {
  color: var(--text-3);
}

.empty-state {
  padding: 24px;
  color: var(--text-3);
  text-align: center;
}

/* ── Collapse / Expand ── */

.is-collapsed {
  max-height: 240px;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(black 60%, transparent);
  mask-image: linear-gradient(black 60%, transparent);
}

/* Pill-shaped toggle (Schoger #12) */
.collapse-toggle {
  display: block;
  width: 100%;
  padding: 5px 0;
  margin-top: 6px;
  border: 0;
  border-radius: 999px;
  background: var(--well);
  box-shadow: 0 0 0 1px var(--ring);
  color: var(--text-2);
  cursor: pointer;
  font-family: var(--mono);
  font-size: var(--fs-sm);
  font-weight: 500;
  text-align: center;
  transition: all 200ms ease;
}

.collapse-toggle:hover {
  color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
  background: var(--accent-muted);
}

.collapse-toggle:active {
  transform: scale(0.98);
}

/* ── Responsive ── */

@media (max-width: 1100px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
    height: auto;
    box-shadow: inset 0 -1px 0 var(--ring);
  }
}
"""

_JS = """
(() => {
  const navItems = Array.from(document.querySelectorAll('.nav-item'));
  const entryCards = Array.from(document.querySelectorAll('.entry-card'));
  const buttons = Array.from(document.querySelectorAll('.filter-btn'));
  const search = document.getElementById('entry-search');
  const status = document.getElementById('entry-status');
  let currentFilter = 'all';

  const normalize = (value) => (value || '').toLowerCase();

  function applyFilters() {
    const query = normalize(search && search.value);
    let visibleCount = 0;

    for (const node of [...navItems, ...entryCards]) {
      const kind = normalize(node.dataset.entryKind);
      const haystack = normalize(node.dataset.search);
      const kindMatch = currentFilter === 'all' || kind === currentFilter;
      const searchMatch = !query || haystack.includes(query);
      const visible = kindMatch && searchMatch;
      node.hidden = !visible;
      if (visible && node.classList.contains('entry-card')) {
        visibleCount += 1;
      }
    }

    if (status) {
      status.textContent = `${visibleCount} visible entries`;
    }
  }

  for (const button of buttons) {
    button.addEventListener('click', () => {
      currentFilter = button.dataset.filter || 'all';
      for (const item of buttons) {
        item.classList.toggle('is-active', item === button);
      }
      applyFilters();
    });
  }

  if (search) {
    search.addEventListener('input', applyFilters);
  }

  for (const item of navItems) {
    item.addEventListener('click', () => {
      for (const navItem of navItems) {
        navItem.classList.remove('is-active');
      }
      item.classList.add('is-active');
    });
  }

  if (window.location.hash) {
    const active = document.querySelector(`.nav-item[href="${window.location.hash}"]`);
    if (active) {
      active.classList.add('is-active');
    }
  }

  applyFilters();

  const COLLAPSE_THRESHOLD = 240;
  const collapsibles = document.querySelectorAll(
    '.markdown-block, pre.tool-output, pre.json-block, pre.code-block, pre.system-prompt'
  );

  for (const el of collapsibles) {
    if (el.scrollHeight <= COLLAPSE_THRESHOLD) continue;

    el.classList.add('is-collapsed');

    const btn = document.createElement('button');
    btn.className = 'collapse-toggle';
    btn.textContent = 'Show more';
    btn.addEventListener('click', () => {
      const collapsed = el.classList.toggle('is-collapsed');
      btn.textContent = collapsed ? 'Show more' : 'Show less';
    });
    el.after(btn);
  }
})();
"""


@dataclass(slots=True)
class _EntryView:
    anchor: str
    kind: str
    label: str
    timestamp: str
    preview: str
    search_text: str
    body_html: str


def render_session_export_html(
    session: Session,
    *,
    system_prompt: str | None,
    tools: Sequence[llm_param.ToolSchema] | None,
) -> str:
    entries = [
        v
        for index, item in enumerate(session.conversation_history, start=1)
        if (v := _render_entry_view(index, item, session.work_dir)) is not None
    ]
    title = session.title or f"Session {session.id[:8]}"
    header = _render_header(session, system_prompt=system_prompt, tools=tools)
    system_prompt_section = _render_system_prompt_section(system_prompt)
    tools_section = _render_tools_section(tools or [])
    sidebar_items = _render_sidebar(entries)
    entry_items = _render_entry_list(entries)
    page_title = html.escape(f"{title} - klaude session export")
    return (
        _HTML_TEMPLATE.replace("__TITLE__", page_title)
        .replace("__SIDEBAR_TITLE__", html.escape(title))
        .replace("__CSS__", _CSS)
        .replace("__HEADER__", header)
        .replace("__SYSTEM_PROMPT_SECTION__", system_prompt_section)
        .replace("__TOOLS_SECTION__", tools_section)
        .replace("__SIDEBAR_ITEMS__", sidebar_items)
        .replace("__ENTRY_ITEMS__", entry_items)
        .replace("__JS__", _JS)
    )


def _render_header(
    session: Session,
    *,
    system_prompt: str | None,
    tools: Sequence[llm_param.ToolSchema] | None,
) -> str:
    assistant_usage = Usage()
    has_usage = False
    counts = {"user": 0, "assistant": 0, "tool": 0, "meta": 0, "tool_calls": 0}

    for item in session.conversation_history:
        if isinstance(item, message.UserMessage):
            counts["user"] += 1
        elif isinstance(item, message.AssistantMessage):
            counts["assistant"] += 1
            counts["tool_calls"] += sum(1 for part in item.parts if isinstance(part, message.ToolCallPart))
            if item.usage is not None:
                has_usage = True
                TaskMetadata.merge_usage(assistant_usage, item.usage)
        elif isinstance(item, message.ToolResultMessage):
            counts["tool"] += 1
        else:
            counts["meta"] += 1

    subtitle = f"{session.work_dir}"
    prompt_line_count = len(system_prompt.splitlines()) if system_prompt else 0
    prompt_value = f"{prompt_line_count} lines" if prompt_line_count else "none"
    tool_value = str(len(tools or []))

    meta_items = [
        ("Session ID", session.id),
        ("Work Dir", str(session.work_dir)),
        ("Created", _format_timestamp_value(session.created_at)),
        ("Updated", _format_timestamp_value(session.updated_at)),
        ("Model", session.model_name or "unknown"),
        ("System Prompt", prompt_value),
        ("Tools", tool_value),
    ]
    stats_items = [
        ("User Messages", str(counts["user"])),
        ("Assistant Messages", str(counts["assistant"])),
        ("Tool Calls", str(counts["tool_calls"])),
        ("Tool Results", str(counts["tool"])),
        ("Meta Events", str(counts["meta"])),
    ]
    if has_usage:
        stats_items.extend(
            [
                ("Input Tokens", _format_number(assistant_usage.input_tokens)),
                ("Output Tokens", _format_number(assistant_usage.output_tokens)),
                ("Cached Tokens", _format_number(assistant_usage.cached_tokens)),
            ]
        )
        if assistant_usage.total_cost is not None:
            currency = assistant_usage.currency or "USD"
            stats_items.append(("Total Cost", f"{assistant_usage.total_cost:.4f} {currency}"))

    meta_html = "".join(
        f'<div class="meta-item"><span class="meta-label">{html.escape(label)}</span><div class="meta-value">{html.escape(value)}</div></div>'
        for label, value in meta_items
    )
    stats_html = "".join(
        f'<div class="stats-item"><span class="stats-label">{html.escape(label)}</span><div class="stats-value">{html.escape(value)}</div></div>'
        for label, value in stats_items
    )

    return "".join(
        [
            '<div class="hero-title-row">',
            "<div>",
            f'<h2 class="hero-title">{html.escape(session.title or "Untitled Session")}</h2>',
            f'<p class="hero-subtitle">{html.escape(subtitle)}</p>',
            "</div>",
            f'<div class="hero-badge">{html.escape(session.id[:8])}</div>',
            "</div>",
            f'<div class="meta-grid">{meta_html}</div>',
            f'<div class="stats-grid">{stats_html}</div>',
        ]
    )


def _render_system_prompt_section(system_prompt: str | None) -> str:
    if not system_prompt:
        return ""
    line_count = len(system_prompt.splitlines())
    return "".join(
        [
            '<details class="panel" open>',
            "<summary>",
            '<span class="panel-title">System Prompt</span>',
            f'<span class="panel-meta">{line_count} lines</span>',
            "</summary>",
            '<div class="panel-body">',
            f'<pre class="system-prompt">{html.escape(system_prompt)}</pre>',
            "</div>",
            "</details>",
        ]
    )


def _render_tools_section(tools: Sequence[llm_param.ToolSchema]) -> str:
    if not tools:
        return ""
    tool_items = "".join(_render_tool_item(tool) for tool in tools)
    return "".join(
        [
            '<details class="panel">',
            "<summary>",
            '<span class="panel-title">Available Tools</span>',
            f'<span class="panel-meta">{len(tools)} registered</span>',
            "</summary>",
            f'<div class="panel-body"><div class="tool-list">{tool_items}</div></div>',
            "</details>",
        ]
    )


def _render_tool_item(tool: llm_param.ToolSchema) -> str:
    body_parts: list[str] = []

    properties = _json_object_value(tool.parameters, "properties")
    required_values = _json_array_value(tool.parameters, "required")
    required_names = {value for value in required_values if isinstance(value, str)}
    if properties:
        rows: list[str] = []
        for raw_name, raw_schema in properties.items():
            if not isinstance(raw_schema, dict):
                continue
            schema_dict = cast(dict[str, object], raw_schema)
            param_type = _schema_type_label(schema_dict)
            description = schema_dict.get("description")
            if not isinstance(description, str):
                description = ""
            required_badge = (
                '<span class="tool-param-required">required</span>'
                if raw_name in required_names
                else '<span class="tool-param-optional">optional</span>'
            )
            rows.append(
                "".join(
                    [
                        "<tr>",
                        f"<td><code>{html.escape(raw_name)}</code>{required_badge}</td>",
                        f"<td>{html.escape(param_type)}</td>",
                        f"<td>{html.escape(description)}</td>",
                        "</tr>",
                    ]
                )
            )
        if rows:
            body_parts.append(
                "".join(
                    [
                        '<table class="tool-params">',
                        "<thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>",
                        f"<tbody>{''.join(rows)}</tbody>",
                        "</table>",
                    ]
                )
            )
    body_parts.append(f'<pre class="json-block">{html.escape(_json_dump(tool.parameters))}</pre>')

    param_count = len(properties) if properties else 0
    return "".join(
        [
            '<details class="tool-item">',
            "<summary>",
            '<div class="tool-header">',
            f'<span class="tool-name">{html.escape(tool.name)}</span>',
            f'<span class="muted">{param_count} params</span>',
            "</div>",
            f'<p class="tool-desc">{html.escape(tool.description)}</p>' if tool.description else "",
            "</summary>",
            f'<div class="tool-item-body">{"".join(body_parts)}</div>',
            "</details>",
        ]
    )


def _render_sidebar(entries: Sequence[_EntryView]) -> str:
    if not entries:
        return '<div class="empty-state">No conversation history yet.</div>'
    return "".join(
        "".join(
            [
                f'<a class="nav-item" href="#{entry.anchor}" data-entry-kind="{entry.kind}" data-search="{html.escape(entry.search_text, quote=True)}">',
                '<div class="nav-meta">',
                f'<span class="nav-index">#{entry.anchor.split("-")[-1]}</span>',
                f'<span class="nav-kind">{html.escape(entry.label)}</span>',
                f"<span>{html.escape(entry.timestamp.split(' ')[-1])}</span>",
                "</div>",
                f'<div class="nav-preview">{html.escape(entry.preview)}</div>',
                "</a>",
            ]
        )
        for entry in entries
    )


def _render_entry_list(entries: Sequence[_EntryView]) -> str:
    if not entries:
        return '<div class="empty-state">Nothing to export yet. Start a conversation first.</div>'
    return "".join(
        "".join(
            [
                f'<article id="{entry.anchor}" class="entry-card {entry.kind}" data-entry-kind="{entry.kind}" data-search="{html.escape(entry.search_text, quote=True)}">',
                '<div class="entry-header">',
                f'<span class="entry-badge">{html.escape(entry.label)}</span>',
                f'<span class="entry-timestamp">{html.escape(entry.timestamp)}</span>',
                f'<a class="entry-anchor" href="#{entry.anchor}">#{entry.anchor.split("-")[-1]}</a>',
                "</div>",
                f'<div class="entry-body">{entry.body_html}</div>',
                "</article>",
            ]
        )
        for entry in entries
    )


def _render_entry_view(index: int, item: message.HistoryEvent, work_dir: Path) -> _EntryView | None:
    if isinstance(item, message.CacheHitRateEntry):
        return None

    anchor = f"entry-{index}"
    timestamp = _history_event_timestamp(item)

    if isinstance(item, message.UserMessage):
        preview = _message_preview(item.parts, fallback="(user message)")
        search = _entry_search_text("user", preview, item)
        return _EntryView(
            anchor=anchor,
            kind="user",
            label="User",
            timestamp=timestamp,
            preview=preview,
            search_text=search,
            body_html=_render_parts(item.parts, work_dir=work_dir, allow_thinking=False),
        )

    if isinstance(item, message.AssistantMessage):
        preview = _assistant_preview(item)
        search = _entry_search_text("assistant", preview, item)
        note_parts = [part for part in [item.phase, item.stop_reason, _usage_summary(item.usage)] if part]
        note_html = (
            f'<span class="entry-note">{" | ".join(html.escape(part) for part in note_parts)}</span>'
            if note_parts
            else ""
        )
        body_html = note_html + _render_parts(item.parts, work_dir=work_dir, allow_thinking=True)
        return _EntryView(
            anchor=anchor,
            kind="assistant",
            label="Assistant",
            timestamp=timestamp,
            preview=preview,
            search_text=search,
            body_html=body_html,
        )

    if isinstance(item, message.ToolResultMessage):
        preview = _text_preview(item.output_text, fallback=f"{item.tool_name} result")
        search = _entry_search_text(item.tool_name, preview, item)
        body_parts: list[str] = []
        if item.status != "success":
            body_parts.append(f'<div class="status-pill {html.escape(item.status)}">{html.escape(item.status)}</div>')
        if item.output_text:
            body_parts.append(f'<pre class="tool-output">{html.escape(item.output_text)}</pre>')
        if item.parts:
            body_parts.append(_render_non_text_parts(item.parts, work_dir=work_dir))
        return _EntryView(
            anchor=anchor,
            kind="tool",
            label=f"Tool: {item.tool_name}",
            timestamp=timestamp,
            preview=preview,
            search_text=search,
            body_html="".join(body_parts) or '<div class="empty-state">No output.</div>',
        )

    if isinstance(item, message.DeveloperMessage):
        if not item.parts:
            return None
        preview = _message_preview(item.parts, fallback="(developer message)")
        search = _entry_search_text("developer", preview, item)
        return _EntryView(
            anchor=anchor,
            kind="meta",
            label="Developer",
            timestamp=timestamp,
            preview=preview,
            search_text=search,
            body_html=_render_parts(item.parts, work_dir=work_dir, allow_thinking=False),
        )

    if isinstance(item, message.SystemMessage):
        preview = _message_preview(item.parts, fallback="(system message)")
        search = _entry_search_text("system", preview, item)
        return _EntryView(
            anchor=anchor,
            kind="meta",
            label="System",
            timestamp=timestamp,
            preview=preview,
            search_text=search,
            body_html=_render_parts(item.parts, work_dir=work_dir, allow_thinking=False),
        )

    preview, title = _meta_preview_and_title(item)
    search = _entry_search_text(title, preview, item)
    return _EntryView(
        anchor=anchor,
        kind="meta",
        label=title,
        timestamp=timestamp,
        preview=preview,
        search_text=search,
        body_html=f'<pre class="json-block">{html.escape(_json_dump(item.model_dump(mode="json")))}</pre>',
    )


def _render_parts(parts: Sequence[message.Part], *, work_dir: Path, allow_thinking: bool) -> str:
    blocks: list[str] = []
    text_buffer: list[str] = []
    thinking_buffer: list[str] = []

    def flush_text() -> None:
        if not text_buffer:
            return
        blocks.append(_markdown_block("".join(text_buffer)))
        text_buffer.clear()

    def flush_thinking() -> None:
        if not thinking_buffer:
            return
        blocks.append(
            _details_block(
                title="Thinking",
                meta=f"{len(thinking_buffer)} part(s)",
                body=f'<pre class="tool-output">{html.escape("".join(thinking_buffer))}</pre>',
            )
        )
        thinking_buffer.clear()

    for part in parts:
        if isinstance(part, message.TextPart):
            flush_thinking()
            text_buffer.append(part.text)
            continue
        if isinstance(part, message.ThinkingTextPart) and allow_thinking:
            flush_text()
            thinking_buffer.append(part.text)
            continue
        if isinstance(part, message.ThinkingSignaturePart) and allow_thinking:
            flush_text()
            thinking_buffer.append(f"\n[signature] {part.signature}")
            continue
        flush_text()
        flush_thinking()
        if isinstance(part, message.ToolCallPart):
            blocks.append(
                _details_block(
                    title=f"Tool Call - {part.tool_name}",
                    meta=part.call_id,
                    body=f'<pre class="tool-output">{html.escape(_pretty_json_text(part.arguments_json))}</pre>',
                )
            )
            continue
        blocks.append(_render_non_text_parts([part], work_dir=work_dir))

    flush_text()
    flush_thinking()
    return "".join(blocks) or '<div class="empty-state">No renderable content.</div>'


def _render_non_text_parts(parts: Sequence[message.Part], *, work_dir: Path) -> str:
    image_blocks: list[str] = []
    other_blocks: list[str] = []
    for part in parts:
        if isinstance(part, message.ImageURLPart):
            if part.url.startswith("data:"):
                label = part.url.split(";")[0].removeprefix("data:") or "embedded image"
            else:
                label = part.url
            image_blocks.append(_image_card(label, part.url, source_label="remote image"))
        elif isinstance(part, message.ImageFilePart):
            image_path = Path(part.file_path)
            if not image_path.is_absolute():
                image_path = work_dir / image_path
            source = image_path.resolve().as_uri() if image_path.exists() else None
            image_blocks.append(_image_card(str(image_path), source, source_label=part.mime_type or "local image"))
        elif isinstance(part, message.ThinkingTextPart):
            other_blocks.append(f'<pre class="tool-output">{html.escape(part.text)}</pre>')
        elif isinstance(part, message.ThinkingSignaturePart):
            other_blocks.append(f'<pre class="tool-output">{html.escape(part.signature)}</pre>')
        elif isinstance(part, message.ToolCallPart):
            other_blocks.append(f'<pre class="tool-output">{html.escape(_pretty_json_text(part.arguments_json))}</pre>')
    blocks: list[str] = []
    if image_blocks:
        blocks.append(f'<div class="image-grid">{"".join(image_blocks)}</div>')
    blocks.extend(other_blocks)
    return "".join(blocks) or '<div class="empty-state">No non-text content.</div>'


def _image_card(label: str, source: str | None, *, source_label: str) -> str:
    image_html = f'<img src="{html.escape(source, quote=True)}" alt="{html.escape(label)}">' if source else ""
    return "".join(
        [
            '<div class="image-card">',
            image_html,
            '<div class="image-meta">',
            f"<div>{html.escape(source_label)}</div>",
            f"<div>{html.escape(label)}</div>",
            "</div>",
            "</div>",
        ]
    )


def _details_block(*, title: str, meta: str | None, body: str, open_by_default: bool = False) -> str:
    open_attr = " open" if open_by_default else ""
    meta_html = f'<div class="segment-meta">{html.escape(meta)}</div>' if meta else ""
    return "".join(
        [
            f'<details class="segment"{open_attr}>',
            "<summary>",
            f'<div class="segment-title">{html.escape(title)}</div>',
            meta_html,
            "</summary>",
            f'<div class="segment-content">{body}</div>',
            "</details>",
        ]
    )


def _markdown_block(text: str) -> str:
    content = text.strip()
    if not content:
        return ""
    rendered = _MARKDOWN.render(content)
    return f'<div class="markdown-block">{rendered}</div>'


def _assistant_preview(item: message.AssistantMessage) -> str:
    text = _message_preview(item.parts)
    if text:
        return text
    first_tool = next((part.tool_name for part in item.parts if isinstance(part, message.ToolCallPart)), None)
    if first_tool:
        return f"Tool call: {first_tool}"
    if any(isinstance(part, message.ThinkingTextPart) for part in item.parts):
        return "(thinking only)"
    return "(assistant message)"


def _message_preview(parts: Sequence[message.Part], fallback: str = "") -> str:
    text = "".join(part.text for part in parts if isinstance(part, message.TextPart))
    preview = _text_preview(text)
    if preview:
        return preview
    if any(isinstance(part, (message.ImageFilePart, message.ImageURLPart)) for part in parts):
        return "(image content)"
    return fallback


def _meta_preview_and_title(item: message.HistoryEvent) -> tuple[str, str]:
    if isinstance(item, message.CompactionEntry):
        return _text_preview(item.summary, fallback="Compaction summary"), "Compaction"
    if isinstance(item, message.RewindEntry):
        return _text_preview(item.note, fallback=f"Checkpoint {item.checkpoint_id}"), "Rewind"
    if isinstance(item, message.InterruptEntry):
        return "Turn interrupted", "Interrupt"
    if isinstance(item, message.CacheHitRateEntry):
        return f"Cache hit rate {item.cache_hit_rate:.1%}", "Cache"
    if isinstance(item, message.SpawnSubAgentEntry):
        return _text_preview(item.sub_agent_desc, fallback=item.sub_agent_type), "Sub Agent"
    if isinstance(item, TaskMetadataItem):
        model_name = item.main_agent.model_name or "task metadata"
        return model_name, "Task"
    if isinstance(item, message.StreamErrorItem):
        return _text_preview(item.error, fallback="stream error"), "Error"
    return _text_preview(_json_dump(item.model_dump(mode="json")), fallback="meta event"), item.__class__.__name__


def _entry_search_text(prefix: str, preview: str, item: message.HistoryEvent) -> str:
    base = f"{prefix} {preview} {_json_dump(item.model_dump(mode='json'))}"
    return _text_preview(base, limit=_SEARCH_LIMIT, fallback=prefix)


def _history_event_timestamp(item: message.HistoryEvent) -> str:
    created_at = getattr(item, "created_at", None)
    if isinstance(created_at, datetime):
        return _format_datetime(created_at)
    return "unknown time"


def _format_timestamp_value(value: float | None) -> str:
    if value is None or value <= 0:
        return "unknown"
    return _format_datetime(datetime.fromtimestamp(value))


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _usage_summary(usage: Usage | None) -> str | None:
    if usage is None:
        return None
    parts: list[str] = []
    if usage.input_tokens:
        parts.append(f"in {usage.input_tokens}")
    if usage.output_tokens:
        parts.append(f"out {usage.output_tokens}")
    if usage.cached_tokens:
        parts.append(f"cached {usage.cached_tokens}")
    if usage.total_cost is not None:
        parts.append(f"cost {usage.total_cost:.4f} {usage.currency}")
    return ", ".join(parts) if parts else None


def _format_number(value: int) -> str:
    return f"{value:,}"


def _text_preview(text: str, *, limit: int = _PREVIEW_LIMIT, fallback: str = "") -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return fallback
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "..."


def _pretty_json_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return _json_dump(parsed)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _json_object_value(schema: object, key: str) -> dict[str, object]:
    if not isinstance(schema, dict):
        return {}
    schema_dict = cast(dict[str, object], schema)
    value = schema_dict.get(key)
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _json_array_value(schema: object, key: str) -> list[object]:
    if not isinstance(schema, dict):
        return []
    schema_dict = cast(dict[str, object], schema)
    value = schema_dict.get(key)
    if not isinstance(value, list):
        return []
    return cast(list[object], value)


def _schema_type_label(schema: dict[str, object]) -> str:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        return " | ".join(str(value) for value in cast(list[object], raw_type))
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return "enum"
    return "any"
