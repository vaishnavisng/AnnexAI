"use client";

import { useEffect, useRef, useState, useCallback, Suspense, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import VideoBackground from "@/components/VideoBackground";
import PageTransition from "@/components/PageTransition";
import { renderRichText, enhanceCodeBlocks } from "@/lib/richtext";
import { getStreamUrl, synthesizeSpeech } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

interface Segment {
  start?: number;
  start_time?: number;
  end?: number;
  end_time?: number;
  rank?: number;
}

interface Turn {
  q: string;
  a: string;
  mode?: string;
  timestamp?: number | null;
  srcUrl?: string;
  segments?: Segment[];
}

function toClock(seconds: number): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function makeJumpUrl(srcUrl: string, timestamp: number): string {
  if (!srcUrl || timestamp == null) return "";
  const t = Math.max(0, Math.floor(Number(timestamp)));
  try {
    const u = new URL(srcUrl);
    u.searchParams.set("t", `${t}s`);
    return u.toString();
  } catch {
    const sep = srcUrl.includes("?") ? "&" : "?";
    return `${srcUrl}${sep}t=${t}s`;
  }
}

function storageKey(lectureId: string): string {
  return `cognify_chat_${lectureId || "default"}`;
}

function loadHistory(lectureId: string): Turn[] {
  try {
    return JSON.parse(localStorage.getItem(storageKey(lectureId)) || "[]");
  } catch {
    return [];
  }
}

function saveHistory(lectureId: string, hist: Turn[]) {
  localStorage.setItem(storageKey(lectureId), JSON.stringify(hist));
}

/* ------------------------------------------------------------------ */
/*  SSE helpers                                                       */
/* ------------------------------------------------------------------ */

interface SseEvent {
  eventName: string;
  data: string;
}

function parseSseBlock(block: string): SseEvent {
  const lines = String(block || "").split("\n");
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  return { eventName, data: dataLines.join("\n") };
}

function safeParseJson(raw: string): Record<string, any> | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function consumeSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (eventName: string, data: string) => Promise<void> | void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replace(/\r/g, "");

    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";

    for (const block of blocks) {
      if (!block.trim()) continue;
      const parsed = parseSseBlock(block);
      if (!parsed.data && parsed.eventName === "message") continue;
      await onEvent(parsed.eventName, parsed.data);
    }

    if (done) break;
  }

  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed.data || parsed.eventName !== "message") {
      await onEvent(parsed.eventName, parsed.data);
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                    */
/* ------------------------------------------------------------------ */

function SpeakerIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 10v4a1 1 0 0 0 1 1h3l4 3.5a1 1 0 0 0 1.7-.75V6.25A1 1 0 0 0 11 5.5L7 9H4a1 1 0 0 0-1 1z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M18 6a8 8 0 0 1 0 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
    </svg>
  );
}

interface SpeakButtonProps {
  text: string;
  messageId: string;
  playingId: string | null;
  setPlayingId: (id: string | null) => void;
}

function SpeakButton({ text, messageId, playingId, setPlayingId }: SpeakButtonProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPlaying = playingId === messageId;

  // Stop our audio when another bubble starts playing.
  useEffect(() => {
    if (!isPlaying && audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
  }, [isPlaying]);

  // Revoke blob URL on unmount.
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
      }
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, []);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    if (playingId === messageId) {
      setPlayingId(null);
    }
  }, [messageId, playingId, setPlayingId]);

  const handleClick = useCallback(async () => {
    if (isLoading) return;

    if (isPlaying) {
      stopAudio();
      return;
    }

    setError(null);

    try {
      let audio = audioRef.current;
      if (!audio || !blobUrlRef.current) {
        setIsLoading(true);
        const url = await synthesizeSpeech(text);
        blobUrlRef.current = url;
        audio = new Audio(url);
        audio.preload = "auto";
        audio.onended = () => {
          if (audioRef.current) audioRef.current.currentTime = 0;
          setPlayingId(null);
        };
        audio.onerror = () => {
          setError("Playback failed.");
          setPlayingId(null);
        };
        audioRef.current = audio;
        setIsLoading(false);
      }

      setPlayingId(messageId);
      audio.currentTime = 0;
      await audio.play();
    } catch (err: any) {
      setIsLoading(false);
      setError(err?.message || "Could not generate audio.");
      if (playingId === messageId) setPlayingId(null);
    }
  }, [isLoading, isPlaying, messageId, playingId, setPlayingId, stopAudio, text]);

  const disabled = !text || isLoading;
  const labelText = isLoading ? "Generating..." : isPlaying ? "Tap to stop" : "Tap to play";
  const ariaLabel = isPlaying ? "Stop audio" : "Play audio";

  return (
    <div className="speak-btn-wrap">
      <button
        type="button"
        className={`speak-btn ${isPlaying ? "is-playing" : ""} ${isLoading ? "is-loading" : ""}`}
        onClick={handleClick}
        disabled={disabled}
        aria-label={ariaLabel}
        title={ariaLabel}
      >
        <span className="speak-btn-label">{labelText}</span>
        <span className="speak-btn-icon" aria-hidden="true">
          {isLoading ? <span className="speak-spinner" /> : isPlaying ? <StopIcon /> : <SpeakerIcon />}
        </span>
      </button>
      {error && <span className="speak-error">{error}</span>}
    </div>
  );
}

function SegmentDropdown({
  segments,
  srcUrl,
}: {
  segments: Segment[];
  srcUrl: string;
}) {
  if (!segments.length) return null;
  return (
    <details className="segment-dropdown">
      <summary className="segment-summary">Relevant segments to rewatch</summary>
      <div className="segment-list">
        {segments.map((seg, i) => {
          const start = Number(seg.start ?? seg.start_time ?? 0);
          const end = Number(seg.end ?? seg.end_time ?? start);
          const rank = Number(seg.rank || i + 1);
          const label = `[${rank}] ${toClock(start)}-${toClock(end)}`;
          const jumpUrl = makeJumpUrl(srcUrl, start);
          return (
            <div key={i} className="segment-item">
              {jumpUrl ? (
                <a className="segment-link" href={jumpUrl} target="_blank" rel="noopener noreferrer">
                  {label}
                </a>
              ) : (
                <span className="segment-link segment-link-disabled">{label}</span>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="msg user">
      <div className="bubble user">
        <div className="bubble-text">{text}</div>
      </div>
    </div>
  );
}

function AssistantBubble({
  turn,
  srcUrl,
  bubbleRef,
  messageId,
  playingId,
  setPlayingId,
}: {
  turn: Turn;
  srcUrl: string;
  bubbleRef?: React.Ref<HTMLDivElement>;
  messageId: string;
  playingId: string | null;
  setPlayingId: (id: string | null) => void;
}) {
  const segments = Array.isArray(turn.segments) ? turn.segments : [];
  return (
    <div className="msg assistant">
      <div className="bubble assistant" ref={bubbleRef}>
        <div
          className="bubble-text rich-text"
          dangerouslySetInnerHTML={{ __html: renderRichText(turn.a || "") }}
        />
        <div className="bubble-actions">
          <SpeakButton
            text={turn.a || ""}
            messageId={messageId}
            playingId={playingId}
            setPlayingId={setPlayingId}
          />
        </div>
        <SegmentDropdown segments={segments} srcUrl={turn.srcUrl || srcUrl} />
      </div>
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="msg assistant">
      <div className="bubble assistant thinking-bubble" aria-label="Assistant is thinking">
        <span className="thinking-dot" />
        <span className="thinking-dot" />
        <span className="thinking-dot" />
      </div>
    </div>
  );
}

function StreamingBubble({
  answer,
  segments,
  srcUrl,
  isFinal,
  bubbleRef,
  messageId,
  playingId,
  setPlayingId,
}: {
  answer: string;
  segments: Segment[];
  srcUrl: string;
  isFinal: boolean;
  bubbleRef?: React.Ref<HTMLDivElement>;
  messageId: string;
  playingId: string | null;
  setPlayingId: (id: string | null) => void;
}) {
  if (!answer) return <ThinkingBubble />;
  return (
    <div className="msg assistant">
      <div className="bubble assistant" ref={bubbleRef}>
        <div
          className="bubble-text rich-text"
          dangerouslySetInnerHTML={{ __html: renderRichText(answer) }}
        />
        {isFinal && (
          <>
            <div className="bubble-actions">
              <SpeakButton
                text={answer}
                messageId={messageId}
                playingId={playingId}
                setPlayingId={setPlayingId}
              />
            </div>
            <SegmentDropdown segments={segments} srcUrl={srcUrl} />
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main page                                                         */
/* ------------------------------------------------------------------ */

function QAContent() {
  const searchParams = useSearchParams();
  const lectureId = searchParams.get("lecture_id") || "";
  const srcUrl = searchParams.get("src_url") || "";

  const [history, setHistory] = useState<Turn[]>([]);
  const [topK, setTopK] = useState(3);
  const [inputValue, setInputValue] = useState("");
  const [sending, setSending] = useState(false);

  // Streaming state
  const [streamAnswer, setStreamAnswer] = useState("");
  const [streamSegments, setStreamSegments] = useState<Segment[]>([]);
  const [streamFinalized, setStreamFinalized] = useState(false);
  const [activeQuestion, setActiveQuestion] = useState<string | null>(null);

  // TTS: only one assistant bubble can be playing at a time.
  const [playingId, setPlayingId] = useState<string | null>(null);

  const chatScrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const streamBubbleRef = useRef<HTMLDivElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  // Add body classes for this page
  useEffect(() => {
    document.body.classList.add("qa", "qa-chat");
    return () => {
      document.body.classList.remove("qa", "qa-chat");
    };
  }, []);

  // Load history from localStorage on mount
  useEffect(() => {
    setHistory(loadHistory(lectureId));
  }, [lectureId]);

  // Enhance code blocks after history renders
  useEffect(() => {
    const el = chatScrollRef.current;
    if (el) enhanceCodeBlocks(el);
  }, [history]);

  // Enhance code blocks on final stream
  useEffect(() => {
    if (streamFinalized && streamBubbleRef.current) {
      enhanceCodeBlocks(streamBubbleRef.current);
    }
  }, [streamFinalized]);

  // Auto-scroll to bottom
  const scrollToBottom = useCallback((smooth = false) => {
    const el = chatScrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  useEffect(() => {
    scrollToBottom(false);
  }, [history, activeQuestion, streamAnswer, scrollToBottom]);

  // Scroll-button visibility
  const handleScroll = useCallback(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    const gap = el.scrollHeight - (el.scrollTop + el.clientHeight);
    setShowScrollBtn(gap > 60);
  }, []);

  // Auto-resize textarea
  const autoResize = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = `${Math.min(160, ta.scrollHeight)}px`;
  }, []);

  useEffect(() => {
    autoResize();
  }, [inputValue, autoResize]);

  // Cycle top-K
  const cycleTopK = () => setTopK((k) => (k >= 5 ? 1 : k + 1));

  // Clear chat
  const clearChat = () => {
    localStorage.removeItem(storageKey(lectureId));
    setHistory([]);
  };

  // Handle Enter key in textarea
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Submit question
  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    const question = inputValue.trim();
    if (!question || sending) return;

    setSending(true);
    setActiveQuestion(question);
    setStreamAnswer("");
    setStreamSegments([]);
    setStreamFinalized(false);
    setInputValue("");

    const currentHistory = loadHistory(lectureId);
    const recentHistory = currentHistory.slice(-4).map((t) => ({ q: t.q || "", a: t.a || "" }));

    const formData = new FormData();
    formData.set("lecture_id", lectureId);
    formData.set("src_url", srcUrl);
    formData.set("question", question);
    formData.set("top_k", String(topK));
    formData.set("conversation_history", JSON.stringify(recentHistory));

    let accumulated = "";
    let finalMode = "";
    let finalTimestamp: number | null = null;
    let finalSegments: Segment[] = [];
    let finalized = false;
    let firstChunkSeen = false;

    const finalizeTurn = (answerText: string, modeOverride = "") => {
      if (finalized) return;
      finalized = true;

      const resolvedAnswer = String(answerText || "").trim() || "Sorry, I could not produce an answer.";
      const resolvedMode = String(modeOverride || finalMode || (firstChunkSeen ? "gemini-rag" : "error"));
      const turn: Turn = {
        q: question,
        a: resolvedAnswer,
        mode: resolvedMode,
        timestamp: Number.isFinite(finalTimestamp) ? finalTimestamp : null,
        srcUrl,
        segments: Array.isArray(finalSegments) ? finalSegments : [],
      };

      const fresh = loadHistory(lectureId);
      fresh.push(turn);
      saveHistory(lectureId, fresh);
      setHistory(fresh);
      setStreamAnswer(resolvedAnswer);
      setStreamSegments(turn.segments || []);
      setStreamFinalized(true);
    };

    try {
      const response = await fetch(getStreamUrl(), {
        method: "POST",
        body: formData,
        headers: { Accept: "text/event-stream" },
      });

      if (!response.ok || !response.body) {
        const contentType = response.headers.get("content-type") || "";
        let errMsg: string;
        if (contentType.includes("application/json")) {
          const data = await response.json().catch(() => null);
          errMsg = data?.error ? String(data.error) : `Request failed with status ${response.status}.`;
        } else {
          const text = await response.text().catch(() => "");
          errMsg = text.trim() || `Request failed with status ${response.status}.`;
        }
        throw new Error(errMsg);
      }

      await consumeSse(response.body, async (eventName, rawData) => {
        const eventData = safeParseJson(rawData) || {};

        if (eventName === "meta") {
          if (Array.isArray(eventData.segments)) finalSegments = eventData.segments;
          if (eventData.timestamp != null) {
            const ts = Number(eventData.timestamp);
            finalTimestamp = Number.isFinite(ts) ? ts : finalTimestamp;
          }
          return;
        }

        if (eventName === "chunk") {
          const nextText = String(eventData.text || "");
          if (!nextText) return;
          firstChunkSeen = true;
          accumulated += nextText;
          setStreamAnswer(accumulated);
          return;
        }

        if (eventName === "error") {
          throw new Error(String(eventData.message || "Streaming failed."));
        }

        if (eventName === "done") {
          if (Array.isArray(eventData.segments)) finalSegments = eventData.segments;
          if (eventData.timestamp != null) {
            const ts = Number(eventData.timestamp);
            finalTimestamp = Number.isFinite(ts) ? ts : finalTimestamp;
          }
          finalMode = String(eventData.mode || finalMode || "");
          accumulated = String(eventData.answer || accumulated || "");
          finalizeTurn(accumulated, finalMode);
        }
      });

      if (!finalized) {
        finalizeTurn(accumulated, finalMode || (firstChunkSeen ? "gemini-rag" : "error"));
      }
    } catch (error: any) {
      const fallback =
        firstChunkSeen && accumulated
          ? accumulated
          : `Sorry, I couldn't answer that right now.\n\n${error?.message || "Please try again in a moment."}`;
      finalizeTurn(fallback, firstChunkSeen ? finalMode || "gemini-rag-partial" : "error");
    } finally {
      setSending(false);
      setActiveQuestion(null);
      textareaRef.current?.focus();
    }
  };

  const isEmpty = history.length === 0 && !activeQuestion;

  return (
    <>
      <PageTransition label="Opening Q&A..." />
      <VideoBackground />

      <main className="chat-shell">
        <header className="chat-header">
          <div className="chat-title">CognifyAI</div>
          <div className="chat-meta">
            {lectureId && (
              <>
                <Link className="pill" href="/library" data-transition-label="Opening library...">
                  Library
                </Link>
                <Link
                  className="pill"
                  href={`/flashcards?lecture_id=${encodeURIComponent(lectureId)}`}
                  data-transition-label="Opening flashcards..."
                >
                  Flashcards
                </Link>
                <Link
                  className="pill"
                  href={`/summary?lecture_id=${encodeURIComponent(lectureId)}`}
                  data-transition-label="Generating summary..."
                >
                  Summary
                </Link>
                <Link
                  className="pill"
                  href={`/notes?lecture_id=${encodeURIComponent(lectureId)}`}
                  data-transition-label="Generating notes..."
                >
                  Notes
                </Link>
                <Link
                  className="pill"
                  href={`/quiz?lecture_id=${encodeURIComponent(lectureId)}`}
                  data-transition-label="Generating quiz..."
                >
                  Quiz
                </Link>
              </>
            )}
            <Link className="pill" href="/" data-transition-label="Opening lectures...">
              Change lecture
            </Link>
          </div>
        </header>

        <div className="chat-main">
          <div className="chat-content">
            <div className="chat-scroll" ref={chatScrollRef} onScroll={handleScroll}>
              <div className="chat-messages">
                {isEmpty && (
                  <div className="chat-empty">Your conversation will appear here.</div>
                )}

                {history.map((turn, i) => (
                  <div key={i}>
                    <UserBubble text={turn.q} />
                    <AssistantBubble
                      turn={turn}
                      srcUrl={srcUrl}
                      messageId={`hist-${i}`}
                      playingId={playingId}
                      setPlayingId={setPlayingId}
                    />
                  </div>
                ))}

                {activeQuestion && (
                  <>
                    <UserBubble text={activeQuestion} />
                    <StreamingBubble
                      answer={streamAnswer}
                      segments={streamSegments}
                      srcUrl={srcUrl}
                      isFinal={streamFinalized}
                      bubbleRef={streamBubbleRef}
                      messageId="streaming"
                      playingId={playingId}
                      setPlayingId={setPlayingId}
                    />
                  </>
                )}
              </div>
            </div>

            <button
              className={`scroll-bottom-btn ${showScrollBtn ? "is-visible" : ""}`}
              type="button"
              aria-label="Scroll to latest message"
              onClick={() => scrollToBottom(true)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 5v14" />
                <path d="M6 13l6 6 6-6" />
              </svg>
            </button>
          </div>

          <aside className="chat-rail" aria-label="Chat controls">
            <button className="rail-btn" type="button" onClick={cycleTopK}>
              Top {topK}
            </button>
            <button className="rail-btn" type="button" onClick={clearChat}>
              Clear chat
            </button>
          </aside>
        </div>

        <div className="composer-bar">
          <form className="chatbox composer" onSubmit={handleSubmit}>
            <input type="hidden" name="lecture_id" value={lectureId} />
            <input type="hidden" name="src_url" value={srcUrl} />
            <input type="hidden" name="top_k" value={String(topK)} />

            <textarea
              ref={textareaRef}
              className="chat-input"
              name="question"
              placeholder="Ask a question about this lecture..."
              rows={1}
              required
              autoComplete="off"
              spellCheck={false}
              value={inputValue}
              readOnly={sending}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
            />

            <button
              className={`send-btn ${sending ? "is-sending" : ""}`}
              type="submit"
              aria-label="Send"
              disabled={sending}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 12h13" />
                <path d="M12 5l7 7-7 7" />
              </svg>
              <span className="btn-spinner" aria-hidden="true" />
            </button>
          </form>
        </div>
      </main>
    </>
  );
}

export default function QAPage() {
  return (
    <Suspense>
      <QAContent />
    </Suspense>
  );
}
