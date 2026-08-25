"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import VideoBackground from "@/components/VideoBackground";
import PageTransition from "@/components/PageTransition";
import { fetchDashboard, deleteLecture, type DashboardData } from "@/lib/api";

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffDays = Math.floor(diffMs / 86_400_000);
  if (diffDays < 0) return d.toLocaleDateString();
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return d.toLocaleDateString();
}

function SkeletonCard() {
  return (
    <article className="library-card" aria-hidden="true">
      <span className="skeleton-heading" />
      <span className="skeleton-line sk-md sk-w-60" />
      <div className="skeleton-chip-row">
        <span className="skeleton-pill sk-narrow" />
        <span className="skeleton-pill sk-narrow" />
        <span className="skeleton-pill sk-narrow" />
      </div>
      <span className="skeleton-line sk-md sk-w-85" />
      <span className="skeleton-line sk-md sk-w-50" />
      <div className="skeleton-chip-row">
        <span className="skeleton-pill" />
        <span className="skeleton-pill sk-narrow" />
        <span className="skeleton-pill" />
      </div>
    </article>
  );
}

export default function LibraryPage() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.body.className = "landing qa docs library-page";
    return () => {
      document.body.className = "landing";
    };
  }, []);

  useEffect(() => {
    fetchDashboard()
      .then(setDashboard)
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (lectureId: string) => {
    if (!confirm("Delete this lecture and all its generated materials?")) return;
    await deleteLecture(lectureId);
    const updated = await fetchDashboard();
    setDashboard(updated);
  };

  const sourceLabel = (type?: string) =>
    (type || "lecture").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <>
      <VideoBackground />
      <PageTransition label="Opening library..." />

      <main className="chat-shell notes-shell docs-shell library-shell">
        {/* ── Header ── */}
        <header className="chat-header">
          <div className="chat-title">Library Dashboard</div>
          <div className="chat-meta">
            {dashboard?.has_due_cards && (
              <Link className="pill pill-primary" href="/flashcards">
                Review Due Today
              </Link>
            )}
            <Link className="pill" href="/">
              Process Lecture
            </Link>
          </div>
        </header>

        {loading ? (
          <div className="library-grid">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : dashboard ? (
          <>
            {/* ── Overview ── */}
            <section className="library-overview">
              <div className="library-hero">
                <p className="doc-kicker">Study control center</p>
                <h2 className="doc-heading">
                  Keep lectures, review, and weak areas in one place
                </h2>
                <p className="doc-intro">
                  Use the dashboard to reopen lectures, clear due cards, and
                  focus on the concepts your quizzes say need more work.
                </p>
              </div>

              <div className="library-stats-grid">
                <article className="library-stat-card">
                  <span className="library-stat-label">Due Today</span>
                  <strong className="library-stat-value">
                    {dashboard.stats.due_today}
                  </strong>
                </article>
                <article className="library-stat-card">
                  <span className="library-stat-label">Overdue</span>
                  <strong className="library-stat-value">
                    {dashboard.stats.overdue}
                  </strong>
                </article>
                <article className="library-stat-card">
                  <span className="library-stat-label">In Rotation</span>
                  <strong className="library-stat-value">
                    {dashboard.stats.lectures_in_rotation}
                  </strong>
                </article>
                <article className="library-stat-card">
                  <span className="library-stat-label">Lectures</span>
                  <strong className="library-stat-value">
                    {dashboard.stats.lecture_count}
                  </strong>
                </article>
              </div>
            </section>

            {/* ── Lecture Library ── */}
            <section className="library-section">
              <div className="library-section-head">
                <div>
                  <p className="doc-kicker">Lecture Library</p>
                  <h3 className="doc-heading">All processed lectures</h3>
                </div>
                {dashboard.has_due_cards && (
                  <Link className="pill" href="/flashcards">
                    Grouped Due View
                  </Link>
                )}
              </div>

              {dashboard.lectures.length > 0 ? (
                <div className="library-grid">
                  {dashboard.lectures.map((lecture: any) => (
                    <article key={lecture.lecture_id} className="library-card">
                      <div className="library-card-head">
                        <div>
                          <h4>{lecture.title || lecture.lecture_id}</h4>
                          <p>{lecture.source_label || lecture.lecture_id}</p>
                        </div>
                        <div className="library-chip-row">
                          <span className="pill pill-muted">
                            {sourceLabel(lecture.source_type)}
                          </span>
                          {!!lecture.overdue_count && (
                            <span className="pill pill-danger">
                              {lecture.overdue_count} overdue
                            </span>
                          )}
                          {!!lecture.due_today_count && (
                            <span className="pill pill-warn">
                              {lecture.due_today_count} due
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="library-chip-row">
                        {lecture.has_summary && (
                          <span className="pill pill-success">Summary</span>
                        )}
                        {lecture.has_notes && (
                          <span className="pill pill-success">Notes</span>
                        )}
                        {lecture.has_quiz && (
                          <span className="pill pill-success">Quiz</span>
                        )}
                        {lecture.has_flashcards && (
                          <span className="pill pill-success">Flashcards</span>
                        )}
                      </div>

                      <div className="library-metrics">
                        <span>
                          Last quiz:{" "}
                          {lecture.last_quiz_score != null
                            ? `${lecture.last_quiz_score}%`
                            : "Not attempted"}
                        </span>
                        <span>
                          Last opened:{" "}
                          {formatTimestamp(
                            lecture.last_opened_at || lecture.created_at
                          )}
                        </span>
                      </div>

                      {lecture.weak_concepts?.length > 0 && (
                        <div className="library-weaknesses">
                          <span className="library-subhead">Weak concepts</span>
                          <div className="library-chip-row">
                            {lecture.weak_concepts.slice(0, 4).map((c: any, i: number) => (
                              <span key={i} className="pill pill-muted">
                                {c.label}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="library-card-actions">
                        <Link
                          className="pill pill-primary"
                          href={`/qa?lecture_id=${encodeURIComponent(lecture.lecture_id)}&src_url=${encodeURIComponent(lecture.source_url || "")}`}
                        >
                          Q&amp;A
                        </Link>
                        <Link
                          className="pill"
                          href={`/flashcards?lecture_id=${encodeURIComponent(lecture.lecture_id)}`}
                        >
                          {lecture.has_flashcards ? "Flashcards" : "Generate Flashcards"}
                        </Link>
                        <Link
                          className="pill"
                          href={`/summary?lecture_id=${encodeURIComponent(lecture.lecture_id)}`}
                        >
                          {lecture.has_summary ? "Summary" : "Generate Summary"}
                        </Link>
                        <Link
                          className="pill"
                          href={`/notes?lecture_id=${encodeURIComponent(lecture.lecture_id)}`}
                        >
                          {lecture.has_notes ? "Notes" : "Generate Notes"}
                        </Link>
                        <Link
                          className="pill"
                          href={`/quiz?lecture_id=${encodeURIComponent(lecture.lecture_id)}`}
                        >
                          {lecture.has_quiz ? "Quiz" : "Generate Quiz"}
                        </Link>
                        <button
                          className="pill pill-danger"
                          type="button"
                          onClick={() => handleDelete(lecture.lecture_id)}
                        >
                          Delete
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <section className="chat-empty">
                  No processed lectures yet. Start by uploading a lecture or
                  pasting a YouTube URL.
                </section>
              )}
            </section>
          </>
        ) : null}
      </main>
    </>
  );
}
