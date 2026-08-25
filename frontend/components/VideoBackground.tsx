"use client";

import { useEffect } from "react";

export default function VideoBackground() {
  useEffect(() => {
    if (typeof window !== "undefined" && (window as any).setupBoomerangBackground) {
      (window as any).setupBoomerangBackground("bgVideoA", "bgVideoB");
    }
  }, []);

  return (
    <>
      <video
        id="bgVideoA"
        className="bg-video is-active"
        muted
        playsInline
        preload="auto"
        data-forward="/intro-bg.mp4"
        data-reverse="/intro-bg-rev.mp4"
      />
      <video
        id="bgVideoB"
        className="bg-video"
        muted
        playsInline
        preload="auto"
        data-forward="/intro-bg.mp4"
        data-reverse="/intro-bg-rev.mp4"
      />
      <div className="bg-overlay" />
    </>
  );
}
