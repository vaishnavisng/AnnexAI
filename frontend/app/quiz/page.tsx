"use client";

import { useState, useEffect, useCallback, useMemo, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import VideoBackground from "@/components/VideoBackground";
import PageTransition from "@/components/PageTransition";
import {
  fetchQuiz,
  submitQuiz,
  regenerateQuiz,
  type QuizData,
  type QuizSubmitResult,
} from "@/lib/api";

type Answers = Record<string, string | string[]>;

function formatType(type: string): string {
  if (type === "multi_select") return "Multiple Correct";
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function resultClass(score: number): string {
  if (score >= 0.99) return "is-correct";
  if (score <= 0.01) return "is-wrong";
  return "is-partial";
}

function resultIcon(score: number): string {
  if (score >= 0.99) return "OK";
  if (score <= 0.01) return "NO";
  return "PART";
}

function QuizContent() {
  const searchParams = useSearchParams();
  const lectureId = searchParams.get("lecture_id") ?? "";

  const [quiz, setQuiz] = useState<QuizData | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [answers, setAnswers] = useState<Answers>({});
  const [results, setResults] = useState<QuizSubmitResult | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  const questions = quiz?.questions ?? [];
  const coaching = quiz?.coaching ?? {};
  const lectureMeta = quiz?.lecture_meta ?? {};

  const loadQuiz = useCallback(
    async (id: string) => {
      setLoading(true);
      setResults(null);
      setAnswers({});
      try {
        const data = await fetchQuiz(id);
        setQuiz(data);
      } catch {
        setQuiz(null);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (lectureId) loadQuiz(lectureId);
  }, [lectureId, loadQuiz]);

  useEffect(() => {
    document.body.className = "landing qa docs quiz-page";
    return () => {
      document.body.className = "";
    };
  }, []);

  const answeredCount = useMemo(() => {
    let count = 0;
    questions.forEach((_, i) => {
      const key = `q_${i + 1}`;
      const val = answers[key];
      if (Array.isArray(val) ? val.length > 0 : val && String(val).trim()) {
        count++;
      }
    });
    return count;
  }, [answers, questions]);

  const progressPct =
    questions.length > 0
      ? Math.min(100, (answeredCount / questions.length) * 100)
      : 0;

  const handleRadio = (key: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [key]: value }));
  };

  const handleCheckbox = (key: string, value: string, checked: boolean) => {
    setAnswers((prev) => {
      const current = Array.isArray(prev[key]) ? (prev[key] as string[]) : [];
      const next = checked
        ? [...current, value]
        : current.filter((v) => v !== value);
      return { ...prev, [key]: next };
    });
  };

  const handleText = (key: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    if (submitting || !lectureId) return;
    setSubmitting(true);
    try {
      const result = await submitQuiz(lectureId, answers);
      setResults(result);

      if (result.coaching) {
        setQuiz((prev) =>
          prev ? { ...prev, coaching: result.coaching } : prev
        );
      }
    } catch {
      // submission failed silently
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegenerate = async () => {
    if (regenerating || !lectureId) return;
    setRegenerating(true);
    try {
      const data = await regenerateQuiz(lectureId);
      setQuiz(data);
      setResults(null);
      setAnswers({});
    } catch {
      // regeneration failed silently
    } finally {
      setRegenerating(false);
    }
  };

  const totalScore = results?.total_score ?? null;
  const resultsList = results?.results ?? [];
  const recommendations = (coaching as any)?.recommendations as any[] | undefined;

  return (
    <>
      <VideoBackground />
      <PageTransition label="Generating quiz..." />

      <main className="chat-shell notes-shell docs-shell quiz-shell">
        <header className="chat-header">
          <div className="chat-title">Exam-Ready Quiz</div>
          <div className="chat-meta">
            <Link className="pill" href="/library">
              Library
            </Link>
            {lectureId && (
              <>
                <Link
                  className="pill"
                  href={`/flashcards?lecture_id=${encodeURIComponent(lectureId)}`}
                >
                  Flashcards
                </Link>
                <Link
                  className="pill"
                  href={`/qa?lecture_id=${encodeURIComponent(lectureId)}&src_url=${encodeURIComponent(lectureMeta.source_url ?? "")}`}
                >
                  Q&amp;A
                </Link>
                <Link
                  className="pill"
                  href={`/summary?lecture_id=${encodeURIComponent(lectureId)}`}
                >
                  Summary
                </Link>
                <Link
                  className="pill"
                  href={`/notes?lecture_id=${encodeURIComponent(lectureId)}`}
                >
                  Notes
                </Link>
              </>
            )}
            <Link className="pill" href="/">
              Change lecture
            </Link>
          </div>
        </header>

        {loading ? (
          <div className="quiz-skeleton-list" aria-hidden="true">
            {[1, 2, 3].map((n) => (
              <article className="quiz-skeleton-card" key={n}>
                <span className="skeleton-pill sk-narrow" />
                <span
                  className={`skeleton-heading${n === 2 ? " sk-w-50" : ""}`}
                />
                <div className="quiz-skeleton-options">
                  <span className="skeleton-line sk-lg sk-w-95" />
                  <span className="skeleton-line sk-lg sk-w-85" />
                  <span className="skeleton-line sk-lg sk-w-70" />
                  {n !== 3 && (
                    <span className="skeleton-line sk-lg sk-w-60" />
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <>
            {/* Quiz overview */}
            <section className="quiz-overview">
              <div className="quiz-overview-copy">
                <p className="doc-kicker">Practice mode</p>
                <h2 className="doc-heading">Assess your understanding</h2>
                <p className="doc-intro">
                  Answer each question, submit for instant feedback, then
                  regenerate for a fresh set.
                </p>
              </div>

              {totalScore !== null ? (
                <div className="quiz-scoreboard" aria-live="polite">
                  <div className="quiz-score-value">{totalScore}%</div>
                  <div className="quiz-score-track">
                    <ScoreFill target={totalScore} />
                  </div>
                </div>
              ) : (
                questions.length > 0 && (
                  <span className="pill pill-muted">
                    Questions: {questions.length}
                  </span>
                )
              )}

              {questions.length > 0 && (
                <div className="quiz-progress">
                  <div className="quiz-progress-bar">
                    <span
                      className="quiz-progress-fill"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  <span className="quiz-progress-text">
                    {answeredCount}/{questions.length} answered
                  </span>
                </div>
              )}
            </section>

            {/* Coaching panel */}
            {recommendations && recommendations.length > 0 && (
              <section className="quiz-coaching-panel">
                <div className="quiz-coaching-head">
                  <div>
                    <p className="doc-kicker">Weakness-Aware Coaching</p>
                    <h3 className="doc-heading">
                      Study next based on your recent performance
                    </h3>
                  </div>
                  {(coaching as any)?.last_quiz_score != null && (
                    <span className="pill pill-muted">
                      Latest score: {(coaching as any).last_quiz_score}%
                    </span>
                  )}
                </div>

                <div className="quiz-coaching-grid">
                  {recommendations.slice(0, 3).map((item: any, idx: number) => (
                    <article className="quiz-coaching-card" key={idx}>
                      <div className="quiz-card-top">
                        <span className="quiz-qno">{item.concept}</span>
                        <span className="quiz-type">
                          {item.mistakes} miss
                          {item.mistakes === 1 ? "" : "es"}
                        </span>
                      </div>
                      <div className="library-chip-row">
                        <span className="pill pill-warn">
                          Avg score: {Math.round((item.avg_score ?? 0) * 100)}%
                        </span>
                        <Link
                          className="pill"
                          href={`/flashcards?lecture_id=${encodeURIComponent(lectureId)}`}
                        >
                          Review Flashcards
                        </Link>
                      </div>
                      {item.segments && item.segments.length > 0 && (
                        <div className="library-chip-row">
                          {item.segments.map((seg: any, si: number) => (
                            <span className="pill pill-muted" key={si}>
                              {Math.round(seg.start)}s-{Math.round(seg.end)}s
                            </span>
                          ))}
                        </div>
                      )}
                      {item.actions && (
                        <div className="quiz-coaching-actions">
                          {item.actions.map((action: string, ai: number) => (
                            <p key={ai}>{action}</p>
                          ))}
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              </section>
            )}

            {/* Questions */}
            {questions.length > 0 ? (
              <>
                <div className="quiz-form">
                  {questions.map((q: any, i: number) => {
                    const qIndex = i + 1;
                    const answerKey = `q_${qIndex}`;
                    const result =
                      resultsList.length > 0 ? resultsList[i] : null;

                    return (
                      <section
                        className="quiz-card"
                        key={answerKey}
                        data-answer-key={answerKey}
                      >
                        <div className="quiz-card-top">
                          <span className="quiz-qno">Q{qIndex}</span>
                          <span className="quiz-type">
                            {formatType(q.type)}
                          </span>
                        </div>
                        <h3>{q.question}</h3>

                        {(q.type === "mcq" || q.type === "multi_select") && (
                          <>
                            {(q.options ?? []).map(
                              (option: string, oi: number) => {
                                const isMulti = q.type === "multi_select";
                                const currentVal = answers[answerKey];
                                const checked = isMulti
                                  ? Array.isArray(currentVal) &&
                                    currentVal.includes(option)
                                  : currentVal === option;

                                return (
                                  <label
                                    className={`quiz-option${isMulti ? " is-multi" : ""}`}
                                    key={oi}
                                  >
                                    <input
                                      type={isMulti ? "checkbox" : "radio"}
                                      name={answerKey}
                                      value={option}
                                      checked={checked}
                                      onChange={(e) =>
                                        isMulti
                                          ? handleCheckbox(
                                              answerKey,
                                              option,
                                              e.target.checked
                                            )
                                          : handleRadio(answerKey, option)
                                      }
                                    />
                                    <span>{option}</span>
                                  </label>
                                );
                              }
                            )}
                          </>
                        )}

                        {q.type === "true_false" && (
                          <>
                            {["True", "False"].map((val) => (
                              <label className="quiz-option" key={val}>
                                <input
                                  type="radio"
                                  name={answerKey}
                                  value={val}
                                  checked={answers[answerKey] === val}
                                  onChange={() => handleRadio(answerKey, val)}
                                />
                                <span>{val}</span>
                              </label>
                            ))}
                          </>
                        )}

                        {q.type === "short_answer" && (
                          <textarea
                            className="quiz-text"
                            name={answerKey}
                            rows={3}
                            placeholder="Write your answer"
                            value={
                              (answers[answerKey] as string | undefined) ?? ""
                            }
                            onChange={(e) =>
                              handleText(answerKey, e.target.value)
                            }
                          />
                        )}

                        {result && (
                          <div
                            className={`quiz-result ${resultClass(result.score)}`}
                          >
                            <span className="quiz-result-icon">
                              {resultIcon(result.score)}
                            </span>
                            <div className="quiz-result-row">
                              <span className="quiz-result-label">
                                Selected
                              </span>
                              <span className="quiz-result-value">
                                {result.user_answer || "No answer"}
                              </span>
                            </div>
                            <div className="quiz-result-row">
                              <span className="quiz-result-label">
                                Correct answer
                              </span>
                              <span className="quiz-result-value">
                                {result.correct}
                              </span>
                            </div>
                            <div className="quiz-result-row">
                              <span className="quiz-result-label">
                                Assessment
                              </span>
                              <span className="quiz-result-value">
                                {result.assessment} &bull;{" "}
                                {Math.round(result.score * 1000) / 10}%
                              </span>
                            </div>
                            {result.feedback && (
                              <div className="quiz-result-row">
                                <span className="quiz-result-label">
                                  Details
                                </span>
                                <span className="quiz-result-value">
                                  {result.feedback}
                                </span>
                              </div>
                            )}
                            <div className="quiz-result-row">
                              <span className="quiz-result-label">Why</span>
                              <span className="quiz-result-value">
                                {result.explanation}
                              </span>
                            </div>
                          </div>
                        )}
                      </section>
                    );
                  })}
                </div>

                <div className="quiz-actions">
                  <button
                    className="pill pill-primary"
                    type="button"
                    disabled={submitting}
                    onClick={handleSubmit}
                  >
                    {submitting ? "Checking..." : "Submit Quiz"}
                  </button>
                </div>

                <div className="quiz-actions-inline">
                  <button
                    className="pill"
                    type="button"
                    disabled={regenerating}
                    onClick={handleRegenerate}
                  >
                    {regenerating ? "Generating..." : "Regenerate Quiz"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <section className="chat-empty">
                  No questions generated yet. Try regenerating to create a new
                  quiz.
                </section>
                <div className="quiz-actions-inline">
                  <button
                    className="pill"
                    type="button"
                    disabled={regenerating}
                    onClick={handleRegenerate}
                  >
                    {regenerating ? "Generating..." : "Generate Quiz"}
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </main>
    </>
  );
}

export default function QuizPage() {
  return (
    <Suspense>
      <QuizContent />
    </Suspense>
  );
}

function ScoreFill({ target }: { target: number }) {
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const clamped = Math.max(0, Math.min(100, target));
    const raf = requestAnimationFrame(() => setWidth(clamped));
    return () => cancelAnimationFrame(raf);
  }, [target]);

  return (
    <span
      className="quiz-score-fill"
      style={{
        width: `${width}%`,
        transition: "width 0.8s cubic-bezier(.4,0,.2,1)",
      }}
    />
  );
}
