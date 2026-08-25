"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import VideoBackground from "@/components/VideoBackground";
import PageTransition from "@/components/PageTransition";
import {
  fetchFlashcards,
  reviewFlashcard,
  regenerateFlashcards,
  type FlashcardsData,
} from "@/lib/api";

function FlashcardsContent() {
  const searchParams = useSearchParams();
  const lectureId = searchParams.get("lecture_id") || "";

  const [data, setData] = useState<FlashcardsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setRevealed(false);
    try {
      const result = await fetchFlashcards(lectureId || undefined);
      if (result.error) setError(result.error);
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load flashcards");
    } finally {
      setLoading(false);
    }
  }, [lectureId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRating = async (rating: string) => {
    if (!data?.current_card || reviewing) return;
    setReviewing(true);
    try {
      await reviewFlashcard(lectureId, data.current_card.card_id, rating);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Review failed");
    } finally {
      setReviewing(false);
    }
  };

  const handleRegenerate = async () => {
    if (regenerating) return;
    setRegenerating(true);
    try {
      await regenerateFlashcards(lectureId);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Regeneration failed");
    } finally {
      setRegenerating(false);
    }
  };

  const lectureMeta = data?.lecture_meta || {};
  const lectureSummary = data?.lecture_summary || {};
  const coaching = data?.coaching || {};

  return (
    <main className="chat-shell notes-shell docs-shell flashcards-shell">
      <header className="chat-header">
        <div className="chat-title">
          {lectureId ? "Lecture Flashcards" : "Due Today Review"}
        </div>
        <div className="chat-meta">
          <Link className={`pill${!lectureId ? " is-active" : ""}`} href="/library">
            Library
          </Link>
          {lectureId && (
            <>
              <Link
                className="pill"
                href={`/qa?lecture_id=${encodeURIComponent(lectureId)}&src_url=${encodeURIComponent(lectureMeta.source_url || "")}`}
              >
                Q&amp;A
              </Link>
              <Link
                className="pill"
                href={`/quiz?lecture_id=${encodeURIComponent(lectureId)}`}
              >
                Quiz
              </Link>
              {lectureMeta.has_notes && (
                <Link
                  className="pill"
                  href={`/notes?lecture_id=${encodeURIComponent(lectureId)}`}
                >
                  Notes
                </Link>
              )}
            </>
          )}
          <Link className="pill" href="/">
            Process Lecture
          </Link>
        </div>
      </header>

      {error && (
        <div className="flash-stack">
          <div className="flash flash-error">{error}</div>
        </div>
      )}

      {loading ? (
        <section className="chat-empty">Loading flashcards…</section>
      ) : !lectureId ? (
        /* ── Mode 1: Due Today overview ── */
        <>
          <section className="flashcards-overview">
            <div>
              <p className="doc-kicker">Grouped by lecture</p>
              <h2 className="doc-heading">
                Work through today&apos;s due cards one lecture block at a time
              </h2>
              <p className="doc-intro">
                Start a lecture block, clear the due stack, then return to the
                dashboard for the next study decision.
              </p>
            </div>
            <div className="library-stats-grid flashcards-stats-grid">
              <article className="library-stat-card">
                <span className="library-stat-label">Due Today</span>
                <strong className="library-stat-value">
                  {data?.dashboard?.stats?.due_today ?? 0}
                </strong>
              </article>
              <article className="library-stat-card">
                <span className="library-stat-label">Overdue</span>
                <strong className="library-stat-value">
                  {data?.dashboard?.stats?.overdue ?? 0}
                </strong>
              </article>
            </div>
          </section>

          {data?.due_groups?.length ? (
            <section className="flashcards-groups">
              {data.due_groups.map((lecture: any) => (
                <article key={lecture.lecture_id} className="flashcard-group-card">
                  <div className="flashcard-group-head">
                    <div>
                      <h3>{lecture.title || lecture.lecture_id}</h3>
                      <p>{lecture.source_label || lecture.lecture_id}</p>
                    </div>
                    <div className="library-chip-row">
                      {!!lecture.overdue_count && (
                        <span className="pill pill-danger">
                          {lecture.overdue_count} overdue
                        </span>
                      )}
                      {!!lecture.due_today_count && (
                        <span className="pill pill-warn">
                          {lecture.due_today_count} due today
                        </span>
                      )}
                    </div>
                  </div>

                  {lecture.weak_concepts?.length > 0 && (
                    <div className="library-chip-row">
                      {lecture.weak_concepts.slice(0, 3).map((c: any, i: number) => (
                        <span key={i} className="pill pill-muted">
                          {c.label}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="library-card-actions">
                    <Link
                      className="pill pill-primary"
                      href={`/flashcards?lecture_id=${encodeURIComponent(lecture.lecture_id)}`}
                    >
                      Start Lecture Block
                    </Link>
                    <Link
                      className="pill"
                      href={`/qa?lecture_id=${encodeURIComponent(lecture.lecture_id)}&src_url=${encodeURIComponent(lecture.source_url || "")}`}
                    >
                      Q&amp;A
                    </Link>
                    <Link
                      className="pill"
                      href={`/quiz?lecture_id=${encodeURIComponent(lecture.lecture_id)}`}
                    >
                      Quiz
                    </Link>
                  </div>
                </article>
              ))}
            </section>
          ) : (
            <>
              <section className="chat-empty">
                No flashcards are due right now. Return to the library to open a
                lecture, generate a deck, or review your next weak concept.
              </section>
              <div className="quiz-actions-inline">
                <Link className="pill pill-primary" href="/library">
                  Back to Library
                </Link>
              </div>
            </>
          )}
        </>
      ) : (
        /* ── Mode 2: Lecture flashcard review ── */
        <>
          <section className="flashcards-overview">
            <div>
              <p className="doc-kicker">
                {lectureMeta.title || lectureId}
              </p>
              <h2 className="doc-heading">
                Review one card, rate it, and keep the lecture block moving
              </h2>
              <p className="doc-intro">
                Cards are spaced locally on this machine. Finishing this
                lecture&apos;s due cards returns you to the library dashboard.
              </p>
            </div>
            <div className="library-chip-row">
              <span className="pill pill-muted">
                Deck: {lectureSummary.card_count ?? 0}
              </span>
              <span className="pill pill-warn">
                Due: {lectureSummary.due_today_count ?? 0}
              </span>
              {!!lectureSummary.overdue_count && (
                <span className="pill pill-danger">
                  Overdue: {lectureSummary.overdue_count}
                </span>
              )}
            </div>
          </section>

          {data?.current_card ? (
            <section className="flashcard-review-layout">
              <article className="flashcard-review-card">
                <div className="flashcard-card-shell">
                  <p className="doc-kicker">{data.current_card.concept}</p>
                  <h3>{data.current_card.front}</h3>
                  {data.current_card.hint && (
                    <p className="flashcard-hint">
                      Hint: {data.current_card.hint}
                    </p>
                  )}

                  {!revealed ? (
                    <button
                      className="pill pill-primary"
                      type="button"
                      onClick={() => setRevealed(true)}
                    >
                      Reveal Answer
                    </button>
                  ) : (
                    <div className="flashcard-answer">
                      <p>{data.current_card.back}</p>
                      {data.current_card.source_segments?.length > 0 && (
                        <div className="library-chip-row">
                          {data.current_card.source_segments.map(
                            (seg: any, i: number) => (
                              <span key={i} className="pill pill-muted">
                                {Math.floor(seg.start)}s–{Math.floor(seg.end)}s
                              </span>
                            )
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {revealed && (
                  <div className="flashcard-rating-form">
                    <button
                      className="pill pill-danger"
                      type="button"
                      disabled={reviewing}
                      onClick={() => handleRating("again")}
                    >
                      Again
                    </button>
                    <button
                      className="pill pill-warn"
                      type="button"
                      disabled={reviewing}
                      onClick={() => handleRating("hard")}
                    >
                      Hard
                    </button>
                    <button
                      className="pill pill-success"
                      type="button"
                      disabled={reviewing}
                      onClick={() => handleRating("good")}
                    >
                      Good
                    </button>
                    <button
                      className="pill pill-primary"
                      type="button"
                      disabled={reviewing}
                      onClick={() => handleRating("easy")}
                    >
                      Easy
                    </button>
                  </div>
                )}
              </article>

              <aside className="flashcard-side-panel">
                <section className="flashcard-side-card">
                  <p className="doc-kicker">Queue</p>
                  <h3>Up next in this lecture</h3>
                  {data.queue_cards?.length ? (
                    <div className="flashcard-mini-list">
                      {data.queue_cards.map((card: any, i: number) => (
                        <article key={i} className="flashcard-mini-item">
                          <strong>{card.concept}</strong>
                          <span>{card.front}</span>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="doc-intro">
                      This is the last due card in the current lecture block.
                    </p>
                  )}
                </section>

                {coaching.recommendations?.length > 0 && (
                  <section className="flashcard-side-card">
                    <p className="doc-kicker">Weakness-Aware Coaching</p>
                    <h3>Focus areas from recent quiz attempts</h3>
                    <div className="flashcard-mini-list">
                      {coaching.recommendations
                        .slice(0, 2)
                        .map((item: any, i: number) => (
                          <article key={i} className="flashcard-mini-item">
                            <strong>{item.concept}</strong>
                            <span>
                              {item.actions?.[0] || "Review this concept again."}
                            </span>
                          </article>
                        ))}
                    </div>
                  </section>
                )}

                <section className="flashcard-side-card">
                  <p className="doc-kicker">Deck Actions</p>
                  <div className="library-card-actions">
                    <button
                      className="pill"
                      type="button"
                      disabled={regenerating}
                      onClick={handleRegenerate}
                    >
                      {regenerating ? "Regenerating…" : "Regenerate Deck"}
                    </button>
                    <Link className="pill" href="/library">
                      Back to Library
                    </Link>
                  </div>
                </section>
              </aside>
            </section>
          ) : (
            <section className="flashcard-complete-card">
              <p className="doc-kicker">Lecture Block Complete</p>
              <h2 className="doc-heading">
                No due cards remain for this lecture right now
              </h2>
              <p className="doc-intro">
                You can return to the library, open another lecture block, or
                regenerate this deck if you want a fresh pass later.
              </p>
              <div className="library-card-actions">
                <Link className="pill pill-primary" href="/library">
                  Return to Library
                </Link>
                <button
                  className="pill"
                  type="button"
                  disabled={regenerating}
                  onClick={handleRegenerate}
                >
                  {regenerating ? "Regenerating…" : "Regenerate Deck"}
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}

export default function FlashcardsPage() {
  return (
    <>
      <VideoBackground />
      <PageTransition label="Opening flashcards..." />
      <Suspense>
        <FlashcardsContent />
      </Suspense>
    </>
  );
}
