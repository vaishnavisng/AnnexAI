"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import VideoBackground from "@/components/VideoBackground";
import PageTransition from "@/components/PageTransition";
import { processLecture } from "@/lib/api";

type Mode = "youtube" | "upload";

export default function Home() {
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("youtube");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toggleRef = useRef<HTMLDivElement>(null);

  const positionHighlight = useCallback(
    (m: Mode) => {
      const toggle = toggleRef.current;
      if (!toggle) return;
      const btns = toggle.querySelectorAll<HTMLButtonElement>(".mode-btn");
      const active = Array.from(btns).find((b) => b.dataset.mode === m);
      if (!active) return;
      toggle.style.setProperty("--highlight-x", `${active.offsetLeft}px`);
      toggle.style.setProperty("--highlight-w", `${active.offsetWidth}px`);
    },
    []
  );

  useEffect(() => {
    positionHighlight(mode);
    const onResize = () => positionHighlight(mode);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [mode, positionHighlight]);

  useEffect(() => {
    if (mode === "youtube") textareaRef.current?.focus();
  }, [mode]);

  const autoResize = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = Math.min(160, ta.scrollHeight) + "px";
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    setError(null);
  };

  const handleSubmit = async () => {
    if (loading) return;

    if (mode === "youtube" && !youtubeUrl.trim()) return;
    if (mode === "upload" && !selectedFile) return;

    setLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("source_type", mode);

      if (mode === "youtube") {
        formData.append("youtube_url", youtubeUrl.trim());
      } else if (selectedFile) {
        formData.append("video_file", selectedFile);
      }

      const data = await processLecture(formData);

      if (data.error || !data.lecture_id) {
        throw new Error(data.error || "Processing failed — no lecture ID returned.");
      }

      const lectureId = data.lecture_id;
      const srcUrl = mode === "youtube" ? youtubeUrl.trim() : "";
      router.push(
        `/qa?lecture_id=${encodeURIComponent(lectureId)}&src_url=${encodeURIComponent(srcUrl)}`
      );
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      setError(message);
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mode !== "youtube") return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
  };

  const hintText =
    mode === "youtube"
      ? "Paste a YouTube lecture link and press Enter"
      : "Upload an offline lecture video.";

  return (
    <>
      <VideoBackground />
      <PageTransition />

      <main className="landing-wrap">
        <h1 className="brand-title">AnnexAI</h1>

        <div className="feature-strip">
          <Link className="pill" href="/library">
            Open Library Dashboard
          </Link>
        </div>

        {error && (
          <div className="flash-stack">
            <div className="flash flash-error">{error}</div>
          </div>
        )}

        <div
          ref={toggleRef}
          className="mode-toggle"
          role="tablist"
          aria-label="Input source mode"
        >
          <span className="mode-highlight" aria-hidden="true" />
          <button
            className={`mode-btn${mode === "youtube" ? " active" : ""}`}
            type="button"
            data-mode="youtube"
            onClick={() => switchMode("youtube")}
          >
            YouTube URL
          </button>
          <button
            className={`mode-btn${mode === "upload" ? " active" : ""}`}
            type="button"
            data-mode="upload"
            onClick={() => switchMode("upload")}
          >
            Upload Video
          </button>
        </div>

        <div className={`chatbox${loading ? " is-loading" : ""}`}>
          <div className="input-stack">
            <div
              className={`input-pane${mode === "youtube" ? " active" : ""}`}
            >
              <textarea
                ref={textareaRef}
                className="chat-input"
                placeholder="Drop your youtube link here"
                rows={1}
                autoCapitalize="none"
                autoComplete="off"
                spellCheck={false}
                inputMode="url"
                value={youtubeUrl}
                readOnly={loading}
                onInput={autoResize}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                onKeyDown={handleKeyDown}
              />
            </div>

            <div
              className={`input-pane${mode === "upload" ? " active" : ""}`}
            >
              <label className="upload-dropzone" htmlFor="videoFile">
                <span className="upload-title">
                  Drop or choose a video file
                </span>
                <span className="upload-meta">
                  MP4, MKV, AVI, MOV up to 500 MB
                </span>
                <span className="upload-file-row">
                  <span className="upload-choose-btn">Choose file</span>
                  <span className="upload-file-name">
                    {selectedFile ? selectedFile.name : "No file selected yet."}
                  </span>
                </span>
                <input
                  ref={fileInputRef}
                  id="videoFile"
                  type="file"
                  accept=".mp4,.mkv,.avi,.mov,video/*"
                  onChange={handleFileChange}
                />
              </label>
            </div>
          </div>

          <button
            className="send-btn"
            type="button"
            aria-label="Send"
            disabled={loading}
            onClick={handleSubmit}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 12h13" />
              <path d="M12 5l7 7-7 7" />
            </svg>
          </button>

          <div className="submit-spinner" aria-hidden="true">
            <div className="ring-spinner" aria-hidden="true" />
          </div>
        </div>

        <p className="hint">{hintText}</p>
      </main>
    </>
  );
}
