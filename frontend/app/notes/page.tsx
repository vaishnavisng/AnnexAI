"use client";

import { useEffect, useRef, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import VideoBackground from "@/components/VideoBackground";
import PageTransition from "@/components/PageTransition";
import { fetchNotes, getDownloadUrl, type SummaryData } from "@/lib/api";
import { renderRichText, enhanceCodeBlocks } from "@/lib/richtext";

interface TocEntry {
  id: string;
  text: string;
  depth: number;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

function NotesContent() {
  const searchParams = useSearchParams();
  const lectureId = searchParams.get("lecture_id") ?? "";

  const [data, setData] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [toc, setToc] = useState<TocEntry[]>([]);
  const [activeId, setActiveId] = useState("");
  const [showTop, setShowTop] = useState(false);

  const contentRef = useRef<HTMLElement>(null);
  const shellRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!lectureId) return;
    let cancelled = false;
    setLoading(true);
    fetchNotes(lectureId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lectureId]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root || !data?.content) return;

    root.innerHTML = renderRichText(data.content);
    enhanceCodeBlocks(root);

    const headings = Array.from(root.querySelectorAll<HTMLElement>("h2, h3, h4"));
    const usedIds = new Set<string>();
    const entries: TocEntry[] = [];

    headings.forEach((h, i) => {
      const base = h.id || slugify(h.textContent ?? "") || `section-${i + 1}`;
      let id = base;
      let serial = 2;
      while (usedIds.has(id)) {
        id = `${base}-${serial}`;
        serial++;
      }
      usedIds.add(id);
      h.id = id;

      entries.push({
        id,
        text: h.textContent || `Section ${i + 1}`,
        depth: Number(h.tagName.replace("H", "")) || 2,
      });
    });

    setToc(entries.length >= 2 ? entries : []);
  }, [data]);

  const handleScroll = useCallback(() => {
    const container = shellRef.current;
    if (!container) return;

    const y = container.scrollTop;
    setShowTop(y > 260);

    const root = contentRef.current;
    if (!root) return;
    const headings = Array.from(root.querySelectorAll<HTMLElement>("h2, h3, h4"));
    const containerTop = container.getBoundingClientRect().top;
    let current = headings[0]?.id ?? "";

    for (const h of headings) {
      if (h.getBoundingClientRect().top - containerTop <= 140) current = h.id;
    }
    setActiveId(current);
  }, []);

  useEffect(() => {
    const container = shellRef.current;
    if (!container) return;
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  useEffect(() => {
    document.body.className = "landing qa docs";
    return () => {
      document.body.className = "";
    };
  }, []);

  const scrollToHeading = (id: string) => {
    const el = document.getElementById(id);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const scrollToTop = () => {
    shellRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const q = (key: string) => `lecture_id=${encodeURIComponent(key)}`;

  return (
    <>
      <VideoBackground />
      <PageTransition label="Generating notes..." />

      <main ref={shellRef} className="chat-shell notes-shell docs-shell">
        <header className="chat-header">
          <div className="chat-title">{data?.title ?? "CognifyAI"}</div>
          <div className="chat-meta">
            <Link className="pill" href="/library">Library</Link>
            <Link className="pill" href={`/flashcards?${q(lectureId)}`}>Flashcards</Link>
            <Link className="pill" href={`/summary?${q(lectureId)}`}>Summary</Link>
            <Link className="pill" href={`/qa?${q(lectureId)}`}>Q&amp;A</Link>
            <Link className="pill" href={`/quiz?${q(lectureId)}`}>Quiz</Link>
            <Link className="pill" href="/">Change lecture</Link>
          </div>
        </header>

        <section className="doc-toolbar">
          <div className="doc-title-group">
            <p className="doc-kicker">Deep study view</p>
            <h2 className="doc-heading">Detailed Notes</h2>
            <p className="doc-intro">
              Structured notes focused on definitions, insights, and exam prep.
            </p>
          </div>
          <div className="doc-actions">
            <a
              className="pill pill-primary"
              href={getDownloadUrl("notes", lectureId)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Download PDF
            </a>
          </div>
        </section>

        <section className="doc-layout">
          {toc.length > 0 && (
            <aside className="doc-toc" aria-label="Table of contents">
              <p className="doc-toc-title">On this page</p>
              <nav>
                <ul className="doc-toc-list">
                  {toc.map((entry) => (
                    <li key={entry.id}>
                      <a
                        className={`doc-toc-item depth-${entry.depth}${activeId === entry.id ? " is-active" : ""}`}
                        href={`#${entry.id}`}
                        onClick={(e) => {
                          e.preventDefault();
                          scrollToHeading(entry.id);
                        }}
                      >
                        {entry.text}
                      </a>
                    </li>
                  ))}
                </ul>
              </nav>
            </aside>
          )}

          <div className="doc-content-area">
            <section className="doc-view">
              <article ref={contentRef} className="doc-rich">
                {loading && (
                  <div className="doc-skeleton" aria-hidden="true">
                    <span className="skeleton-heading sk-xl" />
                    <div className="doc-skeleton-paragraph">
                      <span className="skeleton-line sk-md sk-w-95" />
                      <span className="skeleton-line sk-md sk-w-85" />
                      <span className="skeleton-line sk-md sk-w-70" />
                    </div>
                    <span className="skeleton-heading" />
                    <div className="doc-skeleton-paragraph">
                      <span className="skeleton-line sk-md sk-w-95" />
                      <span className="skeleton-line sk-md sk-w-95" />
                      <span className="skeleton-line sk-md sk-w-60" />
                    </div>
                    <ul className="doc-skeleton-list">
                      <li><span className="skeleton-line sk-md sk-w-85" /></li>
                      <li><span className="skeleton-line sk-md sk-w-70" /></li>
                      <li><span className="skeleton-line sk-md sk-w-95" /></li>
                    </ul>
                    <span className="skeleton-heading" />
                    <div className="doc-skeleton-paragraph">
                      <span className="skeleton-line sk-md sk-w-95" />
                      <span className="skeleton-line sk-md sk-w-85" />
                      <span className="skeleton-line sk-md sk-w-50" />
                    </div>
                  </div>
                )}
              </article>
            </section>
          </div>
        </section>
      </main>

      <button
        className={`back-to-top-btn${showTop ? " is-visible" : ""}`}
        type="button"
        aria-label="Back to top"
        onClick={scrollToTop}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 19V5" />
          <path d="M18 11l-6-6-6 6" />
        </svg>
      </button>
    </>
  );
}

export default function NotesPage() {
  return (
    <Suspense>
      <NotesContent />
    </Suspense>
  );
}
