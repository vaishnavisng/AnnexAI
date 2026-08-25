"use client";

import { useEffect, useState } from "react";

export default function PageTransition({ label = "Loading..." }: { label?: string }) {
  const [active, setActive] = useState(true);

  useEffect(() => {
    requestAnimationFrame(() => requestAnimationFrame(() => setActive(false)));
  }, []);

  return (
    <div className={`page-transition ${active ? "active" : ""}`}>
      <div className="page-transition-content" role="status" aria-live="polite">
        <p className="page-transition-label page-transition-shimmer">{label}</p>
      </div>
    </div>
  );
}
